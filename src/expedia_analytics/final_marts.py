from __future__ import annotations

from typing import Any

from expedia_analytics.final_marts_advanced import _create_advanced_marts
from expedia_analytics.final_marts_base import _create_base_marts


def _create_bounded_statistical_macros(con: Any) -> None:
    con.execute(
        """
        CREATE OR REPLACE MACRO wilson_low(successes, total) AS
            CASE WHEN total > 0 THEN LEAST(
                successes::DOUBLE / total,
                GREATEST(
                    0.0,
                    ((successes::DOUBLE / total) + 1.9208 / total
                     - 1.96 * SQRT(
                        ((successes::DOUBLE / total) * (1 - successes::DOUBLE / total)
                         + 0.9604 / total) / total
                     )) / (1 + 3.8416 / total)
                )
            ) ELSE NULL END;
        CREATE OR REPLACE MACRO wilson_high(successes, total) AS
            CASE WHEN total > 0 THEN GREATEST(
                successes::DOUBLE / total,
                LEAST(
                    1.0,
                    ((successes::DOUBLE / total) + 1.9208 / total
                     + 1.96 * SQRT(
                        ((successes::DOUBLE / total) * (1 - successes::DOUBLE / total)
                         + 0.9604 / total) / total
                     )) / (1 + 3.8416 / total)
                )
            ) ELSE NULL END;
        """
    )


def _create_marts(con: Any, contract: dict[str, Any]) -> None:
    _create_bounded_statistical_macros(con)
    _create_base_marts(con, contract)
    _create_advanced_marts(con)
