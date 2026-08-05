from pathlib import Path

from expedia_recsys.duck import sql_path


def test_sql_path_escapes_quote(tmp_path: Path) -> None:
    escaped = sql_path(tmp_path / "o'hare.csv")
    assert "o''hare.csv" in escaped
    assert "\\" not in escaped
