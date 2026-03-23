import os
import re
import shutil
import subprocess
import sys
import tempfile
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SANDBOX_BASE = Path(tempfile.gettempdir()) / "ai_agent"
MAX_EXECUTION_SECONDS = 180
MAX_OUTPUT_CHARS = 50_000

# Blocked command patterns
BLOCKED_PATTERNS = [
    r"rm\s+-rf\s+/",
    r"sudo\s+",
    r"mkfs",
    r"dd\s+if=",
    r":(){",          # fork bomb
    r"chmod\s+777\s+/",
    r"wget.*\|\s*sh",
    r"curl.*\|\s*sh",
    r">/dev/sd",
    r"shutdown",
    r"reboot",
    r"init\s+0",
    r"passwd",
    r"useradd",
    r"userdel",
]


def _is_safe_command(cmd: str) -> bool:
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            logger.warning(f"BLOCKED unsafe command: {cmd[:80]}")
            return False
    return True


def run_subprocess(cmd: list | str, cwd: str, env: dict = None, timeout: int = MAX_EXECUTION_SECONDS) -> dict:
    """Run a subprocess safely with timeout and output capture."""
    cmd_str = cmd if isinstance(cmd, str) else " ".join(cmd)
    if not _is_safe_command(cmd_str):
        return {"returncode": -1, "stdout": "", "stderr": f"BLOCKED: Unsafe command detected: {cmd_str[:100]}"}

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            env=env or os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=isinstance(cmd, str),
        )
        stdout = result.stdout[:MAX_OUTPUT_CHARS]
        stderr = result.stderr[:MAX_OUTPUT_CHARS]
        return {"returncode": result.returncode, "stdout": stdout, "stderr": stderr}
    except subprocess.TimeoutExpired:
        return {"returncode": -2, "stdout": "", "stderr": f"Execution timed out after {timeout}s"}
    except Exception as e:
        return {"returncode": -3, "stdout": "", "stderr": str(e)}


def clone_repo(clone_url: str, repo_name: str) -> dict:
    """Clone a GitHub repo into the sandbox directory."""
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", repo_name)
    target = SANDBOX_BASE / safe_name

    # Clean up previous run
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)

    result = run_subprocess(
        ["git", "clone", "--depth", "1", clone_url, str(target)],
        cwd=str(SANDBOX_BASE),
        timeout=60,
    )
    return {**result, "path": str(target)}


def create_venv(project_path: str) -> dict:
    """Create a virtual environment inside the project directory."""
    venv_path = os.path.join(project_path, "venv")
    python = sys.executable
    result = run_subprocess([python, "-m", "venv", venv_path], cwd=project_path, timeout=60)
    return {**result, "venv_path": venv_path}


def get_venv_python(project_path: str) -> str:
    """Return path to venv's python executable."""
    venv = os.path.join(project_path, "venv")
    if sys.platform == "win32":
        return os.path.join(venv, "Scripts", "python.exe")
    return os.path.join(venv, "bin", "python")


def get_venv_pip(project_path: str) -> str:
    venv = os.path.join(project_path, "venv")
    if sys.platform == "win32":
        return os.path.join(venv, "Scripts", "pip.exe")
    return os.path.join(venv, "bin", "pip")


def install_requirements(project_path: str) -> dict:
    """Install requirements.txt inside the venv."""
    pip = get_venv_pip(project_path)
    req_file = os.path.join(project_path, "requirements.txt")

    if not os.path.exists(req_file):
        return {"returncode": 0, "stdout": "No requirements.txt found", "stderr": ""}

    # Sanitize requirements - remove git+, svn+, file: to prevent arbitrary installs
    with open(req_file) as f:
        lines = f.readlines()
    safe_lines = [l for l in lines if not re.match(r"^\s*(git\+|svn\+|hg\+|file:)", l, re.IGNORECASE)]
    safe_req = os.path.join(project_path, "requirements_safe.txt")
    with open(safe_req, "w") as f:
        f.writelines(safe_lines)

    return run_subprocess(
        [pip, "install", "-r", safe_req, "--timeout", "30"],
        cwd=project_path,
        timeout=120,
    )


def install_package(project_path: str, package: str) -> dict:
    """Install a single package into venv."""
    # Sanitize package name
    if not re.match(r"^[a-zA-Z0-9_\-\.\[\]>=<!\s]+$", package):
        return {"returncode": -1, "stdout": "", "stderr": f"Unsafe package name: {package}"}
    pip = get_venv_pip(project_path)
    return run_subprocess([pip, "install", package.strip()], cwd=project_path, timeout=60)


def find_entry_point(project_path: str, language: str) -> Optional[str]:
    """Heuristically find the main entry point of the project."""
    p = Path(project_path)
    if language == "python":
        candidates = ["main.py", "app.py", "run.py", "server.py", "agent.py", "start.py", "__main__.py"]
        for c in candidates:
            if (p / c).exists():
                return c
        # Fallback: any .py in root
        py_files = list(p.glob("*.py"))
        if py_files:
            return py_files[0].name
    elif language in {"javascript", "typescript"}:
        pkg = p / "package.json"
        if pkg.exists():
            import json
            try:
                data = json.loads(pkg.read_text())
                main = data.get("main") or data.get("scripts", {}).get("start")
                if main:
                    return main
            except Exception:
                pass
        for c in ["index.js", "app.js", "server.js", "main.js"]:
            if (p / c).exists():
                return c
    return None


def run_python_project(project_path: str, entry_point: str) -> dict:
    python = get_venv_python(project_path)
    return run_subprocess(
        [python, entry_point],
        cwd=project_path,
        timeout=MAX_EXECUTION_SECONDS,
    )


def run_node_project(project_path: str) -> dict:
    pkg = os.path.join(project_path, "package.json")
    if not os.path.exists(pkg):
        return {"returncode": -1, "stdout": "", "stderr": "No package.json found"}

    # npm install
    install = run_subprocess(["npm", "install", "--no-audit", "--no-fund"], cwd=project_path, timeout=120)
    if install["returncode"] != 0:
        return install

    return run_subprocess(["npm", "start", "--", "--exit"], cwd=project_path, timeout=MAX_EXECUTION_SECONDS)


def cleanup_sandbox(repo_name: str):
    safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", repo_name)
    target = SANDBOX_BASE / safe_name
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
        logger.info(f"Cleaned up sandbox: {target}")
