import platform
import shutil
import subprocess
import psutil
import logging

logger = logging.getLogger(__name__)


def get_system_info() -> dict:
    """Collect current system capabilities."""
    info = {
        "os": platform.system(),
        "os_version": platform.version(),
        "arch": platform.machine(),
        "python": _get_cmd_version("python3 --version") or _get_cmd_version("python --version"),
        "node": _get_cmd_version("node --version"),
        "npm": _get_cmd_version("npm --version"),
        "git": _get_cmd_version("git --version"),
        "nvm": shutil.which("nvm") is not None,
        "pip": shutil.which("pip3") is not None or shutil.which("pip") is not None,
    }

    try:
        mem = psutil.virtual_memory()
        info["ram_gb"] = round(mem.total / (1024 ** 3), 1)
        info["ram_available_gb"] = round(mem.available / (1024 ** 3), 1)
        info["cpu_count"] = psutil.cpu_count(logical=True)
    except Exception:
        info["ram_gb"] = 0
        info["ram_available_gb"] = 0
        info["cpu_count"] = 1

    logger.info(f"System info: {info}")
    return info


def _get_cmd_version(cmd: str) -> str | None:
    try:
        result = subprocess.run(cmd.split(), capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            return result.stdout.strip().split("\n")[0]
    except Exception:
        pass
    return None


def check_repo_compatibility(repo: dict, system_info: dict) -> dict:
    """Return compatibility verdict for a repo given system info."""
    issues = []
    lang = (repo.get("language") or "").lower()
    size_kb = repo.get("size", 0)

    if lang == "python" and not system_info.get("python"):
        issues.append("Python not installed")
    if lang in {"javascript", "typescript"} and not system_info.get("node"):
        issues.append("Node.js not installed")
    if not system_info.get("git"):
        issues.append("Git not installed")

    # RAM check - reject repos > 50MB if RAM is low
    if size_kb > 50_000 and system_info.get("ram_available_gb", 0) < 1.0:
        issues.append(f"Repo size {size_kb//1024}MB may exceed available RAM")

    return {
        "compatible": len(issues) == 0,
        "issues": issues,
        "language": lang,
    }
