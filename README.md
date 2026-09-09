# Python Inspector (V1)

A Windows desktop app that finds likely bugs and security vulnerabilities in
a Python project and hands out a report — a plain-English summary plus a
technical repair packet a person or an external AI can act on.

**No AI, cloud model, or paid API runs inside this program.**

Part of Hunter Terry's [AI Orchestration & Verification Portfolio](https://github.com/hunter-terry/ai-orchestration-portfolio/blob/master/03-python-inspector/case-study.md) · [GitHub profile](https://github.com/hunter-terry)

## Status

Both the frontend (interaction design and screens) and the backend (scanning
and safety controls) are complete. `src/inspector_app/backend/`
is the real, deterministic backend (`RealBackend`), wired into the app in
place of the demo-only `mock_data.MockBackend`. See
[docs/INTERFACE_CONTRACT.md](docs/INTERFACE_CONTRACT.md) for the contract it
implements, and [docs/QA_VERIFICATION.md](docs/QA_VERIFICATION.md) /
[docs/DETECTION_VALIDATION.md](docs/DETECTION_VALIDATION.md) for full build
and validation evidence.

Real, read-only scanning uses four proven open-source tools — **ruff**
(syntax/quality), **bandit** (security patterns), **pip-audit** (known
vulnerable dependencies), **detect-secrets** (hardcoded secrets) — plus a
small first-party repository/configuration checker. The one approval-gated
runtime check (running a project's own `pytest` suite, only after you press
**Approve and run**) executes inside a disposable, `--network none`
Docker container; if real isolation cannot be proven on the machine, the
check is refused rather than run unsafely.

## Product rules this build follows

- The first scan is always read-only.
- Nothing from the inspected project runs until you press **Approve
  and run** on the exact command shown to you.
- The app never modifies the inspected source project.
- The app does not become a place that stores project files.
- A report is written to disk only after you press **Save report**
  and pick a destination.
- Results always distinguish confirmed failures from possible findings,
  and the app never claims to guarantee it found every bug or
  vulnerability.

## Running it

After cloning this repo and installing dependencies (see the commands below),
double-click **Start Python Inspector.cmd** in the project folder, or launch
it from source with `python -m inspector_app.main` (see below). Choose a
project, review the source, then scan. Results show ten
findings per page; returning from details or report preview keeps your place.
Use **Copy for repair** for one finding or **Save report** for the complete report.
After an approved test run, **View last run output** reopens both stdout and stderr.

A public GitHub clone remains available only during its review session so an
approved test can use the reviewed source. **Scan something else** or closing
the app ends the session and removes that copy. Closing during work waits for
worker cleanup to finish.

Before accepting an AI repair, have it verify the finding in your source,
explain the proposed change, and supply a regression test. Review the diff,
run the relevant tests, and scan again. A test pass or clean scan does not
establish that a product is secure or that every finding was fixed.

See [QA verification](docs/QA_VERIFICATION.md) for measured results and V1 limits.

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements-backend.txt
.venv\Scripts\python -m pytest              # no GUI required; see docs/DETECTION_VALIDATION.md for the current dated count
cd src && ..\.venv\Scripts\python -m inspector_app.main   # launches the app
```

`requirements-backend.txt` includes everything in `requirements.txt` plus
the four scanner packages (bandit, ruff, pip-audit, detect-secrets). Docker
Desktop must be running for the one approval-gated runtime check to work;
without it, that check is refused with a clear explanation rather than
running unsafely — everything else (scanning, GitHub retrieval, reports)
works with no Docker dependency.

## Project layout

```
src/inspector_app/
  models.py       data shapes shared with the backend
  contract.py     InspectorBackend Protocol — what the backend must implement
  state.py        UI-independent screen/flow state machine (unit tested)
  mock_data.py    MockBackend — demo-only fabricated findings, not a scanner
  backend/        RealBackend — the real, deterministic implementation:
                    scanners.py     ruff / bandit / pip-audit / detect-secrets
                                    / repo-config-checker wrappers
                    github_source.py public-repo-only clone into a disposable,
                                    size-capped, cancellable workspace
                    sandbox.py      Docker-isolated (--network none) approval
                                    -gated runtime executor
                    report.py       renders the two-layer report
                    real_backend.py orchestrates the above into InspectorBackend
  main.py         entry point
  ui/             seven customtkinter screens + the AppController that
                   wires background scan threads to them
tests/            pytest tests against models/state/mock_data and the real
                   backend (scanners, GitHub retrieval, sandbox, safety,
                   report redaction, end-to-end) — no display required
tests/fixtures/   small throwaway Python projects used only by backend tests
docs/INTERFACE_CONTRACT.md   the contract the backend implements
```

## Screens implemented

1. Start — choose a local folder or paste a GitHub link.
2. Project review — confirms the source before anything happens.
3. Scanning — live progress, cancel, and failed/cancelled recovery states.
4. Results — plain-English findings, severity, confirmed vs. possible.
5. Repair details — exact file/line, evidence, fix, verification steps,
   copy-to-clipboard.
6. Run approval — exact command, purpose, safety boundary, risk; no
   preselected decision.
7. Save report — full preview; nothing is written until Save report is
   pressed and a destination chosen.
