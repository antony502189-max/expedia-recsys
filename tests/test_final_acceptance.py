from __future__ import annotations

import json

from expedia_analytics.final_acceptance import _manual_verification


def test_manual_verification_accepts_utf8_bom(tmp_path) -> None:
    path = tmp_path / "manual_verification.json"
    payload = {
        "left_build": "build-a",
        "right_build": "build-b",
        "representative_rows_verified": True,
        "headline_totals_verified": True,
        "quarantine_rows_reviewed": True,
        "reviewer": "reviewer",
        "verified_utc": "2026-08-08T08:27:42Z",
        "notes": "checked",
    }
    path.write_text(json.dumps(payload), encoding="utf-8-sig")

    loaded, checks = _manual_verification(
        path,
        left_build="build-a",
        right_build="build-b",
    )

    assert loaded == payload
    assert checks
    assert all(check["passed"] for check in checks)
