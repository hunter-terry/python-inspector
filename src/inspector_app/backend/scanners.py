"""The read-only, deterministic scanners.

Each `run_*` function takes a project directory and returns
`(ScannerRunRecord, tuple[Finding, ...])`. None of them ever writes to the
project directory or executes any code that belongs to the scanned project
itself -- they only read files and, for pip-audit, query public vulnerability
databases about package name/version pairs.

Every function is defensive: a tool crash, a missing tool, or unparseable
output becomes a FAILED or UNAVAILABLE ScannerRunRecord, never an exception
that reaches the caller, and never a silently-dropped check.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
import tempfile
from pathlib import Path

from ..models import (
    CheckOutcome,
    Confidence,
    Finding,
    FindingStatus,
    ScannerRunRecord,
    Severity,
)
from .findings_util import SECRET_VALUE_BANDIT_TEST_IDS, stable_finding_id
from .fs_util import IGNORED_DIR_NAMES, is_ignored
from .subprocess_utils import ToolResult, module_invocation, run_tool


def _relpath(project_dir: Path, absolute: str) -> str:
    try:
        return str(Path(absolute).resolve().relative_to(project_dir.resolve()))
    except ValueError:
        return absolute


# ---------------------------------------------------------------- ruff -----

_RUFF_VERSION = "unknown"


def _ruff_version() -> str:
    global _RUFF_VERSION
    if _RUFF_VERSION == "unknown":
        result = run_tool(module_invocation("ruff", "--version"), timeout=15)
        _RUFF_VERSION = result.stdout.strip().removeprefix("ruff ") if not result.launch_failed else "unavailable"
    return _RUFF_VERSION


def _classify_ruff(code: str) -> tuple[Severity, Confidence, FindingStatus]:
    if code.startswith("E9"):
        return Severity.CRITICAL, Confidence.HIGH, FindingStatus.CONFIRMED_FAILURE
    if code in ("F821", "F822", "F823"):
        return Severity.HIGH, Confidence.HIGH, FindingStatus.STRONG_FINDING
    if code in ("F401", "F841"):
        return Severity.LOW, Confidence.HIGH, FindingStatus.INFORMATIONAL
    if code.startswith("F"):
        return Severity.MEDIUM, Confidence.HIGH, FindingStatus.STRONG_FINDING
    return Severity.LOW, Confidence.MEDIUM, FindingStatus.INFORMATIONAL


def run_ruff(project_dir: Path) -> tuple[ScannerRunRecord, tuple[Finding, ...]]:
    version_probe = run_tool(module_invocation("ruff", "--version"), timeout=15)
    if version_probe.launch_failed or version_probe.exit_code != 0:
        return (
            ScannerRunRecord("ruff", "unavailable", CheckOutcome.UNAVAILABLE, "ruff is not installed in this environment."),
            (),
        )
    version = version_probe.stdout.strip().removeprefix("ruff ") or "unknown"

    with tempfile.TemporaryDirectory(prefix="python-inspector-ruff-cache-") as cache_dir:
        result = run_tool(
            module_invocation(
                "ruff", "check", "--output-format=json", "--exit-zero",
                "--cache-dir", cache_dir, str(project_dir),
            ),
            cwd=project_dir,
            timeout=120,
        )
    if result.timed_out:
        return (ScannerRunRecord("ruff", version, CheckOutcome.FAILED, "ruff timed out."), ())
    try:
        items = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        detail = (result.stderr or "could not parse ruff output").strip()[:500]
        return (ScannerRunRecord("ruff", version, CheckOutcome.FAILED, detail), ())

    findings: list[Finding] = []
    for item in items:
        code = item.get("code") or "?"
        severity, confidence, status = _classify_ruff(code)
        file_path = _relpath(project_dir, item.get("filename", ""))
        line_number = (item.get("location") or {}).get("row")
        finding_id = stable_finding_id("RUFF", code, file_path, str(line_number))
        findings.append(
            Finding(
                finding_id=finding_id,
                category="Code quality",
                severity=severity,
                confidence=confidence,
                status=status,
                summary=item.get("message", "").strip() or f"Ruff rule {code} was triggered.",
                what_could_happen=_ruff_impact(code),
                file_path=file_path,
                line_number=line_number,
                evidence=f"{code} ({item.get('name', '')}) at {file_path}:{line_number}",
                suggested_repair=_ruff_repair(code, item),
                verification_steps=("Re-run the code-quality scan and confirm this finding no longer appears.",),
                scanner_name="ruff",
                scanner_version=version,
            )
        )
    return (ScannerRunRecord("ruff", version, CheckOutcome.RAN), tuple(findings))


def _ruff_impact(code: str) -> str:
    if code.startswith("E9"):
        return "The file cannot even be parsed as valid Python, so it will fail immediately when run or imported."
    if code in ("F821", "F822", "F823"):
        return "This name is not defined anywhere Python can see, so running this code path will raise a NameError."
    if code in ("F401", "F841"):
        return "This is unused code. It does not break anything by itself, but it makes the file harder to read and maintain."
    return "This may make the code harder to read or slightly more error-prone, without necessarily being an active bug."


def _ruff_repair(code: str, item: dict) -> str:
    fix = item.get("fix")
    if fix and fix.get("message"):
        return str(fix["message"]) + "."
    return "Review the flagged line and address the rule described above."


# -------------------------------------------------------------- bandit -----

def run_bandit(project_dir: Path) -> tuple[ScannerRunRecord, tuple[Finding, ...]]:
    version_probe = run_tool(module_invocation("bandit", "--version"), timeout=15)
    if version_probe.launch_failed or version_probe.exit_code not in (0, 1):
        return (
            ScannerRunRecord("bandit", "unavailable", CheckOutcome.UNAVAILABLE, "bandit is not installed in this environment."),
            (),
        )
    version_match = re.search(r"(\d+\.\d+(?:\.\d+)?)", version_probe.stdout + version_probe.stderr)
    version = version_match.group(1) if version_match else "unknown"

    result = run_tool(
        # B101 (assert_used) is skipped: `assert` is idiomatic in test files
        # and bandit flags every occurrence, which is mostly noise rather
        # than a real security finding.
        module_invocation("bandit", "-r", "-f", "json", "-q", "--skip", "B101", str(project_dir)),
        cwd=project_dir,
        timeout=120,
    )
    if result.timed_out:
        return (ScannerRunRecord("bandit", version, CheckOutcome.FAILED, "bandit timed out."), ())
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        detail = (result.stderr or "could not parse bandit output").strip()[:500]
        return (ScannerRunRecord("bandit", version, CheckOutcome.FAILED, detail), ())

    findings: list[Finding] = []
    for item in payload.get("results", []):
        test_id = item.get("test_id", "")
        severity = Severity[item.get("issue_severity", "LOW")]
        confidence = Confidence[item.get("issue_confidence", "LOW")]
        file_path = _relpath(project_dir, item.get("filename", ""))
        line_number = item.get("line_number")
        finding_id = stable_finding_id("BANDIT", test_id, file_path, str(line_number))

        is_secret_value = test_id in SECRET_VALUE_BANDIT_TEST_IDS or (item.get("issue_cwe") or {}).get("id") == 798
        if is_secret_value:
            category = "Security: Secrets"
            summary = "A hardcoded credential-like value was found in source code."
            evidence = (
                f"bandit {test_id} ({item.get('test_name', '')}) at {file_path}:{line_number} "
                "-- the value itself is not shown."
            )
            status = FindingStatus.POSSIBLE_FINDING
            confidence = Confidence.MEDIUM if confidence == Confidence.HIGH else confidence
        else:
            category = "Security"
            summary = (item.get("issue_text") or "A potential security issue was found.").strip()
            evidence = (
                f"{test_id} ({item.get('test_name', '')}) at {file_path}:{line_number}: "
                + (item.get("code", "").strip() or "(no code snippet)")
            )
            if severity == Severity.HIGH and confidence == Confidence.HIGH:
                status = FindingStatus.CONFIRMED_FAILURE
            elif confidence == Confidence.HIGH:
                status = FindingStatus.STRONG_FINDING
            elif confidence == Confidence.MEDIUM:
                status = FindingStatus.POSSIBLE_FINDING
            else:
                status = FindingStatus.INFORMATIONAL

        findings.append(
            Finding(
                finding_id=finding_id,
                category=category,
                severity=severity,
                confidence=confidence,
                status=status,
                summary=summary,
                what_could_happen=_bandit_impact(item),
                file_path=file_path,
                line_number=line_number,
                evidence=evidence,
                suggested_repair=_bandit_repair(test_id),
                verification_steps=(
                    "Apply the suggested repair.",
                    "Re-run the security scan and confirm this finding no longer appears.",
                ),
                scanner_name="bandit",
                scanner_version=version,
            )
        )
    return (ScannerRunRecord("bandit", version, CheckOutcome.RAN), tuple(findings))


def _bandit_impact(item: dict) -> str:
    cwe = item.get("issue_cwe") or {}
    if cwe.get("link"):
        return f"See {cwe['link']} for the general category of risk this pattern falls into."
    return "This pattern is commonly associated with security vulnerabilities in Python code."


_BANDIT_REPAIRS = {
    "B608": "Use a parameterized query instead of building SQL by string concatenation.",
    "B602": "Avoid shell=True; pass the command as a list of arguments instead.",
    "B609": "Avoid shell=True; pass the command as a list of arguments instead.",
    "B105": "Move the value to an environment variable or secret manager, and rotate it if it was ever real.",
    "B106": "Move the value to an environment variable or secret manager, and rotate it if it was ever real.",
    "B107": "Move the value to an environment variable or secret manager, and rotate it if it was ever real.",
    "B301": "Avoid unpickling untrusted data; use a safer serialization format such as JSON.",
    "B404": "Review whether the subprocess module is used safely elsewhere in this function (e.g. no shell=True, no untrusted input).",
}


def _bandit_repair(test_id: str) -> str:
    return _BANDIT_REPAIRS.get(test_id, "Review this line against the linked CWE guidance and adjust the code accordingly.")


# ------------------------------------------------------------ pip-audit ----

_REQUIREMENTS_FILENAMES = ("requirements.txt", "requirements-prod.txt", "requirements-main.txt")

# Matches an exact `name = "version"` pin in a TOML key/value table -- the
# shape shared by Poetry's `[tool.poetry.dependencies]` and Pipenv's
# `Pipfile` `[packages]` table. A caret, tilde, wildcard, or comparison
# operator marks a *range*, not a pin, so those are deliberately left
# unmatched rather than guessed at (pip-audit needs a concrete version to
# audit, and V1 never invents one).
_TOML_EXACT_PIN_RE = re.compile(r'^([A-Za-z0-9][A-Za-z0-9._-]*)\s*=\s*"(?:==)?([0-9][A-Za-z0-9.+-]*)"\s*$')

# Matches an exact `"name==version"` PEP 508 pin inside a PEP 621
# `dependencies = [...]` array. Anything without a literal `==` (a range,
# an extras marker, a URL requirement) is left unmatched for the same reason
# as above.
_PEP621_PIN_RE = re.compile(r'"([A-Za-z0-9][A-Za-z0-9._-]*)==([0-9][A-Za-z0-9.+-]*)"')


def _extract_toml_table_pins(text: str, table_suffix: str) -> list[tuple[str, str]]:
    """Exact pins from the TOML table whose header ends with `table_suffix`
    (e.g. "poetry.dependencies" for `[tool.poetry.dependencies]`, or
    "packages" for a Pipfile's `[packages]`). The `python` key is not a
    dependency and is always skipped."""
    pins: list[tuple[str, str]] = []
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            header = stripped.strip("[]")
            in_table = header == table_suffix or header.endswith(f".{table_suffix}")
            continue
        if not in_table:
            continue
        match = _TOML_EXACT_PIN_RE.match(stripped)
        if match and match.group(1).lower() != "python":
            pins.append((match.group(1), match.group(2)))
    return pins


def _extract_toml_table_text(text: str, table_name: str) -> str:
    """The raw lines belonging to the top-level TOML table with this exact
    name (e.g. "project"), stopping at the next `[...]` header -- including a
    `[project.optional-dependencies]` sub-table, which is not the same table."""
    lines: list[str] = []
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and not stripped.startswith("[["):
            in_table = stripped.strip("[]") == table_name
            continue
        if in_table:
            lines.append(line)
    return "\n".join(lines)


def _extract_pep621_pins(text: str) -> list[tuple[str, str]]:
    """Exact pins from a PEP 621 `[project] dependencies = [...]` array."""
    project_text = _extract_toml_table_text(text, "project")
    match = re.search(r"dependencies\s*=\s*\[(.*?)\]", project_text, re.DOTALL)
    if not match:
        return []
    return _PEP621_PIN_RE.findall(match.group(1))


def _extract_pyproject_pins(text: str) -> list[tuple[str, str]]:
    """Exact pins declared either the Poetry way (`[tool.poetry.dependencies]`)
    or the PEP 621 way (`[project] dependencies = [...]`) -- a pyproject.toml
    can use either, so both are checked."""
    return _extract_toml_table_pins(text, "poetry.dependencies") + _extract_pep621_pins(text)


def _extract_pipfile_lock_pins(payload: dict) -> list[tuple[str, str]]:
    """Exact pins from a Pipfile.lock's `default` section. `develop` (dev-only
    dependencies) is intentionally not audited here, matching V1's existing
    scope of auditing what the application itself depends on to run."""
    pins: list[tuple[str, str]] = []
    for name, info in (payload.get("default") or {}).items():
        version = (info or {}).get("version", "")
        if version.startswith("=="):
            pins.append((name, version[2:]))
    return pins


def _find_pinned_dependency_manifest(project_dir: Path) -> tuple[Path, str, list[tuple[str, str]]] | None:
    """The first supported dependency manifest found beyond requirements.txt,
    together with its raw text (for evidence/line-number lookups) and its
    exactly-pinned (name, version) pairs. Checked in the order a real project
    is most likely to declare one: pyproject.toml (Poetry or PEP 621), then
    Pipfile.lock (the resolved, authoritative Pipenv source), then a bare
    Pipfile if no lock has been generated yet."""
    pyproject_path = project_dir / "pyproject.toml"
    if pyproject_path.is_file():
        text = pyproject_path.read_text(encoding="utf-8", errors="replace")
        return (pyproject_path, text, _extract_pyproject_pins(text))

    pipfile_lock_path = project_dir / "Pipfile.lock"
    if pipfile_lock_path.is_file():
        text = pipfile_lock_path.read_text(encoding="utf-8", errors="replace")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return (pipfile_lock_path, text, [])
        return (pipfile_lock_path, text, _extract_pipfile_lock_pins(payload))

    pipfile_path = project_dir / "Pipfile"
    if pipfile_path.is_file():
        text = pipfile_path.read_text(encoding="utf-8", errors="replace")
        return (pipfile_path, text, _extract_toml_table_pins(text, "packages"))

    return None


def run_pip_audit(project_dir: Path) -> tuple[ScannerRunRecord, tuple[Finding, ...]]:
    version_probe = run_tool(module_invocation("pip_audit", "--version"), timeout=15)
    if version_probe.launch_failed:
        return (
            ScannerRunRecord("pip-audit", "unavailable", CheckOutcome.UNAVAILABLE, "pip-audit is not installed in this environment."),
            (),
        )
    version = (version_probe.stdout or version_probe.stderr).strip() or "unknown"

    requirements_file = next(
        (project_dir / name for name in _REQUIREMENTS_FILENAMES if (project_dir / name).is_file()),
        None,
    )
    if requirements_file is not None:
        result = run_tool(
            module_invocation("pip_audit", "-f", "json", "-r", str(requirements_file), "--progress-spinner", "off"),
            timeout=90,
        )
        return _pip_audit_outcome(result, version, project_dir, requirements_file, requirements_file.read_text(encoding="utf-8", errors="replace"))

    manifest = _find_pinned_dependency_manifest(project_dir)
    if manifest is None:
        return (
            ScannerRunRecord(
                "pip-audit", version, CheckOutcome.UNAVAILABLE,
                "No requirements.txt, pyproject.toml (Poetry or PEP 621), or Pipfile/Pipfile.lock found.",
            ),
            (),
        )
    manifest_path, manifest_text, pins = manifest
    if not pins:
        return (
            ScannerRunRecord(
                "pip-audit", version, CheckOutcome.UNAVAILABLE,
                f"{_relpath(project_dir, str(manifest_path))} was found but declares no exactly-pinned "
                "dependencies; V1 audits pinned versions only and does not resolve version ranges.",
            ),
            (),
        )

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as tmp:
        for name, pinned_version in pins:
            tmp.write(f"{name}=={pinned_version}\n")
        tmp_path = Path(tmp.name)
    try:
        result = run_tool(
            module_invocation("pip_audit", "-f", "json", "-r", str(tmp_path), "--progress-spinner", "off"),
            timeout=90,
        )
    finally:
        tmp_path.unlink(missing_ok=True)
    return _pip_audit_outcome(result, version, project_dir, manifest_path, manifest_text)


def _pip_audit_outcome(
    result: ToolResult, version: str, project_dir: Path, source_path: Path, source_text: str
) -> tuple[ScannerRunRecord, tuple[Finding, ...]]:
    if result.timed_out:
        return (ScannerRunRecord("pip-audit", version, CheckOutcome.FAILED, "pip-audit timed out (network may be unavailable)."), ())
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        detail = (result.stderr or "could not parse pip-audit output; the vulnerability database may be unreachable").strip()[:500]
        return (ScannerRunRecord("pip-audit", version, CheckOutcome.FAILED, detail), ())

    source_relpath = _relpath(project_dir, str(source_path))

    findings: list[Finding] = []
    seen_vulns: set[tuple[str, str, str]] = set()
    for dependency in payload.get("dependencies", []):
        name = dependency.get("name", "")
        version_pinned = dependency.get("version", "")
        line_number = _find_line_number(source_text, name)
        for vuln in dependency.get("vulns", []):
            vuln_id = vuln.get("id", "unknown")
            # pip-audit's own advisory data occasionally lists the same
            # advisory twice (once per data source) with slightly different
            # text -- collapse those into a single finding.
            dedup_key = (name, version_pinned, vuln_id)
            if dedup_key in seen_vulns:
                continue
            seen_vulns.add(dedup_key)
            fix_versions = vuln.get("fix_versions") or []
            finding_id = stable_finding_id("PIPAUDIT", name, version_pinned, vuln_id)
            aliases = ", ".join(vuln.get("aliases") or []) or vuln_id
            findings.append(
                Finding(
                    finding_id=finding_id,
                    category="Dependency vulnerability",
                    severity=Severity.HIGH,
                    confidence=Confidence.HIGH,
                    status=FindingStatus.CONFIRMED_FAILURE,
                    summary=f"{name} {version_pinned} has a publicly known security vulnerability ({aliases}).",
                    what_could_happen="An attacker could exploit the known flaw in this package version if it is reachable in this application.",
                    file_path=source_relpath,
                    line_number=line_number,
                    evidence=f"{name}=={version_pinned} (advisory {vuln_id}, aliases: {aliases})",
                    suggested_repair=(
                        f"Upgrade {name} to {fix_versions[0]} or later and re-test."
                        if fix_versions
                        else f"No fixed version is published yet for {vuln_id}; consider an alternative package or mitigating controls."
                    ),
                    verification_steps=(
                        f"Update the pin in {source_relpath} and reinstall dependencies in a fresh environment.",
                        "Re-run the dependency scan and confirm the advisory is gone.",
                    ),
                    scanner_name="pip-audit",
                    scanner_version=version,
                )
            )
    return (ScannerRunRecord("pip-audit", version, CheckOutcome.RAN), tuple(findings))


def _find_line_number(requirements_text: str, package_name: str) -> int | None:
    # The optional quotes make this match a plain requirements.txt line
    # (`name==1.0`), a TOML key (`name = "1.0"`), and a JSON key
    # (`"name": {...}`) with the same pattern.
    pattern = re.compile(rf'^\s*"?{re.escape(package_name)}"?\s*[:=<>!~]', re.IGNORECASE)
    for i, line in enumerate(requirements_text.splitlines(), start=1):
        if pattern.match(line):
            return i
    return None


# --------------------------------------------------------- detect-secrets --

# Matches a path with a known tool-cache/dependency directory as one of its
# components (reusing the same directory list every other scanner already
# treats as not-the-project's-own-code), so detect-secrets never has to walk
# into .venv, .pytest_cache, node_modules, etc. --all-files intentionally
# ignores .gitignore (to catch secrets in files that would otherwise never be
# reviewed), which is exactly why these tool-owned directories need their own
# explicit exclusion instead of relying on git-ignore behavior.
_SECRETS_EXCLUDE_DIRS_PATTERN = (
    r"(^|[\\/])(" + "|".join(re.escape(name) for name in sorted(IGNORED_DIR_NAMES)) + r")([\\/]|$)"
)

# A run of base64 alphabet characters long enough to plausibly be a payload
# rather than an incidental short token.
_BASE64_TOKEN_RE = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")


def _decodes_to_json(token: str) -> bool:
    """True if `token` is base64 for bytes that themselves are valid JSON.

    Used only to recognize the shape of a non-secret base64-encoded payload
    (e.g. a logged orchestration/event message) -- real secrets are random
    bytes or opaque tokens, not JSON structures, so this does not risk
    hiding an actual credential.
    """
    core = token.rstrip("=")
    if len(core) < 16:
        return False
    padded = core + "=" * (-len(core) % 4)
    try:
        decoded = base64.b64decode(padded, validate=True)
    except (ValueError, binascii.Error):
        return False
    try:
        text = decoded.decode("utf-8").strip()
    except UnicodeDecodeError:
        return False
    if not text:
        return False
    try:
        json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return False
    return True


def _flags_non_secret_base64_payload(project_dir: Path, file_path: str, line_number: int | None) -> bool:
    if line_number is None:
        return False
    try:
        text = (project_dir / file_path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    lines = text.splitlines()
    if not (1 <= line_number <= len(lines)):
        return False
    line = lines[line_number - 1]
    return any(_decodes_to_json(token) for token in _BASE64_TOKEN_RE.findall(line))


def run_detect_secrets(project_dir: Path) -> tuple[ScannerRunRecord, tuple[Finding, ...]]:
    version_probe = run_tool(module_invocation("detect_secrets", "--version"), timeout=15)
    if version_probe.launch_failed:
        return (
            ScannerRunRecord("detect-secrets", "unavailable", CheckOutcome.UNAVAILABLE, "detect-secrets is not installed in this environment."),
            (),
        )
    version = version_probe.stdout.strip() or "unknown"

    # detect-secrets must be given a relative path and run with cwd set to
    # the project directory -- an absolute Windows path silently yields zero
    # results. --all-files scans the working tree regardless of git tracking.
    result = run_tool(
        module_invocation(
            "detect_secrets", "scan", "--all-files",
            "--exclude-files", _SECRETS_EXCLUDE_DIRS_PATTERN,
            ".",
        ),
        cwd=project_dir,
        timeout=90,
    )
    if result.timed_out:
        return (ScannerRunRecord("detect-secrets", version, CheckOutcome.FAILED, "detect-secrets timed out."), ())
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        detail = (result.stderr or "could not parse detect-secrets output").strip()[:500]
        return (ScannerRunRecord("detect-secrets", version, CheckOutcome.FAILED, detail), ())

    findings: list[Finding] = []
    for file_path, hits in payload.get("results", {}).items():
        for hit in hits:
            secret_type = hit.get("type", "Secret")
            line_number = hit.get("line_number")
            if secret_type == "Base64 High Entropy String" and _flags_non_secret_base64_payload(project_dir, file_path, line_number):
                continue
            hashed = hit.get("hashed_secret", "")
            finding_id = stable_finding_id("SECRETS", file_path, str(line_number), secret_type, hashed)
            findings.append(
                Finding(
                    finding_id=finding_id,
                    category="Security: Secrets",
                    severity=Severity.HIGH,
                    confidence=Confidence.MEDIUM,
                    status=FindingStatus.POSSIBLE_FINDING,
                    summary=f"A string that looks like a {secret_type} was found in a source file.",
                    what_could_happen="If this is a real, active secret, anyone with the source code could use it.",
                    file_path=file_path,
                    line_number=line_number,
                    evidence=f"Detected by pattern '{secret_type}' (value not disclosed; stored only as a one-way hash: {hashed[:12]}...).",
                    suggested_repair="Confirm with the project owner whether this is a real, live secret; if so, remove it from source, rotate it, and load it from an environment variable or secret manager instead.",
                    verification_steps=(
                        "Confirm whether the value is/was live and rotate it if so.",
                        "Re-run the secret scan and confirm no literal secret remains in source.",
                    ),
                    scanner_name="detect-secrets",
                    scanner_version=version,
                )
            )
    return (ScannerRunRecord("detect-secrets", version, CheckOutcome.RAN), tuple(findings))


# ------------------------------------------------------ repo config check --

_SENSITIVE_FILENAME_PATTERNS = ("*.env", "*.pem", "*.key", "id_rsa", "id_dsa", "*.pfx", "*.p12")
_DEBUG_TRUE_RE = re.compile(r"^\s*DEBUG\s*=\s*True\b")


def run_repo_config_checker(project_dir: Path) -> tuple[ScannerRunRecord, tuple[Finding, ...]]:
    findings: list[Finding] = []

    all_files = [p for p in project_dir.rglob("*") if p.is_file() and not is_ignored(p, project_dir)]

    # A single file can match more than one glob (e.g. a literal ".env" also
    # matches "*.env"); report each real file once, not once per pattern.
    seen_sensitive_files: set[Path] = set()
    for pattern in _SENSITIVE_FILENAME_PATTERNS:
        for match in project_dir.rglob(pattern):
            if match.is_file() and not is_ignored(match, project_dir) and match not in seen_sensitive_files:
                seen_sensitive_files.add(match)
                relpath = _relpath(project_dir, str(match))
                findings.append(
                    Finding(
                        finding_id=stable_finding_id("REPOCFG", "sensitive-file", relpath),
                        category="Repository configuration",
                        severity=Severity.HIGH,
                        confidence=Confidence.MEDIUM,
                        status=FindingStatus.POSSIBLE_FINDING,
                        summary=f"A file named '{relpath}' matches a pattern commonly used for credentials or private keys.",
                        what_could_happen="If this file contains a real secret or key, anyone with a copy of this project could use it.",
                        file_path=relpath,
                        line_number=None,
                        evidence=f"File name matched pattern '{pattern}' (file contents were not read).",
                        suggested_repair="If this file contains a real secret, remove it from the project, add it to .gitignore, and rotate any credential it contains.",
                        verification_steps=("Confirm with the project owner whether this file should exist in the project.",),
                        scanner_name="repo-config-checker",
                        scanner_version="1.0.0",
                    )
                )

    if (project_dir / ".git").is_dir() and not (project_dir / ".gitignore").is_file():
        findings.append(
            Finding(
                finding_id=stable_finding_id("REPOCFG", "missing-gitignore"),
                category="Repository configuration",
                severity=Severity.LOW,
                confidence=Confidence.HIGH,
                status=FindingStatus.INFORMATIONAL,
                summary="This project has a .git directory but no .gitignore file.",
                what_could_happen="Build artifacts, virtual environments, or local secrets could be committed by accident.",
                file_path=None,
                line_number=None,
                evidence="No .gitignore file was found at the project root.",
                suggested_repair="Add a .gitignore covering common artifacts (e.g. __pycache__/, .venv/, *.env).",
                verification_steps=("Add a .gitignore and confirm this finding no longer appears on re-scan.",),
                scanner_name="repo-config-checker",
                scanner_version="1.0.0",
            )
        )

    for file in all_files:
        if file.suffix != ".py":
            continue
        try:
            text = file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if _DEBUG_TRUE_RE.match(line):
                relpath = _relpath(project_dir, str(file))
                findings.append(
                    Finding(
                        finding_id=stable_finding_id("REPOCFG", "debug-true", relpath, str(i)),
                        category="Configuration",
                        severity=Severity.MEDIUM,
                        confidence=Confidence.LOW,
                        status=FindingStatus.POSSIBLE_FINDING,
                        summary="A DEBUG flag appears to be hardcoded to True.",
                        what_could_happen="Running with debug mode on in production can expose stack traces, source code, or internal state to users.",
                        file_path=relpath,
                        line_number=i,
                        evidence=line.strip(),
                        suggested_repair="Read DEBUG from an environment variable that defaults to False, so production deployments do not run with it enabled by accident.",
                        verification_steps=("Confirm how DEBUG is set in the real deployment environment.",),
                        scanner_name="repo-config-checker",
                        scanner_version="1.0.0",
                    )
                )

    return (ScannerRunRecord("repo-config-checker", "1.0.0", CheckOutcome.RAN), tuple(findings))


ALL_SCANNERS = (run_ruff, run_bandit, run_pip_audit, run_detect_secrets, run_repo_config_checker)
