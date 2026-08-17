"""Plausibilitaetspruefung und Zustandsspeicher fuer den Zaehlerstand.

Speichert Add-on-intern in einer JSON-Datei:
  - value:       letzter guter Zaehlerstand (m3)
  - timestamp:   Unix-Zeit dieser Messung (fuer die Durchflussrate)
  - error_count: fortlaufender Zaehler aufeinanderfolgender Fehler

Plausibilitaetsregeln:
  1. Monotonie   - der neue Wert darf nie kleiner sein als der letzte gute.
  2. Max. Sprung - der Zuwachs darf max_increase nicht ueberschreiten.
"""

import json
from pathlib import Path


def load_state(path: Path, log):
    """Liest den gespeicherten Zustand. Fehlende Felder werden zu Defaults.

    Rueckgabe: dict mit value (float|None), timestamp (float|None),
    error_count (int).
    """
    state = {"value": None, "timestamp": None, "error_count": 0}
    if not path.exists():
        return state
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("value") is not None:
            state["value"] = float(data["value"])
        if data.get("timestamp") is not None:
            state["timestamp"] = float(data["timestamp"])
        state["error_count"] = int(data.get("error_count", 0))
    except (OSError, json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        log(f"WARNUNG: Zustand nicht lesbar ({exc}), behandle als leer")
    return state


def save_state(path: Path, state: dict, log):
    """Speichert den Zustand atomar."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp.json")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(state, fh)
        tmp.replace(path)
    except OSError as exc:
        log(f"WARNUNG: Zustand nicht speicherbar ({exc})")


def check(value, last_value, max_increase, allow_equal, log):
    """Prueft den neuen Wert gegen den letzten guten.

    Rueckgabe: (plausibel: bool, grund: str|None)
    Ist last_value None (erster Lauf), gilt der Wert immer als plausibel.
    """
    if last_value is None:
        log("Kein Vorwert vorhanden - erster Wert wird akzeptiert.")
        return True, None

    # Regel 1: Monotonie (Zaehler laeuft nur vorwaerts)
    if allow_equal:
        if value < last_value:
            return False, (f"Wert {value} kleiner als letzter {last_value} "
                           f"(Zaehler kann nicht rueckwaerts laufen)")
    else:
        if value <= last_value:
            return False, (f"Wert {value} nicht groesser als letzter {last_value}")

    # Regel 2: maximaler Sprung
    increase = value - last_value
    if increase > max_increase:
        return False, (f"Sprung {increase:.3f} groesser als erlaubt "
                       f"{max_increase} (Wert {value}, letzter {last_value})")

    return True, None


def flow_rate_l_min(value, last_value, last_timestamp, now, log):
    """Berechnet die Durchflussrate in Litern pro Minute.

    value/last_value in m3, Zeit in Unix-Sekunden. 1 m3 = 1000 Liter.
    Gibt None zurueck, wenn keine sinnvolle Berechnung moeglich ist
    (kein Vorwert, keine Zeit, oder Zeitdifferenz <= 0).
    """
    if last_value is None or last_timestamp is None:
        return None
    dt_seconds = now - last_timestamp
    if dt_seconds <= 0:
        return None
    liters = (value - last_value) * 1000.0
    rate = liters / (dt_seconds / 60.0)
    # Winzige negative Rundungsfehler auf 0 klemmen
    if rate < 0:
        rate = 0.0
    return round(rate, 3)
