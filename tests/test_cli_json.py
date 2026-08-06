from __future__ import annotations

import json
import sys
from datetime import date

from expedia_analytics import cli


def test_validate_final_cli_serializes_date_evidence(
    monkeypatch, capsys, tmp_path
) -> None:
    result = {
        "passed": True,
        "checks": [
            {
                "name": "date_bounds",
                "passed": True,
                "actual": [date(2013, 1, 1), date(2016, 12, 31), 1461],
                "expected": [date(2013, 1, 1), date(2016, 12, 31), 1461],
            }
        ],
        "failure_count": 0,
    }
    monkeypatch.setattr(cli, "validate_latest", lambda _paths: result)
    monkeypatch.setattr(
        sys,
        "argv",
        ["expedia-analytics", "--root", str(tmp_path), "validate-final"],
    )

    cli.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["passed"] is True
    assert payload["checks"][0]["actual"][0] == "2013-01-01"
    assert payload["checks"][0]["actual"][1] == "2016-12-31"
