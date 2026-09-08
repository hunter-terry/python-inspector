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

1. ~~Reduce the secrets scanner's false-positive rate~~ — **done 2026-09-08**,
   see [Update](#update-2026-09-08--secrets-false-positive-fix) below.
2. ~~Add `pyproject.toml` / Poetry / Pipenv lockfile support to `pip-audit`
   coverage~~ — **done 2026-09-08**, see
   [Update](#update-2026-09-08--pip-audit-poetrypipenv-coverage) below.
3. Deduplicate same-line secret findings: a single hardcoded secret routinely
   trips more than one `detect-secrets` plugin at once (e.g. the vulnerable
   fixture's AWS key is reported separately as `AWS Access Key`,
   `Base64 High Entropy String`, and `Secret Keyword` — confirmed live during
   the 2026-09-08 false-positive fix above). Collapsing same
   file+line+hashed-secret hits into one finding that lists which detectors
   agreed would cut noise further and could raise confidence when multiple
   detectors agree on the same spot. Explicitly flagged by Hunter as a good
   idea for later, not for now — raised mid-mission during the fix above, not
   yet scoped or authorized as its own mission.
4. Nothing found in this pass is urgent or blocking. This is a backlog for
   whenever Python Inspector work is next prioritized, not a call to act now.

## Update 2026-09-08 — secrets false-positive fix

Candidate next step 1 above is done, under a Claude Code Work Inbox
maintenance mission (`Workstream: Maintenance`), done directly rather than
dispatched to the fleet given the small, precision-sensitive scope. Changes
confined to `src/inspector_app/backend/scanners.py` (`run_detect_secrets`)
and `tests/test_backend_scanners.py`, no other file touched:

- `detect-secrets` is now invoked with `--exclude-files` built from the same
  `IGNORED_DIR_NAMES` list every other scanner already treats as
  not-the-project's-own-code (`.pytest_cache`, `.venv`, `.git`,
  `node_modules`, etc.) — it previously scanned into those directories
  because `--all-files` deliberately ignores `.gitignore`.
- A `Base64 High Entropy String` hit is now checked against the actual
  source line it was found on: if a base64 token on that line decodes to
  valid UTF-8 text that itself parses as JSON, it is recognized as a
  non-secret payload (e.g. a logged orchestration/event message) and not
  reported. Real secrets are random bytes or opaque tokens, not JSON
  structures, so this does not risk hiding a genuine credential — verified
  directly: the vulnerable fixture's hardcoded AWS key also trips the
  Base64 High Entropy plugin and is still reported after this change.

**Verification against a live re-scan of `_V2Relay_Prototype`** (the
richest source of the original 27 false positives): secrets findings
dropped from 25 to 15 — all 4 `.pytest_cache` hits and 6 of 7
`Base64 High Entropy String` hits (JSON-decodable stress-harness payloads)
are gone. The 1 remaining Base64 hit, the `AWS Access Key` hit, and the
`Secret Keyword` hit are all inside `tests/test_redact.py` — the project's
own deliberate fixture for its redaction function, correctly still caught.
The 12 remaining `Hex High Entropy String` hits are in
`stress_test/.runtime/lanes/local/*.json` — that project's own generated
runtime state, not a generic tool-cache directory, so out of scope for a
general-purpose fix in Python-Inspector (left as-is, correctly).

Full suite: 98 passed, 1 skipped (same pre-existing Docker-daemon skip),
including 3 new regression tests
(`test_detect_secrets_excludes_pytest_cache_directory`,
`test_detect_secrets_recognizes_json_decodable_base64_payload`,
`test_detect_secrets_still_finds_the_hardcoded_aws_key_alongside_base64_plugin`).
Commands and full evidence are on the linked Work Inbox result row.

## Update 2026-09-08 — pip-audit Poetry/Pipenv coverage

Candidate next step 2 above is done, under its own Claude Code Work Inbox
maintenance mission (`Workstream: Maintenance`), done directly rather than
dispatched to the fleet given the small, precision-sensitive parsing involved.
Changes confined to `src/inspector_app/backend/scanners.py` (`run_pip_audit`
and its helpers), `tests/test_backend_scanners.py`, two new fixture projects
under `tests/fixtures/` (`poetry_project`, `pipenv_project`), and this file —
no other file touched.

`run_pip_audit` now falls back, when no `requirements.txt`-family file
exists, to reading exactly-pinned dependencies from whichever of these is
present, in order: `pyproject.toml` (Poetry's `[tool.poetry.dependencies]`
table, or PEP 621's `[project] dependencies = [...]` array), `Pipfile.lock`
(Pipenv's resolved lock, `default` section), or a bare `Pipfile`
(`[packages]` table) if no lock has been generated yet. The pinned
`name==version` pairs found are written to a synthetic requirements-format
temp file and audited through the exact same `pip-audit -r` invocation
already used for `requirements.txt` — no new dependency-resolution mechanism,
no new third-party dependency (only the standard library's `re` and `json`,
already imported). A version range (`^`, `~`, `*`, `>=`, an inline table)
is deliberately left unaudited rather than guessed at, matching V1's existing
pinned-only scope; a manifest found with zero exact pins reports
`Unavailable` with an explicit reason rather than a silently-empty `RAN`.

**Verification against a live re-scan of `_V2Relay_Prototype`**: still
reports `Unavailable`, correctly — direct inspection during this mission
found the real project has no `requirements.txt`, `pyproject.toml`, or
`Pipfile`/`Pipfile.lock` at all, of any kind. The original candidate-next-step
wording assumed it was a Poetry/Pipenv project; it is neither. This fix closes
the general format gap for any real Poetry- or Pipenv-declared project, but
cannot manufacture dependency coverage for a project that declares no
dependencies through any file `pip-audit` (or this app) can read. Verified
instead against two new fixtures built to match the gap's shape
(`tests/fixtures/poetry_project/pyproject.toml` and
`tests/fixtures/pipenv_project/Pipfile.lock`, each pinning the same known-CVE
`urllib3==1.24.1` already used by `vulnerable_project`) — both now return
real `Dependency vulnerability` findings that were previously `Unavailable`.

Full suite: 104 passed, 1 skipped (same pre-existing Docker-daemon skip),
including 6 new tests: 2 end-to-end known-answer tests against the new
fixtures, 1 covering the zero-pinned-dependencies case, and 3 unit tests for
the new pin-extraction helpers. Commands and full evidence are on the linked
Work Inbox result row.

### Independent review fix-up 2026-09-08 — PEP 508 extras marker in `dependencies` array

An independent second-look mission (separate Work Inbox result row, linked
from the one above) found that `_extract_pep621_pins`'s original array
boundary detection (`re.search(r"dependencies\s*=\s*\[(.*?)\]", ..., re.DOTALL)`)
stopped at the *first* `]` in the array text. A dependency entry using a PEP
508 extras marker — e.g. `"requests[security]==2.25.0"`, `"uvicorn[standard]==0.30.0"`
— embeds its own `[`/`]` pair inside the quoted string, so that inner `]` was
mistaken for the end of the whole array. Effect: every pin in that array was
silently dropped, not just the one with extras, degrading safely to
`Unavailable` (never a false "audited, no findings") but losing real coverage
for a very common real-world `pyproject.toml` shape.

Fixed with a small bracket-depth scanner (`_extract_bracketed_array_text`)
that tracks nesting depth and ignores brackets inside double-quoted strings,
replacing the single non-greedy regex. The extras-marked entry itself is
still not extracted as a pin (matching the existing narrow, pinned-only
regex scope — extras aren't a version pin), but sibling entries in the same
array are no longer lost. One new regression test added
(`test_extract_pep621_pins_survives_a_pep508_extras_marker`). Full suite:
105 passed, 1 skipped. Verified through the frozen `verify-repair.ps1`
contract (mission id `pep621-extras-review-20260908`, attempt 1/3, PASS).

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
