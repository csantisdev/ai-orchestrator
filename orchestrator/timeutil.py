"""Utilidades de fecha/hora compartidas - conversion de timestamps UTC a fecha local."""

from __future__ import annotations

from datetime import date, datetime, timezone


def local_date_from_ts(ts_raw: str, tz=None) -> date | None:
    """Parsea un `ts` (se asume UTC si no trae offset) y devuelve su fecha local.

    Los runs se guardan con `ts` en UTC (`datetime.now(timezone.utc).isoformat()`).
    Comparar ese string directamente contra una fecha local (`str.startswith` o
    `date(ts)` en SQL) confunde el dia UTC con el dia local: para timezones
    negativos, la noche local ya cae en el dia UTC siguiente.

    `tz=None` (el default en produccion) convierte con `.astimezone()` sin
    argumento: Python resuelve el offset correcto de la zona LOCAL del sistema
    para ESE instante puntual (aware del cambio de horario). Reutilizar en
    cambio un tzinfo de offset fijo obtenido una sola vez (`datetime.now()
    .astimezone().tzinfo`) es lo que rompia con DST: ese offset es el vigente
    en el momento en que se calculo, no el que corresponde a `ts_raw` si hubo
    un cambio de horario entre medio. Pasar `tz` explicito (tests) preserva el
    comportamiento anterior para offsets fijos conocidos.
    """
    if not ts_raw:
        return None
    try:
        ts_dt = datetime.fromisoformat(ts_raw)
    except ValueError:
        return None
    if ts_dt.tzinfo is None:
        ts_dt = ts_dt.replace(tzinfo=timezone.utc)
    return ts_dt.astimezone(tz).date()
