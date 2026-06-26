"""Cliente para el Servicio Web Estadístico del Banco Central de Chile (BCCh).

Obtiene el dólar observado (F073.TCO.PRE.Z.D) y cachea el resultado en SQLite
para no hacer más de una request por día.
"""

from __future__ import annotations

import urllib.request
import urllib.parse
import json
from datetime import datetime, timezone, date, timedelta
from typing import Optional


_BCENTRAL_URL = "https://si3.bcentral.cl/SieteRestWS/SieteRestWS.ashx"
_SERIES_USD_CLP = "F073.TCO.PRE.Z.D"   # Dólar observado diario
_CURRENCY_KEY   = "USD_CLP"


def get_bcentral_config(config: dict) -> dict:
    """Retorna credenciales BCCh desde config o vacío."""
    return config.get("bcentral", {})


def _fetch_from_api(user: str, password: str, series: str = _SERIES_USD_CLP) -> Optional[float]:
    """Llama al API del BCCh y retorna el valor más reciente de la serie."""
    today = date.today()
    week_ago = today - timedelta(days=7)
    params = {
        "function":   "GetSeries",
        "user":       user,
        "pass":       password,
        "timeseries": series,
        "firstdate":  week_ago.isoformat(),
        "lastdate":   today.isoformat(),
        "format":     "json",
    }
    url = _BCENTRAL_URL + "?" + urllib.parse.urlencode(params)
    try:
        req = urllib.request.urlopen(url, timeout=10)
        raw = req.read()
        # BCCh responde en Latin-1; detectar desde header Content-Type o fallback
        charset = "utf-8"
        ct = req.headers.get("Content-Type", "")
        if "charset=" in ct:
            charset = ct.split("charset=")[-1].split(";")[0].strip()
        try:
            data = json.loads(raw.decode(charset))
        except (UnicodeDecodeError, LookupError):
            data = json.loads(raw.decode("latin-1"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"BCCh: error decodificando respuesta: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"BCCh: error de conexión: {exc}") from exc

    # Verificar código de error del API antes de leer datos
    codigo = data.get("Codigo", 0)
    if codigo != 0:
        descripcion = data.get("Descripcion") or f"código {codigo}"
        raise RuntimeError(f"BCCh API: {descripcion}")

    # El API retorna {"Series": {"Obs": [{"indexDateString":"YYYY-MM-DD","value":"..."}]}}
    series_data = data.get("Series") or {}
    obs = series_data.get("Obs") or []
    if not obs:
        raise RuntimeError("BCCh API: sin observaciones — verificá el rango de fechas o el código de serie")

    # Tomar el más reciente (vienen ordenados ascendentemente)
    latest = obs[-1]
    value_str = latest.get("value", "")
    try:
        return float(str(value_str).replace(",", "."))
    except (ValueError, TypeError):
        raise RuntimeError(f"BCCh API: valor no parseable: {value_str!r}")


def refresh_rate(config: dict) -> dict:
    """Consulta el API del BCCh y guarda la tasa en caché. Retorna dict con la tasa."""
    bc = get_bcentral_config(config)
    user = bc.get("user", "").strip()
    password = bc.get("pass", "").strip()
    if not user or not password:
        raise RuntimeError("BCCh: credenciales no configuradas (bcentral.user / bcentral.pass en config.yaml)")

    rate = _fetch_from_api(user, password)
    today_str = date.today().isoformat()
    fetched_at = datetime.now(timezone.utc).isoformat()

    try:
        from orchestrator.db import _conn, _write_lock
        conn = _conn()
        with _write_lock:
            conn.execute(
                """INSERT INTO exchange_rates (date, currency, rate, source, fetched_at)
                   VALUES (?, ?, ?, 'bcentral', ?)
                   ON CONFLICT(date, currency) DO UPDATE SET
                       rate=excluded.rate, fetched_at=excluded.fetched_at""",
                (today_str, _CURRENCY_KEY, rate, fetched_at),
            )
            conn.commit()
    except Exception as exc:
        raise RuntimeError(f"BCCh: error guardando en DB: {exc}") from exc

    return {"date": today_str, "rate": rate, "currency": _CURRENCY_KEY, "fetched_at": fetched_at}


def get_current_rate(config: dict) -> Optional[dict]:
    """Retorna la tasa desde caché (o refresca si no hay dato de hoy).

    Nunca lanza excepción — retorna None si no hay credenciales o falla la red.
    """
    try:
        from orchestrator.db import _conn
        conn = _conn()
        today_str = date.today().isoformat()

        # Intentar desde caché (hoy o ayer como fallback)
        row = conn.execute(
            """SELECT date, rate, fetched_at FROM exchange_rates
               WHERE currency=? ORDER BY date DESC LIMIT 1""",
            (_CURRENCY_KEY,),
        ).fetchone()

        if row and row["date"] >= (date.today() - timedelta(days=1)).isoformat():
            return {"date": row["date"], "rate": row["rate"],
                    "currency": _CURRENCY_KEY, "fetched_at": row["fetched_at"], "from_cache": True}

        # No hay dato reciente — intentar refrescar
        bc = get_bcentral_config(config)
        if bc.get("user") and bc.get("pass"):
            return {**refresh_rate(config), "from_cache": False}

        # Sin credenciales y sin caché reciente
        if row:
            return {"date": row["date"], "rate": row["rate"],
                    "currency": _CURRENCY_KEY, "fetched_at": row["fetched_at"],
                    "from_cache": True, "stale": True}
        return None
    except Exception:
        return None


def save_bcentral_credentials(user: str, password: str) -> None:
    """Escribe credenciales BCCh en config.yaml preservando el resto del archivo."""
    import yaml
    from orchestrator.paths import CONFIG_PATH

    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    else:
        cfg = {}

    cfg.setdefault("bcentral", {})
    cfg["bcentral"]["user"] = user
    cfg["bcentral"]["pass"] = password

    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
