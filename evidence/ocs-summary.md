# Inspection summary — C:\Users\hunte\Documents\Second Brain\2-work\client-opportunity-scanner

**1 confirmed failures, 14 strong findings, 3 possible findings, 26 informational findings.**

- **[High / Confirmed failure] Dependency vulnerability** — pytest 8.4.2 has a publicly known security vulnerability (CVE-2025-71176, GHSA-6w46-j5rx-g56g).
  What could happen: An attacker could exploit the known flaw in this package version if it is reachable in this application.
- **[High / Possible finding] Security: Secrets** — A string that looks like a Hex High Entropy String was found in a source file.
  What could happen: If this is a real, active secret, anyone with the source code could use it.
- **[Medium / Strong finding] Security** — Audit url open for permitted schemes. Allowing use of file:/ or custom schemes is often unexpected.
  What could happen: See https://cwe.mitre.org/data/definitions/22.html for the general category of risk this pattern falls into.
- **[Medium / Strong finding] Security** — Audit url open for permitted schemes. Allowing use of file:/ or custom schemes is often unexpected.
  What could happen: See https://cwe.mitre.org/data/definitions/22.html for the general category of risk this pattern falls into.
- **[Medium / Possible finding] Security** — Possible SQL injection vector through string-based query construction.
  What could happen: See https://cwe.mitre.org/data/definitions/89.html for the general category of risk this pattern falls into.
- **[Medium / Strong finding] Code quality** — Use of regular expression alias `re.I`
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Medium / Strong finding] Code quality** — Use of regular expression alias `re.I`
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Medium / Strong finding] Code quality** — Use of regular expression alias `re.I`
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Medium / Strong finding] Code quality** — Use of regular expression alias `re.I`
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Medium / Strong finding] Code quality** — Use of regular expression alias `re.I`
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Medium / Strong finding] Code quality** — Use of regular expression alias `re.I`
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Medium / Strong finding] Code quality** — Use of regular expression alias `re.I`
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Medium / Strong finding] Code quality** — Use of regular expression alias `re.I`
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Medium / Strong finding] Code quality** — Use of regular expression alias `re.I`
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Medium / Strong finding] Code quality** — Use of regular expression alias `re.I`
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Medium / Strong finding] Code quality** — Use of regular expression alias `re.I`
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Medium / Strong finding] Code quality** — Use of regular expression alias `re.I`
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Low / Possible finding] Security: Secrets** — A hardcoded credential-like value was found in source code.
  What could happen: See https://cwe.mitre.org/data/definitions/259.html for the general category of risk this pattern falls into.
- **[Low / Informational] Code quality** — Import block is un-sorted or un-formatted
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Low / Informational] Code quality** — Import block is un-sorted or un-formatted
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Low / Informational] Code quality** — Import block is un-sorted or un-formatted
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Low / Informational] Code quality** — Unpacked variable `bus` is never used
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Low / Informational] Code quality** — Local variable `categories_by_id` is assigned to but never used
  What could happen: This is unused code. It does not break anything by itself, but it makes the file harder to read and maintain.
- **[Low / Informational] Code quality** — Do not catch blind exception: `Exception`
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Low / Informational] Code quality** — Unpacked variable `bus2` is never used
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Low / Informational] Code quality** — Unpacked variable `bus` is never used
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Low / Informational] Code quality** — Import block is un-sorted or un-formatted
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Low / Informational] Code quality** — Use a single `with` statement with multiple contexts instead of nested `with` statements
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Low / Informational] Code quality** — Import block is un-sorted or un-formatted
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Low / Informational] Code quality** — Import block is un-sorted or un-formatted
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Low / Informational] Code quality** — Unnecessary `start` argument in `range`
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Low / Informational] Code quality** — Return the condition `uname in self.db.all_candidate_usernames()` directly
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Low / Informational] Code quality** — Use a single `with` statement with multiple contexts instead of nested `with` statements
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Low / Informational] Code quality** — Unnecessary `start` argument in `range`
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Low / Informational] Code quality** — Unpacked variable `bus` is never used
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Low / Informational] Code quality** — `threading` imported but unused
  What could happen: This is unused code. It does not break anything by itself, but it makes the file harder to read and maintain.
- **[Low / Informational] Code quality** — Unused `noqa` directive (unused: `BLE001`)
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Low / Informational] Code quality** — Import block is un-sorted or un-formatted
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Low / Informational] Code quality** — Local variable `events` is assigned to but never used
  What could happen: This is unused code. It does not break anything by itself, but it makes the file harder to read and maintain.
- **[Low / Informational] Code quality** — Remove quotes from type annotation
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Low / Informational] Code quality** — Use a single `with` statement with multiple contexts instead of nested `with` statements
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Low / Informational] Code quality** — `os` imported but unused
  What could happen: This is unused code. It does not break anything by itself, but it makes the file harder to read and maintain.
- **[Low / Informational] Code quality** — Use a single `with` statement with multiple contexts instead of nested `with` statements
  What could happen: This may make the code harder to read or slightly more error-prone, without necessarily being an active bug.
- **[Low / Informational] Code quality** — Local variable `first_requests` is assigned to but never used
  What could happen: This is unused code. It does not break anything by itself, but it makes the file harder to read and maintain.

This scan cannot guarantee that every possible bug or vulnerability has been found.