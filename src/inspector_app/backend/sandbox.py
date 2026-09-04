"""The approval-gated runtime executor's isolation layer.

Design decision (documented, per the work order's "smallest maintainable
toolchain" instruction): this backend uses Docker Desktop, already installed
on the target machine, to get real, provable isolation --
`--network none` genuinely disables network access for the container (unlike
trying to sandbox a bare subprocess on Windows, which has no equivalent to
Linux network namespaces / cgroups and cannot make an enforceable claim like
this), plus a memory/CPU/process-count cap and no inherited host environment.

If Docker cannot be reached, or the isolated runner image cannot be
built/verified, `check_isolation_available` reports why, and the caller
(`real_backend.run_approved_check`) refuses to run anything rather than
falling back to an unsandboxed subprocess. This is a deliberate, disclosed
V1 limitation: the runner image only has `pytest` installed (no project
dependencies), because installing arbitrary project dependencies would
require either network access during the "network disabled" run, or
silently `pip install`-ing unreviewed third-party code before running it --
both rejected as unsafe. Projects whose tests need third-party packages will
see an honest ImportError in the captured output rather than a successful
run.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from .subprocess_utils import run_tool

RUNNER_IMAGE = "python-inspector-runner:v1"
DOCKER_PROBE_TIMEOUT = 8.0
IMAGE_BUILD_TIMEOUT = 300.0
DEFAULT_RUN_TIMEOUT = 120.0
MEMORY_LIMIT = "512m"
CPU_LIMIT = "1"
PIDS_LIMIT = "256"

_DOCKERFILE = "FROM python:3.12-slim\nRUN pip install --no-cache-dir pytest==8.*\n"


def check_isolation_available() -> tuple[bool, str]:
    """Best-effort, honest check of whether we can prove real isolation right now."""
    if shutil.which("docker") is None:
        return False, "Docker is not installed (or not on PATH) on this machine."
    result = run_tool(["docker", "info", "--format", "{{.ServerVersion}}"], timeout=DOCKER_PROBE_TIMEOUT)
    if result.launch_failed:
        return False, f"Docker could not be reached ({result.launch_error})."
    if result.timed_out:
        return False, "Docker did not respond in time."
    if result.exit_code != 0:
        return False, "Docker Desktop is installed but its engine is not running. Start Docker Desktop and try again."
    return True, ""


def ensure_runner_image() -> tuple[bool, str]:
    """Make sure the (trusted, project-independent) pytest runner image exists locally."""
    inspect = run_tool(["docker", "image", "inspect", RUNNER_IMAGE], timeout=15)
    if inspect.exit_code == 0:
        return True, ""

    with tempfile.TemporaryDirectory(prefix="python-inspector-image-") as build_ctx:
        dockerfile_path = Path(build_ctx) / "Dockerfile"
        dockerfile_path.write_text(_DOCKERFILE, encoding="utf-8")
        build = run_tool(
            ["docker", "build", "-t", RUNNER_IMAGE, "-f", str(dockerfile_path), build_ctx],
            timeout=IMAGE_BUILD_TIMEOUT,
        )
    if build.exit_code != 0:
        detail = (build.stderr or build.stdout or "unknown error")[-500:]
        return False, f"Could not build the isolated runner image: {detail}"
    return True, ""


@dataclass(frozen=True)
class ContainerRunOutcome:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    launch_failed: bool = False
    launch_error: str = ""


def run_in_isolated_container(
    workspace: Path,
    command: list[str],
    *,
    timeout: float = DEFAULT_RUN_TIMEOUT,
) -> ContainerRunOutcome:
    """Run `command` inside a disposable, network-disabled container.

    - `--rm`: the container is removed the instant it stops, win or lose.
    - `--network none`: no network namespace is attached at all.
    - No `-e`/`--env-file`: the container gets Docker's own minimal default
      environment, never this process's environment or secrets.
    - Bounded memory/CPU/process count, and `no-new-privileges`.
    - A named container so a timeout can be enforced with `docker kill`,
      since killing our own CLI client would not otherwise stop it.
    """
    container_name = f"python-inspector-run-{uuid.uuid4().hex[:12]}"
    args = [
        "docker", "run", "--rm",
        "--name", container_name,
        "--network", "none",
        "--memory", MEMORY_LIMIT,
        "--cpus", CPU_LIMIT,
        "--pids-limit", PIDS_LIMIT,
        "--security-opt", "no-new-privileges",
        "-v", f"{workspace}:/workspace:rw",
        "-w", "/workspace",
        RUNNER_IMAGE,
        *command,
    ]
    try:
        # Explicit utf-8: the container's output is from a Linux process and
        # is not guaranteed to be valid in the host's default codepage
        # (cp1252 on Windows), which would otherwise crash a reader thread
        # and silently lose part of the captured output.
        process = subprocess.Popen(
            args, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            encoding="utf-8", errors="replace",
        )
    except (FileNotFoundError, OSError) as exc:
        return ContainerRunOutcome(None, "", "", False, launch_failed=True, launch_error=str(exc))

    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return ContainerRunOutcome(process.returncode, stdout, stderr, timed_out=False)
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "kill", container_name], capture_output=True, timeout=15, shell=False, check=False)
        try:
            stdout, stderr = process.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        return ContainerRunOutcome(None, stdout, stderr, timed_out=True)
