"""Override-Speicher fuer die getunten Rotations- und Zuschnittwerte.

Werte, die ueber die Tuner-Webseite gespeichert werden, landen hier und haben
Vorrang vor den Add-on-Optionen - so kann man die Werte live ueberschreiben,
ohne die HA-Konfiguration anzufassen.
"""

import json
from pathlib import Path

# Diese Schluessel duerfen ueber den Tuner ueberschrieben werden
TUNABLE_KEYS = (
    "rotate_angle",
    "fill_color",
    "crop_top",
    "crop_bottom",
    "crop_left",
    "crop_right",
    "jpeg_quality",
    "jpeg_subsampling",
)


def load(path: Path, log=None) -> dict:
    """Liest die Override-Werte. Leeres dict, wenn keine Datei existiert."""
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        # nur erlaubte Schluessel uebernehmen
        return {k: data[k] for k in TUNABLE_KEYS if k in data}
    except (OSError, json.JSONDecodeError) as exc:
        if log:
            log(f"WARNUNG: Tuning-Override nicht lesbar ({exc})")
        return {}


def save(path: Path, values: dict, log=None) -> None:
    """Speichert die Override-Werte atomar (nur erlaubte Schluessel)."""
    clean = {k: values[k] for k in TUNABLE_KEYS if k in values}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.json")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(clean, fh)
    tmp.replace(path)
    if log:
        log(f"Tuning-Werte gespeichert: {clean}")


def clear(path: Path, log=None) -> None:
    """Loescht die Override-Datei (zurueck zur Add-on-Konfiguration)."""
    if path.exists():
        path.unlink()
        if log:
            log("Tuning-Override zurueckgesetzt (Add-on-Konfig gilt wieder)")


def effective(opts: dict, path: Path, log=None) -> dict:
    """Liefert die effektiven Werte: Add-on-Optionen, ueberschrieben vom Override."""
    result = {k: opts[k] for k in TUNABLE_KEYS if k in opts}
    result.update(load(path, log))
    return result
