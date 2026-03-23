import requests
import logging
from typing import Optional

logger = logging.getLogger(__name__)

MODELS = ["llama3.1:8b", "mistral:7b-instruct", "phi3:mini"]
OLLAMA_URL = "http://localhost:11434"


def call_llm(prompt: str, system: Optional[str] = None, timeout: int = 60) -> str:
    """Call Ollama LLM with automatic fallback through model list."""
    full_prompt = f"{system}\n\n{prompt}" if system else prompt

    for model in MODELS:
        try:
            response = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": model, "prompt": full_prompt, "stream": False},
                timeout=timeout,
            )
            if response.status_code == 200:
                result = response.json().get("response", "")
                if result.strip():
                    logger.info(f"LLM responded using model: {model}")
                    return result.strip()
        except requests.exceptions.ConnectionError:
            logger.warning(f"Ollama not reachable. Is it running? (ollama serve)")
            return _fallback_response(prompt)
        except requests.exceptions.Timeout:
            logger.warning(f"Model {model} timed out, trying next...")
        except Exception as e:
            logger.warning(f"Model {model} failed: {e}")

    logger.error("All LLM models failed")
    return _fallback_response(prompt)


def _fallback_response(prompt: str) -> str:
    """Deterministic fallback when Ollama is unavailable."""
    p = prompt.lower()
    if "keyword" in p or "search term" in p:
        words = [w for w in prompt.split() if len(w) > 3 and w.isalpha()][:3]
        return " ".join(words) if words else "agent automation python"
    if "classify" in p or "error type" in p or "small" in p:
        if "modulenotfound" in p or "import" in p or "no module" in p:
            return '{"type":"SMALL","reason":"Missing dependency - can be installed","fix_possible":true}'
        if "api key" in p or "token" in p or "credential" in p or "auth" in p:
            return '{"type":"CREDENTIAL","reason":"API credentials required","fix_possible":false}'
        return '{"type":"LARGE","reason":"Complex error requiring manual investigation","fix_possible":false}'
    if "fix" in p or "patch" in p:
        return "pip install -r requirements.txt"
    return "Unable to process - Ollama not available. Please run: ollama serve"


def check_ollama_available() -> bool:
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def get_available_models() -> list:
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        if r.status_code == 200:
            return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        pass
    return []
