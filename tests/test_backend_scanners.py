"""Unit tests for the individual read-only scanners against fixture projects.

`vulnerable_project` intentionally contains a SQL-injection pattern, a
shell=True call, an undefined name, an unused import, a hardcoded secret, an
old vulnerable dependency pin, and a fake private-key file -- one thing for
each scanner to legitimately find. `clean_project` should come back clean.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from inspector_app.backend import scanners
from inspector_app.models import CheckOutcome

FIXTURES = Path(__file__).parent / "fixtures"
VULNERABLE = FIXTURES / "vulnerable_project"
CLEAN = FIXTURES / "clean_project"
POETRY_PROJECT = FIXTURES / "poetry_project"
PIPENV_PROJECT = FIXTURES / "pipenv_project"


def test_ruff_finds_undefined_names_and_unused_import():
    record, findings = scanners.run_ruff(VULNERABLE)
    assert record.outcome == CheckOutcome.RAN
    codes = {f.evidence.split()[0] for f in findings}
    assert "F821" in codes  # undefined name
    assert "F401" in codes  # unused import


def test_ruff_clean_project_has_no_findings():
    record, findings = scanners.run_ruff(CLEAN)
    assert record.outcome == CheckOutcome.RAN
    assert findings == ()


def test_bandit_finds_sql_injection_and_shell_true():
    record, findings = scanners.run_bandit(VULNERABLE)
    assert record.outcome == CheckOutcome.RAN
    test_ids = {f.evidence.split()[0] for f in findings if not f.evidence.startswith("bandit")}
    assert "B608" in test_ids  # SQL injection
    assert "B602" in test_ids  # shell=True


def test_bandit_never_leaks_the_hardcoded_secret_value():
    _, findings = scanners.run_bandit(VULNERABLE)
    secret_findings = [f for f in findings if f.category == "Security: Secrets"]
    assert secret_findings, "bandit should flag the hardcoded AWS secret"
    for f in secret_findings:
        assert "wJalrXUtnFEMI" not in f.evidence
        assert "wJalrXUtnFEMI" not in f.summary


def test_pip_audit_finds_known_vulnerable_pin():
    record, findings = scanners.run_pip_audit(VULNERABLE)
    assert record.outcome == CheckOutcome.RAN
    assert any(f.category == "Dependency vulnerability" for f in findings)
    assert all(f.file_path == "requirements.txt" for f in findings)


def test_pip_audit_unavailable_without_requirements_file():
    record, findings = scanners.run_pip_audit(CLEAN)
    assert record.outcome == CheckOutcome.UNAVAILABLE
    assert findings == ()


def test_pip_audit_finds_known_vulnerable_pin_in_poetry_pyproject_toml():
    """poetry_project has no requirements.txt at all -- only a pyproject.toml
    declaring urllib3 via Poetry's [tool.poetry.dependencies] table. This is
    the exact shape that returned "Unavailable" before this fix."""
    record, findings = scanners.run_pip_audit(POETRY_PROJECT)
    assert record.outcome == CheckOutcome.RAN
    assert any(f.category == "Dependency vulnerability" for f in findings)
    assert all(f.file_path == "pyproject.toml" for f in findings)


def test_pip_audit_finds_known_vulnerable_pin_in_pipfile_lock():
    """pipenv_project has no requirements.txt or pyproject.toml -- only a
    Pipfile/Pipfile.lock pair declaring urllib3 via Pipenv."""
    record, findings = scanners.run_pip_audit(PIPENV_PROJECT)
    assert record.outcome == CheckOutcome.RAN
    assert any(f.category == "Dependency vulnerability" for f in findings)
    assert all(f.file_path == "Pipfile.lock" for f in findings)


def test_pip_audit_unavailable_when_pyproject_has_no_pinned_dependencies(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "no-pins"\nversion = "0.1.0"\ndependencies = ["requests>=2.0"]\n',
        encoding="utf-8",
    )
    record, findings = scanners.run_pip_audit(tmp_path)
    assert record.outcome == CheckOutcome.UNAVAILABLE
    assert findings == ()


def test_extract_pep621_pins_reads_exact_pins_only():
    text = (
        "[project]\n"
        "dependencies = [\n"
        '    "requests==2.25.0",\n'
        '    "urllib3>=1.0",\n'
        '    "flask~=2.0",\n'
        "]\n"
    )
    assert scanners._extract_pep621_pins(text) == [("requests", "2.25.0")]


def test_extract_pep621_pins_survives_a_pep508_extras_marker():
    """A dependency entry with an extras marker (e.g. requests[security])
    embeds its own `[`/`]` pair inside the quoted string. A naive
    non-greedy bracket match stops at that inner `]` and would silently
    lose every pin in the array, not just the one with extras."""
    text = (
        "[project]\n"
        "dependencies = [\n"
        '    "requests[security]==2.25.0",\n'
        '    "flask==2.0.1",\n'
        "]\n"
    )
    assert scanners._extract_pep621_pins(text) == [("flask", "2.0.1")]


def test_extract_toml_table_pins_skips_ranges_and_python_key():
    text = (
        "[packages]\n"
        'python = "3.10"\n'
        'urllib3 = "==1.24.1"\n'
        'requests = "*"\n'
        'flask = {version = "^2.0"}\n'
    )
    assert scanners._extract_toml_table_pins(text, "packages") == [("urllib3", "1.24.1")]


def test_extract_pipfile_lock_pins_skips_unpinned_entries():
    payload = {
        "default": {
            "urllib3": {"version": "==1.24.1"},
            "requests": {"version": "*"},
        }
    }
    assert scanners._extract_pipfile_lock_pins(payload) == [("urllib3", "1.24.1")]


def test_detect_secrets_finds_the_fake_private_key():
    record, findings = scanners.run_detect_secrets(VULNERABLE)
    assert record.outcome == CheckOutcome.RAN
    assert any("Private Key" in f.summary for f in findings)
    for f in findings:
        assert "FAKEFAKEFAKE" not in f.evidence


def test_detect_secrets_excludes_pytest_cache_directory(tmp_path):
    """Found live: every real-world scan flagged `.pytest_cache/CACHEDIR.TAG`'s
    hex signature as a possible secret -- reproduced here with the exact real
    file content, not a synthetic stand-in."""
    cache_dir = tmp_path / ".pytest_cache"
    cache_dir.mkdir()
    (cache_dir / "CACHEDIR.TAG").write_text(
        "Signature: 8a477f597d28d172789f06886806bc55\n"
        "# This file is a cache directory tag created by pytest.\n",
        encoding="utf-8",
    )
    _, findings = scanners.run_detect_secrets(tmp_path)
    assert findings == ()


def test_detect_secrets_recognizes_json_decodable_base64_payload(tmp_path):
    """Found live in a real stress-test harness's own logs: a base64-encoded
    JSON event payload has enough entropy to trip the Base64 High Entropy
    String plugin, but it is not a secret -- it cleanly JSON-decodes."""
    import base64
    import json as json_module

    payload = json_module.dumps({"event": "heartbeat", "seq": 42, "ok": True, "trace_id": "abc123def456"})
    encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    (tmp_path / "orchestration_log.py").write_text(f'PAYLOAD = "{encoded}"\n', encoding="utf-8")
    _, findings = scanners.run_detect_secrets(tmp_path)
    assert findings == ()


def test_detect_secrets_still_finds_the_hardcoded_aws_key_alongside_base64_plugin():
    """The false-positive fix must not weaken real detection: the vulnerable
    fixture's AWS key also trips the Base64 High Entropy String plugin (real
    secrets are high-entropy too), and it must still be reported."""
    _, findings = scanners.run_detect_secrets(VULNERABLE)
    assert any("AWS Access Key" in f.summary for f in findings)


def test_detect_secrets_deduplicates_same_secret():
    """When detect-secrets reports multiple hits for the same secret (same file, line, hashed_secret),
    only one Finding should be returned."""
    record, findings = scanners.run_detect_secrets(VULNERABLE)
    assert record.outcome == CheckOutcome.RAN
    # Filter findings for the hardcoded AWS key in bad.py line 13
    bad13 = [f for f in findings if f.file_path == "bad.py" and f.line_number == 13]
    # There should be exactly one finding for this secret
    assert len(bad13) == 1, f"Expected 1 finding for bad.py:13, got {len(bad13)}: {[f.summary for f in bad13]}"


def test_repo_config_checker_flags_sensitive_filename():
    record, findings = scanners.run_repo_config_checker(VULNERABLE)
    assert record.outcome == CheckOutcome.RAN
    assert any(f.file_path == "id_rsa_fake.pem" for f in findings)


def test_repo_config_checker_clean_project_has_no_findings():
    _, findings = scanners.run_repo_config_checker(CLEAN)
    assert findings == ()


def test_repo_config_checker_env_file_reported_once_not_twice(tmp_path):
    """A literal `.env` file matches both '*.env' and '.env' in
    _SENSITIVE_FILENAME_PATTERNS -- found live on a real project (Hunter's
    own Second Brain vault) reporting each real .env file twice."""
    (tmp_path / ".env").write_text("SECRET=xyz\n", encoding="utf-8")
    _, findings = scanners.run_repo_config_checker(tmp_path)
    env_findings = [f for f in findings if f.file_path == ".env"]
    assert len(env_findings) == 1, f"expected exactly 1 finding for a literal .env file, got {len(env_findings)}"


def test_all_scanners_produce_unique_finding_ids():
    seen: set[str] = set()
    for fn in scanners.ALL_SCANNERS:
        _, findings = fn(VULNERABLE)
        for f in findings:
            assert f.finding_id not in seen, f"duplicate finding_id: {f.finding_id}"
            seen.add(f.finding_id)


def test_finding_ids_are_stable_across_repeat_scans():
    _, first = scanners.run_bandit(VULNERABLE)
    _, second = scanners.run_bandit(VULNERABLE)
    assert {f.finding_id for f in first} == {f.finding_id for f in second}


def test_unavailable_tool_is_never_reported_as_ran(monkeypatch):
    def fake_run_tool(args, **kwargs):
        from inspector_app.backend.subprocess_utils import ToolResult
        return ToolResult(exit_code=None, stdout="", stderr="", timed_out=False, launch_failed=True, launch_error="not found")

    monkeypatch.setattr("inspector_app.backend.scanners.run_tool", fake_run_tool)
    for fn in (scanners.run_ruff, scanners.run_bandit, scanners.run_pip_audit, scanners.run_detect_secrets):
        record, findings = fn(VULNERABLE)
        assert record.outcome == CheckOutcome.UNAVAILABLE
        assert findings == ()


def test_tool_crash_is_reported_as_failed_not_silently_dropped(monkeypatch):
    """A tool that launches but produces garbage output must show up as
    FAILED, never as a silent empty RAN result (that would be a false
    success)."""
    from inspector_app.backend.subprocess_utils import ToolResult

    real_run_tool = scanners.run_tool

    def flaky_run_tool(args, **kwargs):
        if "--version" in args:
            return real_run_tool(args, **kwargs)
        return ToolResult(exit_code=1, stdout="not json at all {{{", stderr="internal crash", timed_out=False, launch_failed=False)

    monkeypatch.setattr("inspector_app.backend.scanners.run_tool", flaky_run_tool)
    record, findings = scanners.run_ruff(VULNERABLE)
    assert record.outcome == CheckOutcome.FAILED
    assert findings == ()
