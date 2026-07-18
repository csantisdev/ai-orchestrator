import json
import threading
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import orchestrator.db as db
import orchestrator.paths as paths
from orchestrator.rates import refresh_rate


def _reset_temp_db(temp_root: Path) -> None:
    paths.HOME_DIR = temp_root
    paths.DB_PATH = temp_root / "runs.db"
    db._local = threading.local()


def test_refresh_rate_fetches_and_persists_bcch_value():
    tmp_root = Path(tempfile.mkdtemp(prefix="aio-rates-"))
    original_home = paths.HOME_DIR
    original_db = paths.DB_PATH
    _reset_temp_db(tmp_root)

    payload = {
        "Codigo": 0,
        "Series": {
            "Obs": [
                {"indexDateString": "2026-07-17", "value": "987.65"},
            ]
        },
    }
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode("utf-8")
    response.headers.get.return_value = "application/json; charset=utf-8"

    try:
        db.init_db()
        with patch("orchestrator.rates.urllib.request.urlopen", return_value=response) as mock_urlopen:
            result = refresh_rate({"bcentral": {"user": "user", "pass": "pass"}})

        assert result["currency"] == "USD_CLP"
        assert result["rate"] == 987.65
        assert mock_urlopen.call_count == 1

        row = db._conn().execute(
            "SELECT date, rate, currency, fetched_at, source FROM exchange_rates ORDER BY date DESC LIMIT 1"
        ).fetchone()
        assert row["currency"] == "USD_CLP"
        assert row["rate"] == 987.65
        assert row["source"] == "bcentral"
    finally:
        db._local = threading.local()
        paths.HOME_DIR = original_home
        paths.DB_PATH = original_db