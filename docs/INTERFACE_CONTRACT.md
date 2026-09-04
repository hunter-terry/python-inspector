# Frontend → Backend interface contract

This is what the backend work order (`Implement V1 Python Inspector
backend and safety controls`) must deliver. The frontend already depends
on this contract and only on this contract — nothing in `ui/` or
`app_window.py` needs to change if the backend satisfies it.

Source of truth: [`src/inspector_app/contract.py`](../src/inspector_app/contract.py)
(the `InspectorBackend` Protocol) and
[`src/inspector_app/models.py`](../src/inspector_app/models.py) (the data
shapes below). Read those two files directly — this document explains the
*why*, they are the exact *what*.

## What the backend must provide

An object implementing `InspectorBackend`:

```python
class InspectorBackend(Protocol):
    def scan_local_project(self, folder_path: str, *, on_progress, is_cancelled) -> ScanResult: ...
    def scan_github_project(self, repo_url: str, *, on_progress, is_cancelled) -> ScanResult: ...
    def build_approval_request(self, scan_result: ScanResult, finding_id: str) -> ApprovalRequest: ...
    def run_approved_check(self, request: ApprovalRequest) -> RunResult: ...
    def render_report(self, scan_result: ScanResult) -> ReportDocument: ...
```

The frontend's `AppController` (`ui/app_window.py`) currently constructs
`mock_data.MockBackend()`. Swapping to the real backend is a one-line
change: pass the real backend into `AppController(root, backend=...)`.

## Threading contract

`scan_local_project` / `scan_github_project` are called on a background
thread. Implementations must:

- Call `on_progress(current_check_label: str, fraction_complete: float)`
  periodically. `fraction_complete` is 0.0–1.0.
- Poll `is_cancelled()` between checks (not just once) and return a
  `ScanResult(cancelled=True, ...)` promptly when it goes `True`. **Do not
  raise** on cancellation — return a normal `ScanResult` with `cancelled=True`.
- Never raise past the frontend boundary for expected failure modes
  (network down, invalid URL, oversized repo, tool crash). Return
  `ScanResult(failed=True, failure_reason=...)` instead. An *unexpected*
  exception is still caught by the frontend (`app_window.py`'s worker
  wraps the call in try/except) and surfaced as a failed scan, but a
  clean `failed=True` result is always preferable because it lets you
  supply an honest `failure_reason`.

## Data shapes (`models.py`)

- **`Finding`** — one issue. Must include `file_path`/`line_number` when
  available, `evidence`, `suggested_repair`, `verification_steps`, and a
  `status` (`FindingStatus`) that honestly distinguishes a confirmed
  failure from a possible finding — never upgrade confidence to make a
  result look more complete.
- **`ScanResult`** — `scanners_run: tuple[ScannerRunRecord, ...]` must
  report every checker attempted, with `CheckOutcome.RAN` /
  `UNAVAILABLE` / `FAILED`. A tool that failed or was skipped must never
  be reported as `RAN`; the overall `ScanResult` must not claim success
  if any required checker failed outright.
- **`ApprovalRequest`** — the *exact* command/test to display, in
  `command_display`. Whatever string you put here is what Hunter sees
  before approving — it must be the literal command that will run, not a
  paraphrase.
- **`RunResult`** — produced only by `run_approved_check`, only after the
  frontend has already recorded Hunter's approval. `run_approved_check`
  must enforce, itself, the isolation rules from the backend work order
  (disposable copy, `shell=True` forbidden, timeout, no inherited
  secrets, network disabled where enforceable) — the frontend does not
  and cannot enforce these; it only decides *when* to call this method.
- **`ReportDocument`** — `hunter_summary_markdown` (plain English) and
  `technical_packet_markdown` (repair packet) are rendered verbatim in
  the Save Report screen's preview and in the saved file. Never include
  credentials, tokens, or unrelated file contents in either string.

## Things the frontend already guarantees (do not re-implement in the backend)

- Nothing calls `run_approved_check` except in direct response to Hunter
  pressing **Approve and run** on the exact `ApprovalRequest` shown.
- The report is written to disk only inside `save_report_to_disk`
  (`ui/app_window.py`), only after Hunter picks a destination in the
  native save dialog. The backend never needs to write the report file
  itself.
- Cancelling a scan or a run approval is always available to Hunter and
  always leaves state consistent (verified by `tests/test_state.py`).

## Honesty requirements carried through from the source idea

- `ScanResult.GUARANTEE_DISCLAIMER` is rendered on every Results screen
  and in every saved report. Do not build a backend that undermines it by
  overstating coverage elsewhere in a finding's text.
- If a scanner is unavailable in the runtime environment, that must show
  up as `CheckOutcome.UNAVAILABLE` in `scanners_run`, not be silently
  dropped.
