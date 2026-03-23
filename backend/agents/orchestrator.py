import logging
import asyncio
from typing import AsyncIterator, Optional

from services.llm_service import check_ollama_available, get_available_models
from services.github_service import expand_query_to_keywords, search_github_repos, filter_and_rank_repos, get_repo_readme
from services.system_service import get_system_info, check_repo_compatibility
from services.sandbox_service import (
    clone_repo, create_venv, install_requirements,
    find_entry_point, run_python_project, run_node_project, cleanup_sandbox
)
from services.error_service import classify_error, attempt_self_heal, summarize_error

logger = logging.getLogger(__name__)


def _event(event_type: str, **kwargs) -> dict:
    return {"type": event_type, **kwargs}


class AgentOrchestrator:
    def __init__(self, github_token: Optional[str] = None):
        self.github_token = github_token

    async def run(self, query: str) -> AsyncIterator[dict]:
        """Main agent loop - yields progress events."""
        actions_taken = []
        fixes_applied = []

        # ── Step 0: Environment check ──────────────────────────────────────
        yield _event("status", step=0, message="Checking environment...")
        ollama_ok = check_ollama_available()
        models = get_available_models()
        yield _event("env_check", ollama_available=ollama_ok, models=models,
                     message="Ollama available" if ollama_ok else "⚠️ Ollama not running — using deterministic fallbacks")
        actions_taken.append(f"Environment checked. Ollama: {'OK' if ollama_ok else 'unavailable'}")
        await asyncio.sleep(0)

        # ── Step 1: Query Understanding ─────────────────────────────────────
        yield _event("status", step=1, message=f"Understanding query: '{query}'...")
        keywords = await asyncio.get_event_loop().run_in_executor(None, expand_query_to_keywords, query)
        yield _event("keywords", keywords=keywords, message=f"Search keywords: {keywords}")
        actions_taken.append(f"Query expanded to keywords: {keywords}")
        await asyncio.sleep(0)

        # ── Step 2: GitHub Search ───────────────────────────────────────────
        yield _event("status", step=2, message=f"Searching GitHub for: {keywords}")
        repos = await asyncio.get_event_loop().run_in_executor(
            None, search_github_repos, keywords, self.github_token
        )
        yield _event("github_results", count=len(repos), message=f"Found {len(repos)} repos")
        if not repos:
            yield _event("fatal", message="No repositories found. Try a different query or add a GitHub token.")
            return
        actions_taken.append(f"GitHub search returned {len(repos)} repos")
        await asyncio.sleep(0)

        # ── Step 3: System Info + Ranking ───────────────────────────────────
        yield _event("status", step=3, message="Analyzing system and ranking repos...")
        system_info = await asyncio.get_event_loop().run_in_executor(None, get_system_info)
        yield _event("system_info", **system_info)
        actions_taken.append(f"System: {system_info['os']}, Python: {system_info.get('python', 'N/A')}")

        ranked = await asyncio.get_event_loop().run_in_executor(
            None, filter_and_rank_repos, repos, system_info
        )
        if not ranked:
            yield _event("fatal", message="No compatible repositories found after filtering.")
            return

        repos_summary = [
            {"name": r["full_name"], "stars": r["stargazers_count"], "score": r["_score"],
             "language": r.get("language"), "description": r.get("description", "")[:100]}
            for r in ranked[:5]
        ]
        yield _event("ranked_repos", repos=repos_summary, message=f"Top {len(ranked)} repos ranked")
        await asyncio.sleep(0)

        # ── Steps 5–12: Try each repo until one succeeds (up to top 10) ────
        # Build candidate list: compatible ones first, then rest as fallback
        candidates = []
        for repo in ranked:
            compat = check_repo_compatibility(repo, system_info)
            if compat["compatible"]:
                candidates.append((repo, compat))
            else:
                yield _event("repo_skipped", name=repo["full_name"], issues=compat["issues"])

        # If no compatible repos found, try all ranked repos anyway
        if not candidates:
            yield _event("warning", message="No fully compatible repos found — will attempt all ranked repos")
            candidates = [(repo, {"compatible": False, "issues": [], "language": (repo.get("language") or "python").lower()}) for repo in ranked]

        MAX_ATTEMPTS = min(10, len(candidates))
        last_summary = ""
        succeeded = False

        for attempt_num, (selected, compat) in enumerate(candidates[:MAX_ATTEMPTS]):
            yield _event("repo_selected",
                         name=selected["full_name"],
                         stars=selected["stargazers_count"],
                         score=selected["_score"],
                         language=selected.get("language"),
                         url=selected["html_url"],
                         description=selected.get("description", ""),
                         attempt=attempt_num + 1,
                         total=MAX_ATTEMPTS,
                         message=f"[{attempt_num+1}/{MAX_ATTEMPTS}] Trying: {selected['full_name']} ⭐{selected['stargazers_count']}")
            actions_taken.append(f"Attempt {attempt_num+1}: {selected['full_name']}")
            await asyncio.sleep(0)

            repo_name = selected["name"]
            clone_url = selected["clone_url"]
            language = (selected.get("language") or "python").lower()

            # ── Clone ───────────────────────────────────────────────────────
            yield _event("status", step=5, message=f"Cloning {selected['full_name']}...")
            clone_result = await asyncio.get_event_loop().run_in_executor(
                None, clone_repo, clone_url, repo_name
            )
            if clone_result["returncode"] != 0:
                yield _event("warning", message=f"Clone failed: {clone_result['stderr'][:300]} — trying next repo...")
                actions_taken.append(f"Clone failed for {selected['full_name']}")
                continue
            project_path = clone_result["path"]
            yield _event("cloned", path=project_path, message=f"Cloned to {project_path}")
            await asyncio.sleep(0)

            # ── Setup + Execute ─────────────────────────────────────────────
            final_result = None
            entry = None

            if language == "python":
                yield _event("status", step=6, message="Creating virtual environment...")
                venv_result = await asyncio.get_event_loop().run_in_executor(None, create_venv, project_path)
                if venv_result["returncode"] != 0:
                    yield _event("warning", message=f"venv issue: {venv_result['stderr'][:200]}")

                yield _event("status", step=6, message="Installing dependencies...")
                req_result = await asyncio.get_event_loop().run_in_executor(None, install_requirements, project_path)
                if req_result["returncode"] != 0:
                    yield _event("warning", message=f"Dep warnings: {req_result['stderr'][:200]}")
                else:
                    yield _event("deps_installed", message="Dependencies installed")
                await asyncio.sleep(0)

                entry = find_entry_point(project_path, language)
                if not entry:
                    yield _event("warning", message=f"No entry point found in {selected['full_name']} — trying next repo...")
                    actions_taken.append(f"No entry point in {selected['full_name']}")
                    continue
                yield _event("entry_point", file=entry, message=f"Entry point: {entry}")

                yield _event("status", step=8, message=f"Running {entry}...")
                final_result = await asyncio.get_event_loop().run_in_executor(
                    None, run_python_project, project_path, entry
                )

            elif language in {"javascript", "typescript"}:
                yield _event("status", step=6, message="Running npm install + start...")
                final_result = await asyncio.get_event_loop().run_in_executor(None, run_node_project, project_path)
                actions_taken.append("npm install + npm start executed")

            else:
                yield _event("warning", message=f"Unsupported language '{language}' in {selected['full_name']} — trying next repo...")
                continue

            rc = final_result["returncode"]
            stdout = final_result["stdout"]
            stderr = final_result["stderr"]

            yield _event("execution_result",
                         returncode=rc,
                         stdout=stdout[:3000],
                         stderr=stderr[:3000],
                         message=f"Execution finished (exit code {rc})")

            # ── Success ─────────────────────────────────────────────────────
            if rc == 0:
                yield _event("done",
                             selected_repo=selected["full_name"],
                             status="success",
                             actions_taken=actions_taken,
                             fixes_applied=fixes_applied,
                             error_summary="",
                             logs=stdout[:5000],
                             message=f"✅ {selected['full_name']} ran successfully! (attempt {attempt_num+1})")
                succeeded = True
                break

            # ── Error Classification ────────────────────────────────────────
            yield _event("status", step=10, message="Classifying error...")
            classification = await asyncio.get_event_loop().run_in_executor(
                None, classify_error, stdout, stderr
            )
            yield _event("error_classified", classification=classification,
                         message=f"Error type: {classification['type']} — {classification['reason']}")
            actions_taken.append(f"Error in {selected['full_name']}: {classification['type']}")
            await asyncio.sleep(0)

            error_type = classification["type"]

            # Credentials — skip this repo, try next
            if error_type == "CREDENTIAL":
                yield _event("warning",
                             message=f"🔑 {selected['full_name']} needs credentials — trying next repo...")
                actions_taken.append(f"Skipped {selected['full_name']}: credentials required")
                continue

            # Large error — skip this repo, try next
            if error_type == "LARGE":
                last_summary = await asyncio.get_event_loop().run_in_executor(
                    None, summarize_error, stdout, stderr, classification
                )
                yield _event("warning",
                             message=f"❌ Large error in {selected['full_name']} — trying next repo... ({last_summary[:100]})")
                actions_taken.append(f"Skipped {selected['full_name']}: large error")
                continue

            # Small error — attempt self-healing then retry ONCE
            yield _event("status", step=11, message="Attempting self-healing...")
            heal_result = await asyncio.get_event_loop().run_in_executor(
                None, attempt_self_heal, project_path, stderr, stdout
            )
            fixes_applied.extend(heal_result["actions"])
            yield _event("self_heal", healed=heal_result["healed"], actions=heal_result["actions"],
                         message=f"Self-heal {'succeeded' if heal_result['healed'] else 'failed'}: {', '.join(heal_result['actions'])}")
            await asyncio.sleep(0)

            if not heal_result["healed"]:
                yield _event("warning", message=f"Self-healing failed for {selected['full_name']} — trying next repo...")
                actions_taken.append(f"Self-heal failed for {selected['full_name']}")
                continue

            # Retry after healing
            yield _event("status", step=12, message="Retrying after fix...")
            if language == "python":
                retry_result = await asyncio.get_event_loop().run_in_executor(
                    None, run_python_project, project_path, entry
                )
            else:
                retry_result = await asyncio.get_event_loop().run_in_executor(
                    None, run_node_project, project_path
                )

            actions_taken.append(f"Retried {selected['full_name']} after self-healing")
            yield _event("retry_result",
                         returncode=retry_result["returncode"],
                         stdout=retry_result["stdout"][:2000],
                         stderr=retry_result["stderr"][:2000])

            if retry_result["returncode"] == 0:
                yield _event("done",
                             selected_repo=selected["full_name"],
                             status="success",
                             actions_taken=actions_taken,
                             fixes_applied=fixes_applied,
                             error_summary="",
                             logs=retry_result["stdout"][:5000],
                             message=f"✅ {selected['full_name']} succeeded after self-healing! (attempt {attempt_num+1})")
                succeeded = True
                break
            else:
                last_summary = await asyncio.get_event_loop().run_in_executor(
                    None, summarize_error, retry_result["stdout"], retry_result["stderr"], classification
                )
                yield _event("warning",
                             message=f"Still failed after healing {selected['full_name']} — trying next repo...")
                actions_taken.append(f"Retry failed for {selected['full_name']}")
                continue

        # ── All attempts exhausted ──────────────────────────────────────────
        if not succeeded:
            yield _event("done",
                         selected_repo=ranked[0]["full_name"] if ranked else "none",
                         status="failed",
                         actions_taken=actions_taken,
                         fixes_applied=fixes_applied,
                         error_summary=last_summary or f"All {MAX_ATTEMPTS} repos failed. Try a more specific query or add a GitHub token.",
                         logs="",
                         message=f"❌ All {MAX_ATTEMPTS} repos attempted — none succeeded.")