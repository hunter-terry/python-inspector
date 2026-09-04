"""Public-GitHub-only retrieval into a disposable workspace.

Deliberately narrow: only `https://github.com/<owner>/<repo>` URLs are
accepted, cloned anonymously (no credentials, ever), shallow, with a size
cap, a timeout, and a cooperative cancel check. Private repositories are out
of scope for V1 by design (see the work order) -- an anonymous clone of a
private repo simply fails, which is surfaced as a clear, honest failure
reason rather than a crash.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .fs_util import safe_rmtree

_GITHUB_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)

MAX_REPO_BYTES = 300 * 1024 * 1024  # 300 MB, generous for a Python project
CLONE_TIMEOUT_SECONDS = 180


@dataclass(frozen=True)
class CloneOutcome:
    ok: bool
    cancelled: bool = False
    error: str = ""


def validate_github_url(url: str) -> tuple[bool, str]:
    """Returns (is_valid, normalized_url_or_error_message)."""
    url = url.strip()
    match = _GITHUB_URL_RE.match(url)
    if not match:
        return False, (
            "That does not look like a public GitHub repository URL. "
            "Expected exactly https://github.com/<owner>/<repo> -- no credentials, "
            "query strings, or other hosts."
        )
    if "@" in url:
        return False, "URLs containing credentials are not accepted. V1 only clones public repositories anonymously."
    owner, repo = match.group("owner"), match.group("repo")
    return True, f"https://github.com/{owner}/{repo}.git"


def clone_repository(url: str, dest: Path, *, is_cancelled) -> CloneOutcome:
    """Shallow, anonymous, size-capped clone of a public GitHub repo.

    Polls `is_cancelled()` while the clone is in flight and terminates it
    promptly if set. Never passes credentials or the parent environment's
    secrets to git -- only a minimal explicit environment.
    """
    is_valid, normalized = validate_github_url(url)
    if not is_valid:
        return CloneOutcome(ok=False, error=normalized)

    dest.mkdir(parents=True, exist_ok=True)
    # Start from the real environment (Windows networking/TLS needs
    # SYSTEMROOT, TEMP, etc. to function at all) and strip only the pieces
    # that could supply git credentials, so an anonymous clone can never
    # succeed against a private repo using Hunter's own stored credentials.
    clone_env = dict(os.environ)
    for key in ("GIT_ASKPASS", "GITHUB_TOKEN", "GH_TOKEN", "GIT_TOKEN", "GIT_USERNAME", "GIT_PASSWORD", "SSH_AUTH_SOCK", "SSH_AGENT_PID"):
        clone_env.pop(key, None)
    clone_env["GIT_TERMINAL_PROMPT"] = "0"  # never hang waiting for a credential prompt
    clone_env["GIT_ASKPASS"] = "echo"  # any credential prompt gets a blank answer, not a real one

    args = [
        "git", "-c", "credential.helper=", "-c", "core.longpaths=true",
        "clone", "--depth", "1", "--no-tags", "--single-branch",
        normalized, str(dest),
    ]
    try:
        process = subprocess.Popen(
            args, cwd=None, env=clone_env, shell=False,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8", errors="replace",
        )
    except (FileNotFoundError, OSError) as exc:
        return CloneOutcome(ok=False, error=f"git is not available on this machine: {exc}")

    started = time.monotonic()
    while process.poll() is None:
        if is_cancelled():
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            safe_rmtree(dest)
            return CloneOutcome(ok=False, cancelled=True)
        if time.monotonic() - started > CLONE_TIMEOUT_SECONDS:
            process.kill()
            safe_rmtree(dest)
            return CloneOutcome(ok=False, error="Cloning this repository took too long and was stopped. It may be too large or the network may be slow.")
        time.sleep(0.2)

    _, stderr = process.communicate()
    if process.returncode != 0:
        safe_rmtree(dest)
        reason = _explain_git_failure(stderr or "")
        return CloneOutcome(ok=False, error=reason)

    size = _dir_size(dest)
    if size > MAX_REPO_BYTES:
        safe_rmtree(dest)
        return CloneOutcome(ok=False, error=f"This repository is larger than the {MAX_REPO_BYTES // (1024 * 1024)} MB limit for V1 inspection.")

    return CloneOutcome(ok=True)


def _explain_git_failure(stderr: str) -> str:
    lower = stderr.lower()
    if "could not resolve host" in lower or "network" in lower:
        return "The network is unavailable, or GitHub could not be reached."
    if "not found" in lower or "repository not found" in lower or "does not exist" in lower:
        return "This repository could not be found. It may not exist, or it may be private -- V1 only supports public repositories (select a private repository from a local folder instead)."
    if "authentication" in lower or "could not read username" in lower:
        return "This repository could not be cloned anonymously -- it is likely private. V1 only supports public repositories; select private repositories from a local folder instead."
    return "Cloning this repository failed. It may be private, may not exist, or the network may be unavailable."


def _dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


