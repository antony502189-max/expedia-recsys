from __future__ import annotations

from typing import Any

from expedia_analytics.final_marts_advanced import _create_advanced_marts
from expedia_analytics.final_marts_base import _create_base_marts


def _create_marts(con: Any, contract: dict[str, Any]) -> None:
    _create_base_marts(con, contract)
    _create_advanced_marts(con)
