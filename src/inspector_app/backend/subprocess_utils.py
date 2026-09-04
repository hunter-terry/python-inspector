"""Small, careful subprocess helpers shared by every scanner and by the
GitHub retrieval and sandbox-execution code.

Rules enforced here, everywhere in the backend:
  - Never `shell=True`. Every call passes an argv list.
  - Every call has a timeout; nothing can hang the scan or the app forever.
  - Callers control which environment variables (if any) a child process
    inherits, so secrets are never handed to a process that does not need
    them.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ToolResult:
    """The outcome of running one external tool. Never raises for a normal
    tool exit, even a non-zero one -- non-zero is how bandit/ruff/pip-audit
    report "issues found", not a tool crash."""

    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    launch_failed: bool
    launch_error: str = ""


def run_tool(
    args: list[str],
    *,
    cwd: str | Path | None = None,
    timeout: float = 60.0,
    env: dict[str, str] | None = None,
) -> ToolResult:
    """Run one external tool and capture its result. Never uses shell=True.

    `env=None` means "inherit this process's environment" (fine for our own
    trusted read-only scanners). Pass an explicit dict to run with a
    controlled/minimal environment (required for anything touching
    untrusted project code).
    """
    try:
        completed = subprocess.run(
            args,
            cwd=str(cwd) if cwd is not None else None,
            capture_output=True,
            # Explicit utf-8, not `text=True` (which decodes using the
            # host's default codepage -- cp1252 on Windows). A scanned
            # project's files can contain arbitrary Unicode in comments,
            # docstrings, or string literals, which a scanner tool may echo
            # back in its own output; cp1252 can't decode all of that and
            # would crash the whole scan rather than just this one check.
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return ToolResult(
            exit_code=None,
            stdout=exc.stdout or "" if isinstance(exc.stdout, str) else "",
            stderr=exc.stderr or "" if isinstance(exc.stderr, str) else "",
            timed_out=True,
            launch_failed=False,
        )
    except (FileNotFoundError, OSError) as exc:
        return ToolResult(
            exit_code=None,
            stdout="",
            stderr="",
            timed_out=False,
            launch_failed=True,
            launch_error=str(exc),
        )
    return ToolResult(
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        timed_out=False,
        launch_failed=False,
    )


def module_invocation(module: str, *args: str) -> list[str]:
    """Invoke a tool as `<this interpreter> -m <module> ...`.

    Using `-m` with `sys.executable` guarantees we run the copy of the tool
    installed in the same venv as the running app, regardless of PATH.
    """
    return [sys.executable, "-m", module, *args]
