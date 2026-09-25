from datetime import date, datetime, timedelta, timezone, tzinfo

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


def test_default_tz_delegates_to_system_astimezone():
    """El default (sin tz) debe llamar a .astimezone() sin argumento, que
    resuelve el offset del sistema PARA ESE instante. No es DST-real porque
    depende de la zona configurada en la maquina que corre el test - eso se
    verifico manualmente (Windows, zona Santiago: UTC-3 en enero vs UTC-4 en
    julio). Este test solo fija que el wiring es ese, comparando contra el
    mismo mecanismo aplicado a mano."""
    ts = "2026-08-25T12:00:00+00:00"
    expected = datetime.fromisoformat(ts).astimezone().date()
    assert local_date_from_ts(ts) == expected
    assert local_date_from_ts(ts, None) == local_date_from_ts(ts)


class _SyntheticDstTz(tzinfo):
    """tzinfo minimo con una regla de cambio de offset determinista y
    portable (no depende de la zona real de la maquina que corre el test),
    para probar que local_date_from_ts resuelve el offset POR INSTANTE via
    .astimezone(tz) y no lo reutiliza de otro momento.

    Sobrescribe fromutc() en vez de apoyarse en el algoritmo default
    (utcoffset()/dst() con deteccion de fold) - la version anterior de este
    tzinfo no preservaba el instante en la conversion (round-trip UTC ->
    local -> UTC no volvia al mismo valor), aunque la fecha final le
    resultara casualmente correcta a este test puntual. fromutc() recibe un
    datetime cuyos campos YA representan el instante UTC (tageado con
    tzinfo=self) y construye directamente el resultado, sin ambiguedad.
    """

    _TRANSITION = datetime(2026, 6, 1, 3, 0)  # naive, representa un instante UTC

    def _offset_for_utc_instant(self, naive_utc: datetime) -> timedelta:
        return timedelta(hours=-4) if naive_utc >= self._TRANSITION else timedelta(hours=-3)

    def fromutc(self, dt):
        offset = self._offset_for_utc_instant(dt.replace(tzinfo=None))
        return (dt + offset).replace(tzinfo=self)

    def utcoffset(self, dt):
        if dt is None:
            return timedelta(hours=-3)
        return self._offset_for_utc_instant(dt.replace(tzinfo=None))

    def dst(self, dt):
        return timedelta(0)

    def tzname(self, dt):
        return "SYN"


def test_explicit_tz_resolves_offset_per_instant_across_a_transition():
    """Con una tz sintetica que cambia de -3 a -4 en una fecha conocida, un
    timestamp justo despues de la transicion debe resolverse con el offset
    NUEVO. Si se reutilizara el offset viejo (-3, capturado antes de la
    transicion) - el bug real que se corrigio en los callers de
    local_date_from_ts -, el resultado caeria en el dia calendario
    incorrecto."""
    tz = _SyntheticDstTz()
    after_transition = "2026-06-01T03:30:00+00:00"

    correct_with_new_offset = local_date_from_ts(after_transition, tz)
    assert correct_with_new_offset == date(2026, 5, 31)  # 03:30 - 4h = 23:30 del 31/05

    wrong_with_stale_old_offset = datetime.fromisoformat(after_transition).astimezone(
        timezone(timedelta(hours=-3))
    ).date()
    assert wrong_with_stale_old_offset == date(2026, 6, 1)  # 03:30 - 3h = 00:30 del 01/06
    assert correct_with_new_offset != wrong_with_stale_old_offset
