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
from .fs_util import is_ignored
from .subprocess_utils import module_invocation, run_tool


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

        is_secret_value = test_id in SECRET_VALUE_BANDIT_TEST_IDS
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
    if requirements_file is None:
        return (
            ScannerRunRecord(
                "pip-audit", version, CheckOutcome.UNAVAILABLE,
                "No requirements.txt found. V1 audits pinned dependencies from a requirements.txt "
                "file only; pyproject.toml/poetry/pipenv lockfiles are not yet supported.",
            ),
            (),
        )

    result = run_tool(
        module_invocation("pip_audit", "-f", "json", "-r", str(requirements_file), "--progress-spinner", "off"),
        timeout=90,
    )
    if result.timed_out:
        return (ScannerRunRecord("pip-audit", version, CheckOutcome.FAILED, "pip-audit timed out (network may be unavailable)."), ())
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        detail = (result.stderr or "could not parse pip-audit output; the vulnerability database may be unreachable").strip()[:500]
        return (ScannerRunRecord("pip-audit", version, CheckOutcome.FAILED, detail), ())

    req_text = requirements_file.read_text(encoding="utf-8", errors="replace")
    req_relpath = _relpath(project_dir, str(requirements_file))

    findings: list[Finding] = []
    seen_vulns: set[tuple[str, str, str]] = set()
    for dependency in payload.get("dependencies", []):
        name = dependency.get("name", "")
        version_pinned = dependency.get("version", "")
        line_number = _find_line_number(req_text, name)
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
                    file_path=req_relpath,
                    line_number=line_number,
                    evidence=f"{name}=={version_pinned} (advisory {vuln_id}, aliases: {aliases})",
                    suggested_repair=(
                        f"Upgrade {name} to {fix_versions[0]} or later and re-test."
                        if fix_versions
                        else f"No fixed version is published yet for {vuln_id}; consider an alternative package or mitigating controls."
                    ),
                    verification_steps=(
                        "Update the pin in requirements.txt and reinstall dependencies in a fresh environment.",
                        "Re-run the dependency scan and confirm the advisory is gone.",
                    ),
                    scanner_name="pip-audit",
                    scanner_version=version,
                )
            )
    return (ScannerRunRecord("pip-audit", version, CheckOutcome.RAN), tuple(findings))


def _find_line_number(requirements_text: str, package_name: str) -> int | None:
    pattern = re.compile(rf"^\s*{re.escape(package_name)}\s*[=<>!~]", re.IGNORECASE)
    for i, line in enumerate(requirements_text.splitlines(), start=1):
        if pattern.match(line):
            return i
    return None


# --------------------------------------------------------- detect-secrets --

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
        module_invocation("detect_secrets", "scan", "--all-files", "."),
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

_SENSITIVE_FILENAME_PATTERNS = ("*.env", ".env", "*.pem", "*.key", "id_rsa", "id_dsa", "*.pfx", "*.p12")
_DEBUG_TRUE_RE = re.compile(r"^\s*DEBUG\s*=\s*True\b")


def run_repo_config_checker(project_dir: Path) -> tuple[ScannerRunRecord, tuple[Finding, ...]]:
    findings: list[Finding] = []

    all_files = [p for p in project_dir.rglob("*") if p.is_file() and not is_ignored(p, project_dir)]

    for pattern in _SENSITIVE_FILENAME_PATTERNS:
        for match in project_dir.rglob(pattern):
            if match.is_file() and not is_ignored(match, project_dir):
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
