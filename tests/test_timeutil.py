from datetime import date, datetime, timedelta, timezone

from orchestrator.timeutil import local_date_from_ts


def test_negative_offset_evening_run_stays_on_correct_local_day():
    """Regresion del bug real: un run a las 23:53 hora local (UTC-4) queda
    guardado como 2026-08-25T03:53 UTC (ya paso medianoche UTC). Comparar
    contra la fecha UTC lo asignaria al dia siguiente; debe quedar en 24/08."""
    tz = timezone(timedelta(hours=-4))
    assert local_date_from_ts("2026-08-25T03:53:00+00:00", tz) == date(2026, 8, 24)


def test_positive_offset_early_morning_run():
    tz = timezone(timedelta(hours=9))
    assert local_date_from_ts("2026-08-24T20:10:00+00:00", tz) == date(2026, 8, 25)


def test_naive_ts_assumed_utc():
    tz = timezone(timedelta(hours=-3))
    assert local_date_from_ts("2026-08-25T01:00:00", tz) == date(2026, 8, 24)


def test_empty_or_invalid_returns_none():
    tz = timezone.utc
    assert local_date_from_ts("", tz) is None
    assert local_date_from_ts("not-a-date", tz) is None


def test_default_tz_resolves_per_instant_not_a_frozen_offset():
    """Regresion: el default (sin tz) debe resolver el offset local del
    sistema PARA ESE instante puntual (.astimezone() sin argumento), no
    reutilizar un offset fijo capturado en otro momento - eso es lo que
    rompia con DST. Se compara contra el mismo mecanismo aplicado a mano."""
    ts = "2026-08-25T12:00:00+00:00"
    expected = datetime.fromisoformat(ts).astimezone().date()
    assert local_date_from_ts(ts) == expected
    assert local_date_from_ts(ts, None) == local_date_from_ts(ts)
