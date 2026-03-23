import json
import re
import logging
from services.llm_service import call_llm
from services.sandbox_service import install_package

logger = logging.getLogger(__name__)

CREDENTIAL_SIGNALS = [
    "api key", "api_key", "token required", "apikey", "unauthorized", "401",
    "authentication", "credentials", "secret key", "openai_api", "stripe",
    "aws_access", "google_api", ".env", "set your", "add your key",
    "login required", "permission denied: api", "please provide",
]

SMALL_SIGNALS = [
    "modulenotfounderror", "no module named", "importerror",
    "no such file or directory", "requirement", "pip install",
    "version", "incompatible", "typeerror: can't", "attributeerror",
    "nameerror: name", "syntaxerror", "indentationerror",
    "filenotfounderror: [errno 2]",
]

LARGE_SIGNALS = [
    "segmentation fault", "core dumped", "killed", "out of memory",
    "cannot allocate", "broken pipe", "connection refused",
    "exit code 137", "killed by signal",
    "runtimeerror: cuda", "assert false",
]


def classify_error(stdout: str, stderr: str) -> dict:
    """Classify error using signals first, then LLM for ambiguous cases."""
    combined = (stdout + "\n" + stderr).lower()

    # Fast deterministic classification
    for sig in CREDENTIAL_SIGNALS:
        if sig in combined:
            return {
                "type": "CREDENTIAL",
                "reason": f"Credential signal detected: '{sig}'",
                "fix_possible": False,
            }

    for sig in LARGE_SIGNALS:
        if sig in combined:
            return {
                "type": "LARGE",
                "reason": f"Critical system error: '{sig}'",
                "fix_possible": False,
            }

    for sig in SMALL_SIGNALS:
        if sig in combined:
            return {
                "type": "SMALL",
                "reason": f"Fixable error signal: '{sig}'",
                "fix_possible": True,
            }

    # LLM fallback for ambiguous errors
    return _llm_classify(stdout, stderr)


def _llm_classify(stdout: str, stderr: str) -> dict:
    snippet = (stderr or stdout)[:1500]
    prompt = (
        "You are an error classifier. Classify this error output into one of three types:\n"
        "- SMALL: missing dependency, import error, version mismatch, missing file (fixable)\n"
        "- LARGE: logic failure, broken architecture, memory error, complex runtime crash\n"
        "- CREDENTIAL: API key, token, login, authentication required\n\n"
        f"ERROR OUTPUT:\n{snippet}\n\n"
        "Respond ONLY with valid JSON in this exact format (no markdown, no extra text):\n"
        '{"type":"SMALL","reason":"brief explanation","fix_possible":true}'
    )

    raw = call_llm(prompt, timeout=30)
    try:
        # Extract JSON from response
        match = re.search(r'\{[^}]+\}', raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
            if data.get("type") in {"SMALL", "LARGE", "CREDENTIAL"}:
                return data
    except Exception:
        pass

    return {"type": "LARGE", "reason": f"Unclassified error: {snippet[:200]}", "fix_possible": False}


def extract_missing_package(stderr: str) -> str | None:
    """Try to extract the missing package name from error output."""
    patterns = [
        r"No module named '([^']+)'",
        r"ModuleNotFoundError: No module named '([^']+)'",
        r"ImportError: No module named ([^\s]+)",
        r"pip install ([a-zA-Z0-9_\-]+)",
        r"Try: pip install ([a-zA-Z0-9_\-]+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, stderr, re.IGNORECASE)
        if m:
            pkg = m.group(1).split(".")[0]  # Take top-level package
            # Map common module names to pip packages
            MODULE_MAP = {
                "cv2": "opencv-python",
                "PIL": "Pillow",
                "sklearn": "scikit-learn",
                "bs4": "beautifulsoup4",
                "yaml": "pyyaml",
                "dotenv": "python-dotenv",
                "flask_cors": "flask-cors",
                "fastapi": "fastapi",
                "uvicorn": "uvicorn",
            }
            return MODULE_MAP.get(pkg, pkg)
    return None


def attempt_self_heal(project_path: str, stderr: str, stdout: str) -> dict:
    """
    Attempt to fix a SMALL error.
    Returns dict with fix description and whether it likely succeeded.
    """
    actions = []

    # Try to install missing package
    pkg = extract_missing_package(stderr)
    if pkg:
        logger.info(f"Self-heal: installing '{pkg}'")
        result = install_package(project_path, pkg)
        if result["returncode"] == 0:
            actions.append(f"Installed missing package: {pkg}")
            return {"healed": True, "actions": actions}
        else:
            actions.append(f"Failed to install {pkg}: {result['stderr'][:200]}")
            return {"healed": False, "actions": actions}

    # Ask LLM for a fix command
    snippet = (stderr or stdout)[:800]
    prompt = (
        f"Given this Python error:\n{snippet}\n\n"
        "Provide ONE shell command to fix it (pip install, export VAR=..., etc.).\n"
        "If it cannot be fixed with one command, reply: NO_FIX\n"
        "Reply with ONLY the command or NO_FIX."
    )
    fix_cmd = call_llm(prompt, timeout=20).strip()

    if fix_cmd and fix_cmd != "NO_FIX" and not fix_cmd.startswith("NO_FIX"):
        # Validate it's a safe pip/export command
        if re.match(r"^(pip\d? install|pip3 install|export \w+=)", fix_cmd, re.IGNORECASE):
            if "pip install" in fix_cmd.lower():
                pkg_match = re.search(r"pip\d* install\s+([a-zA-Z0-9_\-\.\s]+)", fix_cmd)
                if pkg_match:
                    pkg = pkg_match.group(1).strip().split()[0]
                    result = install_package(project_path, pkg)
                    if result["returncode"] == 0:
                        actions.append(f"LLM-suggested install: {pkg}")
                        return {"healed": True, "actions": actions}
            actions.append(f"LLM suggested: {fix_cmd} (could not apply safely)")
            return {"healed": False, "actions": actions}

    actions.append("No automatic fix available for this error")
    return {"healed": False, "actions": actions}


def summarize_error(stdout: str, stderr: str, classification: dict) -> str:
    """Generate a human-readable error summary using LLM."""
    snippet = (stderr or stdout)[:1000]
    prompt = (
        f"Summarize this error for a developer in 2-3 sentences. Be specific and helpful.\n"
        f"Error type: {classification.get('type')}\n"
        f"Error output:\n{snippet}"
    )
    return call_llm(prompt, timeout=20)
