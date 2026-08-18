"""Verlaufsspeicher fuer die Verbrauchsgrafik auf der Uebersichtsseite.

Speichert keine Rohwerte auf Dauer (das waechst unbegrenzt), sondern nur den
jeweils letzten bekannten Zaehlerstand pro Stunde und pro Tag. Daraus laesst
sich der Verbrauch fuer Tag/Woche/Monat/Jahr per Differenzbildung berechnen -
genau wie ein Stromzaehler-Verlauf.

Speichergroesse bleibt klein: 48 Stunden- + 400 Tages-Eintraege sind zusammen
nur wenige KB.
"""

import json
from datetime import datetime, timedelta
from pathlib import Path

HOURLY_KEEP_HOURS = 48
DAILY_KEEP_DAYS = 400


def _load(path: Path, log=None) -> dict:
    if not path.exists():
        return {"hourly": {}, "daily": {}}
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        data.setdefault("hourly", {})
        data.setdefault("daily", {})
        return data
    except (OSError, json.JSONDecodeError) as exc:
        if log:
            log(f"WARNUNG: Verlauf nicht lesbar ({exc})")
        return {"hourly": {}, "daily": {}}


def _save(path: Path, data: dict, log=None) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp.json")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(data, fh)
        tmp.replace(path)
    except OSError as exc:
        if log:
            log(f"WARNUNG: Verlauf nicht speicherbar ({exc})")


def record(path: Path, value: float, timestamp: float, log=None) -> None:
    """Merkt sich den Zaehlerstand als Stunden- und Tages-Schnappschuss.

    Wird nur bei einer frischen, gueltigen Ablesung aufgerufen (nicht bei
    einem gehaltenen alten Wert) - sonst wuerde ein Ausfall faelschlich als
    Verbrauch 0 im Verlauf auftauchen, statt als Luecke.
    """
    dt = datetime.fromtimestamp(timestamp)
    hour_key = dt.strftime("%Y-%m-%d %H")
    day_key = dt.strftime("%Y-%m-%d")

    data = _load(path, log)
    data["hourly"][hour_key] = value
    data["daily"][day_key] = value

    hour_cutoff = (dt - timedelta(hours=HOURLY_KEEP_HOURS)).strftime("%Y-%m-%d %H")
    data["hourly"] = {k: v for k, v in data["hourly"].items() if k >= hour_cutoff}
    day_cutoff = (dt - timedelta(days=DAILY_KEEP_DAYS)).strftime("%Y-%m-%d")
    data["daily"] = {k: v for k, v in data["daily"].items() if k >= day_cutoff}

    _save(path, data, log)


def _deltas(snapshots: dict) -> dict:
    """Verbrauch je Schluessel = Differenz zum zeitlich vorherigen Schnappschuss."""
    keys = sorted(snapshots.keys())
    result = {}
    prev_value = None
    for k in keys:
        v = snapshots[k]
        if prev_value is not None:
            result[k] = max(0.0, round(v - prev_value, 3))
        prev_value = v
    return result


def _month_start(dt: datetime, months_back: int) -> datetime:
    total = dt.year * 12 + (dt.month - 1) - months_back
    y, m = divmod(total, 12)
    return datetime(y, m + 1, 1)


_WEEKDAY_DE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
_MONTH_DE = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
             "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]


def get_chart_data(path: Path, now_ts: float, log=None) -> dict:
    """Liefert Verbrauchsdaten (Liter) fuer Tag/Woche/Monat/Jahr."""
    data = _load(path, log)
    now = datetime.fromtimestamp(now_ts)

    hourly_deltas = _deltas(data["hourly"])
    today_str = now.strftime("%Y-%m-%d")
    day_chart = []
    for h in range(24):
        hk = f"{today_str} {h:02d}"
        liters = round(hourly_deltas.get(hk, 0.0) * 1000, 1)
        # Stunden in der Zukunft (heute, aber noch nicht erreicht) als None
        # markieren statt 0, damit die Grafik sie nicht als "kein Verbrauch"
        # zeigt.
        future = h > now.hour
        day_chart.append({"label": f"{h:02d}", "liters": None if future else liters})

    daily_deltas = _deltas(data["daily"])

    week_chart = []
    for i in range(6, -1, -1):
        d = now - timedelta(days=i)
        dk = d.strftime("%Y-%m-%d")
        liters = round(daily_deltas.get(dk, 0.0) * 1000, 1) if dk in daily_deltas else None
        week_chart.append({"label": _WEEKDAY_DE[d.weekday()], "liters": liters})

    month_chart = []
    for i in range(29, -1, -1):
        d = now - timedelta(days=i)
        dk = d.strftime("%Y-%m-%d")
        liters = round(daily_deltas.get(dk, 0.0) * 1000, 1) if dk in daily_deltas else None
        month_chart.append({"label": d.strftime("%d.%m"), "liters": liters})

    year_chart = []
    for i in range(11, -1, -1):
        start = _month_start(now, i)
        end = _month_start(now, i - 1)
        total = None
        for k, v in daily_deltas.items():
            kd = datetime.strptime(k, "%Y-%m-%d")
            if start <= kd < end:
                total = (total or 0.0) + v
        label = f"{_MONTH_DE[start.month - 1]}"
        year_chart.append({
            "label": label,
            "liters": round(total * 1000, 1) if total is not None else None,
        })

    return {"day": day_chart, "week": week_chart, "month": month_chart, "year": year_chart}
