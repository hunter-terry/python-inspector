"""Shared helpers for building `Finding` objects honestly and safely:
stable IDs and secret redaction.
"""
from __future__ import annotations

import hashlib


def stable_finding_id(prefix: str, *parts: str) -> str:
    """A finding ID that stays the same across re-scans of unchanged code.

    Built from a hash of the scanner + rule + location, not from position in
    a list, so it does not shift just because an earlier finding disappeared.
    """
    key = "|".join(parts)
    digest = hashlib.sha1(key.encode("utf-8", errors="replace")).hexdigest()[:8]
    return f"{prefix}-{digest.upper()}"


# Bandit test IDs that specifically detect a hardcoded secret/password value.
# Bandit's own issue_text and code snippet for these include the literal
# secret value, which must never reach a Finding or the saved report.
SECRET_VALUE_BANDIT_TEST_IDS = {"B105", "B106", "B107"}
