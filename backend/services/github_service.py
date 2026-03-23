import requests
import logging
import time
from datetime import datetime, timezone
from typing import Optional
from services.llm_service import call_llm

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
SUPPORTED_LANGUAGES = {"python", "javascript", "typescript", "html", "css"}
DANGEROUS_TOPICS = {"malware", "exploit", "hack", "crack", "rootkit"}


def expand_query_to_keywords(query: str) -> str:
    """Use LLM to expand user query into GitHub search keywords."""
    prompt = (
        f"Convert this user query into 3-5 GitHub search keywords separated by spaces. "
        f"Return ONLY the keywords, nothing else.\n\nQuery: {query}"
    )
    keywords = call_llm(prompt, timeout=30)
    # Sanitize - keep only safe alphanumeric terms
    safe = " ".join(w for w in keywords.split() if w.isalnum() or w in ["+", "-"])
    logger.info(f"Expanded '{query}' → '{safe}'")
    return safe or query


def search_github_repos(keywords: str, token: Optional[str] = None, max_results: int = 20) -> list:
    """Search GitHub for repos matching keywords."""
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    params = {
        "q": f"{keywords} in:name,description,readme",
        "sort": "stars",
        "order": "desc",
        "per_page": max_results,
    }

    try:
        resp = requests.get(f"{GITHUB_API}/search/repositories", headers=headers, params=params, timeout=15)
        if resp.status_code == 403:
            logger.warning("GitHub rate limit hit")
            return []
        if resp.status_code == 422:
            # Try simpler query
            params["q"] = keywords.split()[0] if keywords else "agent"
            resp = requests.get(f"{GITHUB_API}/search/repositories", headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        items = resp.json().get("items", [])
        logger.info(f"GitHub returned {len(items)} repos for '{keywords}'")
        return items
    except Exception as e:
        logger.error(f"GitHub search failed: {e}")
        return []


def score_repo(repo: dict) -> float:
    """Score a repo 0–100 based on multiple signals."""
    score = 0.0

    # Stars (0–30 pts) — log scale
    stars = repo.get("stargazers_count", 0)
    import math
    star_score = min(30, math.log1p(stars) * 3)
    score += star_score

    # Recency (0–20 pts)
    pushed = repo.get("pushed_at", "")
    if pushed:
        try:
            pushed_dt = datetime.fromisoformat(pushed.replace("Z", "+00:00"))
            days_ago = (datetime.now(timezone.utc) - pushed_dt).days
            recency_score = max(0, 20 - (days_ago / 30))
            score += recency_score
        except Exception:
            pass

    # README quality (0–20 pts) — proxy: description + has_wiki + size
    if repo.get("description"):
        score += 8
        desc_len = len(repo.get("description", ""))
        score += min(7, desc_len / 20)
    if repo.get("has_wiki"):
        score += 5

    # Setup simplicity (0–20 pts) — proxy: smaller repos, no heavy deps signal
    size_kb = repo.get("size", 9999)
    if size_kb < 500:
        score += 20
    elif size_kb < 2000:
        score += 15
    elif size_kb < 10000:
        score += 8
    else:
        score += 2

    # Language match (0–10 pts)
    lang = (repo.get("language") or "").lower()
    if lang in SUPPORTED_LANGUAGES:
        score += 10
    elif lang in {"shell", "makefile"}:
        score += 5

    return round(score, 2)


def filter_and_rank_repos(repos: list, system_info: dict) -> list:
    """Filter unsafe/incompatible repos and rank by score."""
    scored = []
    for repo in repos:
        # Skip archived or dangerous
        if repo.get("archived"):
            continue
        name_lower = repo.get("full_name", "").lower()
        if any(t in name_lower for t in DANGEROUS_TOPICS):
            continue
        # Skip if language not supported
        lang = (repo.get("language") or "").lower()
        if lang and lang not in SUPPORTED_LANGUAGES and lang not in {"", "shell", "makefile", "dockerfile"}:
            continue
        # Skip extremely large repos (likely not simple to run)
        if repo.get("size", 0) > 500_000:
            continue

        score = score_repo(repo)
        scored.append({**repo, "_score": score})

    scored.sort(key=lambda r: r["_score"], reverse=True)
    return scored[:10]


def get_repo_readme(full_name: str, token: Optional[str] = None) -> str:
    """Fetch README content for a repo."""
    headers = {"Accept": "application/vnd.github.raw+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        resp = requests.get(f"{GITHUB_API}/repos/{full_name}/readme", headers=headers, timeout=10)
        if resp.status_code == 200:
            return resp.text[:3000]  # Truncate
    except Exception:
        pass
    return ""
