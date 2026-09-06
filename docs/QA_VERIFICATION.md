# Python Inspector QA repair — 2026-09-04

The Results freeze was reproduced and repaired. This build can scan, review,
copy repair packets, save complete reports, and display real approved runtime
output. No AI service or automatic source repair was added.

## What changed

- Results now renders at most ten finding cards per page. Returning from
  details/report preview reuses those cards and preserves the page. Only the
  active screen is mapped, avoiding overlapping canvases and hidden layout work.
- Results and saved reports distinguish confirmed failures, strong findings,
  possible findings, and informational results. Incomplete scanner coverage is
  visible in Results. Both saved and copied repair packets include instructions
  to validate source evidence, propose a minimal change and regression test,
  treat project text as untrusted, and disclose uncertainty.
- Runtime work stays off the Tk thread. Repeated approval dispatch cannot start
  duplicate runs; unexpected worker failures return a visible result. Output
  includes both stdout and stderr, command, duration, timeout, and exit status.
  The last result can be reopened from Results. A timeout never displays Passed.
- Scan something else ends the review session, removes disposable GitHub content
  and its parent, and clears prior approval/report/run state. Closing waits for
  active workers to finish cleanup. Local source folders are never deleted.
- Native dialogs have an explicit parent. Save errors stay visible in the report
  screen. Clipboard copying displays a Copied acknowledgement.
- `Start Python Inspector.cmd` launches the installed app without a console.

## Evidence

Original code: 400 synthetic findings with return-from-details navigation produced
an **87.065-second event-loop gap**, taking 96.945 seconds to reach a scheduled
50-second finish. This isolates the UI cost from scanning.

Repaired code: same 400-finding probe completed in **50.011 seconds**, with a
maximum event-loop gap of **0.728 seconds** and only **10 cards** allocated.
Windows `Get-Process` polling recorded **97/97 Responding=True samples** at
roughly 500 ms intervals. Logs are in `evidence/windows-responsiveness.json`,
`evidence/responsiveness-output.txt`, and `evidence/responsiveness-errors.txt`.
These are measurements on this machine, not a universal performance guarantee.

Real-widget checks cover all 40 pages, 12 details/return cycles, one visible
screen, header button mouse events, system clipboard readback, cancelled/failed
save, worker exceptions, duplicate approval suppression, timeout display, and
reopening run output. Native Windows Save dialogs wrote real reports for both
1 and 400 synthetic findings; five consecutive native folder selections worked.

A real read-only scan of a generated safe fixture produced **322 findings**.
The real native Save dialog wrote the complete report, including the final
finding. Clipboard text contained the real scanner evidence. An explicit
Approve and run event launched the fixture's test inside the existing Docker
runner and the UI displayed **1 passed**, with separate stdout/stderr sections.
SHA-256 snapshots of every fixture file were identical before and after.
A live public `octocat/Hello-World` scan removed its clone and parent when
Scan something else ended the session.

Commands run from the project root:

```powershell
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m pytest tests\test_backend_report.py tests\test_session_lifecycle.py -q
.venv\Scripts\python -m pytest evidence\verify_ui.py -q -s
.venv\Scripts\python evidence\measure_results.py 400
```

The original full suite passed **81/81, zero skips** before and after the core
changes (178.29 s baseline; 164.42 s after). Final report/lifecycle checks passed
**10/10**, including five new regressions. The complete final real-widget GUI
suite passed **13/13 in 90.19 seconds**, including the real scanner, native
dialogs, clipboard readback, Docker output, and GitHub cleanup. The GUI harness requires a Windows
display and normal GitHub/Docker access; it is intentionally separate from the
default tests. Sandboxed baseline failures were environment access errors, and
the normal-access rerun passed. Native GUI automation and screenshot-harness
errors were corrected separately from application code.

## Cleanup requirement discrepancy and limitations

The QA order says no clone should remain immediately on entering Results. The
approved backend requirement says remove it when the session ends; existing
tests also require retaining it during review to support an approved run.
This implementation preserves that backend behavior and now explicitly ends
the session on Scan something else or normal close. **Immediate deletion on
entry to Results is not implemented.** Thus the app repairs are operationally
verified, but the literal QA checklist is not completely satisfied. No claim
is made that an abrupt process kill or machine crash runs cleanup handlers.

The Results/header/clipboard buttons worked in the controlled live checks;
the original isolated button failures were not independently reproduced apart
from the long freeze. The folder-dialog failure after three uses did not
reproduce in five consecutive selections. Minimize/restore behavior has not
been separately certified across Windows themes, monitors, or DPI settings.

This is a deterministic scanner and repair handoff, not an exhaustive security
assessment or a guarantee about legal liability. Runtime checks run the
project's existing pytest suite; a passing suite does not prove a specific
finding is fixed. The runner does not install project dependencies. Dependency
advisory scanning retains V1's requirements-file coverage limits. Review the
displayed check coverage and test any AI-proposed repair before relying on it.

## Files

Application: `ui/screen_results.py`, `ui/app_window.py`,
`ui/screen_repair_details.py`, `state.py`, `models.py`,
`backend/real_backend.py`, `backend/report.py` under `src/inspector_app/`.
Also: `tests/test_session_lifecycle.py`, the three QA scripts under `evidence/`,
`.gitignore`, `README.md`, this document, and `Start Python Inspector.cmd`.
Changes are local and reviewable; no deployment or publication was performed.
