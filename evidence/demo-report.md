# Inspection summary — https://github.com/psf/requests

- **[Low] Reliability** — A broad except clause silently swallows every error in a file-loading routine.
- **[High] Security: Secrets** — A string that looks like an API key was found in a source file.
- **[Critical] Security: Injection** — A database query is built by pasting user input directly into SQL text.
- **[Medium] Code quality** — A function is over 150 lines long and handles several unrelated jobs.
- **[High] Dependency vulnerability** — A required package has a publicly known security vulnerability in the version pinned here.

This scan cannot guarantee that every possible bug or vulnerability has been found.

---

# Technical repair packet — https://github.com/psf/requests

## FIND-005: Reliability (Informational)
- Severity: Low  |  Confidence: High
- Location: app/io/loader.py:55
- Evidence: `except Exception:
    pass`
- Suggested repair: Catch the specific exception types you expect, and log or re-raise anything unexpected.
- Verification steps:
  1. Re-run the quality scan and confirm the bare-except warning is gone.
- Scanner: ruff 0.6.9

## FIND-004: Security: Secrets (Possible finding)
- Severity: High  |  Confidence: Medium
- Location: app/config/defaults.py:9
- Evidence: `DEFAULT_API_KEY = "sk-********************"  (value redacted)`
- Suggested repair: Move the value to an environment variable or secret manager, and rotate the key if it was ever real.
- Verification steps:
  1. Confirm with the project owner whether the key is/was live and rotate it if so.
  1. Re-run the secret scan and confirm no literal key remains in source.
- Scanner: detect-secrets 1.5.0

## FIND-001: Security: Injection (Confirmed failure)
- Severity: Critical  |  Confidence: High
- Location: app/db/queries.py:42
- Evidence: `cursor.execute("SELECT * FROM users WHERE name = '" + user_name + "'")`
- Suggested repair: Use a parameterized query, e.g. cursor.execute("SELECT * FROM users WHERE name = ?", (user_name,)).
- Verification steps:
  1. Re-run the security scan and confirm FIND-001 no longer appears.
  1. Add a test that passes a name like "a' OR '1'='1" and assert it is treated as a literal value.
- Scanner: bandit 1.7.9

## FIND-003: Code quality (Strong finding)
- Severity: Medium  |  Confidence: Medium
- Location: app/services/report_builder.py:18
- Evidence: `def build_report(...): ... (162 lines, cyclomatic complexity 24)`
- Suggested repair: Split it into smaller functions, one job each, and add focused tests for each.
- Verification steps:
  1. Re-run the quality scan and confirm the complexity warning is resolved.
- Scanner: ruff 0.6.9

## FIND-002: Dependency vulnerability (Confirmed failure)
- Severity: High  |  Confidence: High
- Location: requirements.txt:7
- Evidence: `requests==2.25.0 (advisory: GHSA-example, fixed in 2.31.0+)`
- Suggested repair: Upgrade the pin to requests>=2.31.0 and re-test.
- Verification steps:
  1. Update the pin and reinstall dependencies.
  1. Re-run the dependency scan and confirm the advisory is gone.
- Scanner: pip-audit 2.7.3
