# Working on Python-Inspector

This project is part of Hunter's fleet-managed set of repositories. If you are
OpenCode, Codex, or any coding agent other than Claude Code, read this before
touching anything — Claude Code did not see your work happen unless you show it.

## The one rule that matters

Nothing you do here counts as "done" until Claude Code independently re-runs
your check and reads your diff itself. Saying "it worked" is not evidence.
Show your work: the exact command you ran, and its exact output — not a
summary of what you believe happened.

## Before you submit anything back

1. Run the real test/check command for what you changed, and get a real, clean
   exit code. If you don't know what the right check is, say so — don't guess
   and call it passing.
2. Only touch the files you were actually asked to touch. If your change
   spread outside that scope, say so explicitly rather than leaving it
   unmentioned.
3. You get up to 3 real attempts at a given task. If you can't get a clean
   pass in 3, stop and report exactly what's still failing — don't keep
   silently retrying, and don't submit the same unchanged code twice.

## A real pitfall already found in this exact repo

`pyproject.toml` scopes `pytest` to `testpaths = ["tests"]`, which does **not**
include `evidence/verify_ui.py` (the GUI regression tests). Running `pytest -q`
and seeing everything pass does **not** mean the GUI tests were checked. If
your task touches anything under `src/inspector_app/ui/`, also run
`pytest evidence/verify_ui.py -q` explicitly and report both results.

## Standing safety boundaries for this project

Carried over from this project's own approved backend and QA work orders —
these apply to every task here, not just the one you were given:

- Do not add AI or external model calls.
- Do not automatically fix findings for the user — this app finds and
  explains problems; it does not silently patch the user's own code.
- Do not add private GitHub credential handling.
- Do not claim exhaustive vulnerability detection.
- Do not connect this product to Second Brain V2, the Claude Code Work Inbox,
  or any other of Hunter's internal systems.
- Do not install new dependencies, add paid services, or touch anything
  outside this repository without flagging it first.
- Stop and flag rather than proceed on: any new sensitive permission,
  credential use, paid service, publishing action, or a change bigger than
  what you were actually asked to do.

## Where things live

- Application code: `src/inspector_app/` (`ui/` = screens/buttons, `backend/`
  = scanning and sandbox logic, `state.py`/`models.py` = app state — see
  `docs/INTERFACE_CONTRACT.md` for the boundary between them).
- Tests: `tests/` (default `pytest` scope) and `evidence/verify_ui.py` (real
  GUI tests, run separately — see the pitfall above).
- Read `docs/QA_VERIFICATION.md` for what's already been tested and how.
