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
   third-party client-confidential work. Identities, paths, and full findings
   for these three are kept in a private validation record rather than this
   public repo, since they document real (if low-risk) findings in
   unpublished code — only the aggregate, non-identifying results are
   reported below.

## Results

| Confirmed | Strong | Possible | Informational |
|---|---|---|---|
| 1 of 3 projects had one confirmed finding | 26 across all 3 | 29 across all 3 | 169 across all 3 |

The one confirmed finding across all three projects was a real, currently
published CVE in a pinned dependency (`pytest==8.4.2`, advisory
PYSEC-2026-1845 / CVE-2025-71176 / GHSA-6w46-j5rx-g56g) — see the
[QA verification](QA_VERIFICATION.md) demo report for the same class of
finding against a public repo (`psf/requests`).

Every Strong/Possible security finding across the three projects was checked
by hand against the actual source line. All were genuine pattern matches (no
tool fabricated a hit), and each read as either worth a follow-up look or
lower real risk on inspection once the surrounding code was read — exactly
what the app's Strong/Possible labels are designed to mean: "real pattern,
worth a two-minute read," not "confirmed bug."

**Measured weak spot: secrets detection specifically.** Tally across all
three real-world scans: **27 "possible secret" findings, 0 real.** All were
`.pytest_cache` marker files, base64-encoded non-secret orchestration
payloads in one project's own stress-test logs, or deliberately fake
credential strings in a test fixture for a redaction function. This is
expected behavior for an entropy-based heuristic (it is tuned to over-flag
rather than miss a real key) — not a defect in how the app labels or handles
findings — but it is the one category worth mentally discounting until
proven otherwise, unlike Confirmed findings from the other three tools.

## Verdict

**Confirmed-tier findings are fully trustworthy as reported.** They are real
tool output relayed directly, not a heuristic — proven here by a live catch
of a real, currently-published dependency CVE (see above).

**Strong/Possible findings are always real pattern matches — bandit and ruff
never fabricated a hit across any scan in this pass or the fixture suite —
but the label alone doesn't tell you exploitability.** Treat a Strong/Possible
finding as "real pattern, worth a two-minute read" rather than "confirmed
bug," matching how the app documents itself.

## Candidate next steps (not authorized or scheduled — for Hunter to prioritize)

1. ~~Reduce the secrets scanner's false-positive rate~~ — **done 2026-09-08**,
   see [Update](#update-2026-09-08--secrets-false-positive-fix) below.
2. ~~Add `pyproject.toml` / Poetry / Pipenv lockfile support to `pip-audit`
   coverage~~ — **done 2026-09-08**, see
   [Update](#update-2026-09-08--pip-audit-poetrypipenv-coverage) below.
3. ~~Deduplicate same-line secret findings~~ — **done 2026-09-09**, see
   [Update](#update-2026-09-09--secrets-dedup-fix-plus-1-app-bug-and-1-flaky-test-found-and-fixed)
   below.
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

**Verification against a live re-scan of one of the three private validation
projects** (the richest source of the original 27 false positives): secrets
findings dropped from 25 to 15 — all 4 `.pytest_cache` hits and 6 of 7
`Base64 High Entropy String` hits (JSON-decodable stress-harness payloads)
are gone. The 1 remaining Base64 hit, the `AWS Access Key` hit, and the
`Secret Keyword` hit are all inside that project's own deliberate fixture for
its redaction function, correctly still caught. The 12 remaining
`Hex High Entropy String` hits are in that project's own generated runtime
state (not a generic tool-cache directory), so out of scope for a
general-purpose fix in Python-Inspector (left as-is, correctly).

Full suite: 98 passed, 1 skipped (same pre-existing Docker-daemon skip),
including 3 new regression tests
(`test_detect_secrets_excludes_pytest_cache_directory`,
`test_detect_secrets_recognizes_json_decodable_base64_payload`,
`test_detect_secrets_still_finds_the_hardcoded_aws_key_alongside_base64_plugin`).

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

**Verification against a live re-scan of one of the three private validation
projects**: still reports `Unavailable`, correctly — direct inspection during
this mission found the real project has no `requirements.txt`,
`pyproject.toml`, or `Pipfile`/`Pipfile.lock` at all, of any kind. The
original candidate-next-step wording assumed it was a Poetry/Pipenv project;
it is neither. This fix closes the general format gap for any real Poetry- or
Pipenv-declared project, but cannot manufacture dependency coverage for a
project that declares no dependencies through any file `pip-audit` (or this
app) can read. Verified instead against two new fixtures built to match the
gap's shape (`tests/fixtures/poetry_project/pyproject.toml` and
`tests/fixtures/pipenv_project/Pipfile.lock`, each pinning the same known-CVE
`urllib3==1.24.1` already used by `vulnerable_project`) — both now return
real `Dependency vulnerability` findings that were previously `Unavailable`.

Full suite: 104 passed, 1 skipped (same pre-existing Docker-daemon skip),
including 6 new tests: 2 end-to-end known-answer tests against the new
fixtures, 1 covering the zero-pinned-dependencies case, and 3 unit tests for
the new pin-extraction helpers.

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

## Update 2026-09-09 — secrets dedup fix, plus 1 app bug and 1 flaky test found and fixed

Candidate next step 3 above (secrets dedup) is done. Separately, a re-verification
pass triggered by an unrelated maintenance finding surfaced one real, previously
unknown app bug and one flaky (but not app-defective) regression test in
Python-Inspector itself — both fixed the same day. Distinguishing
who did what: OpenCode (a free-tier AI coding agent) drafted the dedup fix; Claude
Code found, root-caused, and fixed the other two, and independently re-verified
all three before anything was committed; Hunter authorized the scoped fixes,
tests, and pushes in chat.

**Why this pass happened:** a separate maintenance mission on the shared
verify-repair tooling (Hunter's own agent-fleet verification controller, not part
of this repo) found that tool's acceptance checker had been silently treating any
external-command check as "passed" regardless of its real exit code. That defect
was live during several past missions against this repo, including the one that
added `docs/QA_VERIFICATION.md`'s documented combined-test command
(`codex-pytestscope-20260907`) — so its recorded "PASS" wasn't actually proven at
the time. Re-verifying it for real, independent of that tool, is what surfaced
the app bug and the flaky test below. See the [AI-worker supervision case
study](https://github.com/hunter-terry/ai-orchestration-portfolio/blob/master/02-fleet-supervision/case-study.md)
for the full correction to that historical claim.

- **Secrets dedup** (candidate step 3, drafted by OpenCode, cleaned up and
  verified by Claude Code): `run_detect_secrets` created one `Finding` per
  detector-type hit instead of one per unique secret, so the vulnerable
  fixture's single hardcoded AWS key still showed up 3 times (`AWS Access Key`,
  `Base64 High Entropy String`, `Secret Keyword`) even after the false-positive
  fix above. Fixed by grouping hits on `(file_path, line_number, hashed_secret)`
  and listing every detected type in one finding. Commit `4079e05`.
- **`approve_and_run()` TypeError against the shipped demo backend** (found and
  fixed by Claude Code, not part of any fleet dispatch): `AppController` always
  calls `backend.run_approved_check(request, is_cancelled=...)`. `RealBackend`
  accepted that parameter; the documented `InspectorBackend` contract and
  `MockBackend` — the backend the app actually constructs by default — did not.
  Every real "Approve and run" click against the demo backend raised a
  `TypeError` inside the background worker thread, which was caught and turned
  into a failure `RunResult` before a test could observe it, making a real
  interface bug look like GUI-test flakiness. Root-caused by tracing the
  worker's actual result payload directly (not by inspection alone). Fixed by
  extending the contract and `MockBackend` to accept `is_cancelled` (matching
  `RealBackend`'s existing signature) rather than removing it from the call
  site, so real cancellation support for long-running checks was not dropped.
  New regression test:
  `test_run_approved_check_accepts_is_cancelled_like_the_real_caller` — confirmed
  failing with the exact `TypeError` against the pre-fix signature, passing
  after. Commit `f36a4af`.
- **Flaky minimize/restore repaint regression test** (found and fixed by Claude
  Code): `test_minimize_restore_forces_repaint` polled the window's alpha value
  at ~20ms granularity to catch a repaint nudge that only holds a non-1.0 alpha
  for ~1ms, an observation window narrow enough that pump()'s coarser polling
  could step over it entirely — measured at roughly a 1-in-4 real failure rate
  over repeated runs, with no change in app behavior. This was a test-timing
  gap, not an app defect: the app's own repaint-nudge mechanism is unchanged.
  Fixed by tracing the actual `_force_repaint` call directly instead of racing
  a polling loop against a 1ms window; 10/10 clean runs after the fix. Commit
  `f36a4af`.

Full suite, 2026-09-09, commit `f36a4af`: **107 passed, 1 skipped, 174.16s**
(`.venv\Scripts\python -m pytest -q`). Combined suite (adds
`evidence/verify_ui.py`, the separate GUI regression file `pyproject.toml`
excludes from the bare command above): **120 passed, 1 skipped, 1 failed,
238.33s** (`.venv\Scripts\python -m pytest tests evidence\verify_ui.py -q -rs`).
The 1 skip and the 1 failure are the same root cause reported twice by two
different tests: Docker Desktop's daemon could not be started in this
environment during this pass — an environment gap, not a code regression. No
other failures were observed in either suite.

## Commands run

```powershell
.venv\Scripts\python -m pytest -q            # 107 passed, 1 skipped, 174.16s (2026-09-09, commit f36a4af)
.venv\Scripts\python -m pytest -q -rs        # skip reason: tests\test_backend_sandbox.py:132, Docker daemon not reachable
.venv\Scripts\python -m pytest tests evidence\verify_ui.py -q -rs   # combined suite: 120 passed, 1 skipped, 1 failed, 238.33s (2026-09-09, commit f36a4af)
```

The three real-world scans were run via a throwaway script (not committed —
scratch, not part of the app) that imported `RealBackend` directly and called
`scan_local_project(target_path, ...)` then `render_report(result)`, writing
the two resulting Markdown documents per project.

## Evidence

Full per-finding evidence for the three private validation projects (paths,
file/line locations, and exact findings) is kept locally rather than in this
public repo — see the note in Method above. `evidence/demo-report.md` (a scan
of the public `psf/requests` repo) is the one full example report published
here.

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
