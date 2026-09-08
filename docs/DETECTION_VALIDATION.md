# Python Inspector detection-quality validation — 2026-09-08

Python Inspector V1 has been feature-complete and passing its own test suite
since 2026-09-06 (see [QA verification](QA_VERIFICATION.md)). This pass asks a
different question: when it reports a finding against a *real* project, is
that finding actually real? Answered by (1) reviewing what the scanners
actually are, and (2) running the real production scan path against three
real, unrelated local projects and checking the results by hand rather than
trusting the labels.

## Method

1. Read `src/inspector_app/backend/scanners.py` end to end. Confirmed the app
   invents no detection logic of its own: it wraps four independently
   maintained open-source tools — **ruff**, **bandit**, **pip-audit**,
   **detect-secrets** — plus one small first-party `repo-config-checker`
   (sensitive filenames, missing `.gitignore`, hardcoded `DEBUG=True`), and
   relabels each tool's real output onto the app's own
   Confirmed/Strong/Possible/Informational scale.
2. Confirmed `tests/test_backend_scanners.py` is a known-answer test: it runs
   every real scanner against `tests/fixtures/vulnerable_project` (one
   planted issue per scanner — SQL injection, `shell=True`, an undefined
   name, a hardcoded AWS key, a vulnerable pinned dependency, a fake private
   key) and against `tests/fixtures/clean_project`, asserting both that every
   planted issue is caught **and** that the clean fixture produces zero
   findings from every scanner. Ran the suite live: currently passing
   (95 passed, 1 skipped — see Commands below).
3. Called `RealBackend.scan_local_project()` and `render_report()`
   programmatically (the same production scan path the GUI uses, no GUI
   involved) against three real projects Hunter owns, chosen to exclude
   Python Inspector itself, his personal Second-Brain note vaults, and any
   third-party client-confidential work:
   - `C:\Users\hunte\Documents\spreadsheet-cleanup-qc-kit`
   - `C:\Users\hunte\Documents\_V2Relay_Prototype`
   - `C:\Users\hunte\Documents\Second Brain\2-work\client-opportunity-scanner`

## Results by project

| Project | Confirmed | Strong | Possible | Informational | Headline |
|---|---|---|---|---|---|
| spreadsheet-cleanup-qc-kit | 0 | 0 | 1 | 100 | The 1 possible finding is a false positive (`.pytest_cache\CACHEDIR.TAG`). Rest is real typing/datetime/unused-var cleanup in actual source. |
| _V2Relay_Prototype | 0 | 12 | 25 | 43 | All 25 possible findings verified false positive by hand (cache markers, base64 orchestration payloads, a deliberate test fixture for the project's own redaction function). 12 strong = bandit subprocess-hygiene notices in `relay/`, expected for a subprocess-orchestration tool. `pip-audit` did not run — no `requirements.txt` in this project. |
| client-opportunity-scanner | 1 | 14 | 3 | 26 | The 1 confirmed finding is real: `pytest==8.4.2` has a published CVE. The 3 possible + 2 of the 14 strong findings were checked against actual source and read as lower real risk than the label implies (parameterized SQL, fixed API endpoints, a test-fixture default). The other 12 strong findings are one cosmetic ruff rule in one file. |

Full findings for each project are in `evidence/` (see below) as the same
two-layer report the app itself produces — a plain-English summary and a
technical packet with exact file/line/evidence per finding.

## Verdict

**Confirmed-tier findings are fully trustworthy as reported.** They are real
tool output relayed directly, not a heuristic — proven here by a live catch:
`requirements.txt:4` in client-opportunity-scanner pins `pytest==8.4.2`,
which has a real, currently-published advisory (PYSEC-2026-1845 /
CVE-2025-71176 / GHSA-6w46-j5rx-g56g). Suggested repair: upgrade to
`pytest>=9.0.3`.

**Strong/Possible findings are always real pattern matches — bandit and ruff
never fabricated a hit across any scan in this pass or the fixture suite —
but the label alone doesn't tell you exploitability.** Every strong/possible
security finding checked by hand this pass turned out to be either genuinely
worth a look (client-opportunity-scanner's dynamic SQL construction, though
its actual *values* are parameterized) or lower real risk on inspection
(fixed-URL `urlopen` calls, a test-fixture default password). This is exactly
what the app's own confidence labeling is for — it was never designed to
mean "definitely exploitable," and treating a Strong/Possible finding as
"real pattern, worth a two-minute read" rather than "confirmed bug" matches
how the app documents itself.

**Measured weak spot: secrets detection specifically.** Tally across all
three real-world scans: **27 "possible secret" findings, 0 real.** All were
`.pytest_cache` marker files, base64-encoded non-secret orchestration
payloads in a stress-test harness's own logs, or deliberately fake
credential strings in a test file for a redaction function. This is expected
behavior for an entropy-based heuristic (it is tuned to over-flag rather than
miss a real key) — not a defect in how the app labels or handles findings —
but it is the one category worth mentally discounting until proven
otherwise, unlike Confirmed findings from the other three tools.

## Candidate next steps (not authorized or scheduled — for Hunter to prioritize)

1. Reduce the secrets scanner's false-positive rate: exclude `.pytest_cache`
   (and similar tool-cache directories) by default, and consider recognizing
   the shape of base64-encoded non-secret payloads (e.g. JSON-decodes
   cleanly) before flagging them.
2. Add `pyproject.toml` / Poetry / Pipenv lockfile support to `pip-audit`
   coverage. V1 only reads `requirements.txt`-style files; `_V2Relay_Prototype`
   got zero dependency-vulnerability coverage as a direct result, silently
   in the sense that nothing crashed, but not silently in the sense that the
   report always states plainly that no requirements.txt is being audited.
3. Nothing found in this pass is urgent or blocking. This is a backlog for
   whenever Python Inspector work is next prioritized, not a call to act now.

## Commands run

```powershell
.venv\Scripts\python -m pytest -q            # 95 passed, 1 skipped, 165.01s
.venv\Scripts\python -m pytest -q -rs        # skip reason: tests\test_backend_sandbox.py:132, Docker daemon not reachable
```

The three real-world scans were run via a throwaway script (not committed —
scratch, not part of the app) that imported `RealBackend` directly and called
`scan_local_project(target_path, ...)` then `render_report(result)`, writing
the two resulting Markdown documents per project.

## Evidence

- `evidence/qc-kit-summary.md`, `evidence/qc-kit-technical-packet.md`
- `evidence/v2relay-summary.md`, `evidence/v2relay-technical-packet.md`
- `evidence/ocs-summary.md`, `evidence/ocs-technical-packet.md`

## Limitations

- All three sampled projects are Hunter's own; none have a genuinely diverse
  dependency ecosystem (Poetry/Pipenv) or a real, live secret, so this pass
  could not observe a true-positive secrets detection or exercise
  `pip-audit`'s lockfile gap directly against a project that would otherwise
  have coverage.
- Strong/Possible security findings were checked by reading the flagged line
  and its immediate context, not the full call graph — the risk assessments
  above ("lower real risk on inspection") are a same-session human read, not
  a formal audit.
