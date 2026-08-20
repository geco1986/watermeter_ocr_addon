"""Einstellungs-Speicher fuer alles, was frueher in der Supervisor-Add-on-
Konfiguration stand und jetzt stattdessen ueber die Konfiguration-Webseite
des Add-ons eingestellt wird.

Funktioniert nach demselben Muster wie tuning.py: Werte landen in einer JSON-
Datei in /data und werden live (ohne Add-on-Neustart) angewendet.
"""

import json
from pathlib import Path

# Schluessel, die ueber die Konfiguration-Webseite einstellbar sind.
SETTINGS_KEYS = (
    "camera_entity",
    "light_entity",
    "light_warmup",
    "ocr_provider",
    "ollama_url",
    "ollama_model",
    "ollama_timeout",
    "ollama_num_thread",
    "ollama_local_cpu_percent",
    "openai_api_key",
    "openai_model",
    "gemini_api_key",
    "gemini_model",
    "claude_api_key",
    "claude_model",
    "ocr_main_digits",
    "ocr_decimal_digits",
    "ocr_prompt",
    "plausibility_check",
    "max_increase",
    "hold_last_on_failure",
)

# Schluessel mit sensiblen Daten - werden in Logs/Statusantworten maskiert.
SECRET_KEYS = ("openai_api_key", "gemini_api_key", "claude_api_key")


def load(path: Path, log=None) -> dict:
    """Liest die gespeicherten Einstellungen. Leeres dict, wenn keine Datei existiert."""
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
        return {k: data[k] for k in SETTINGS_KEYS if k in data}
    except (OSError, json.JSONDecodeError) as exc:
        if log:
            log(f"WARNUNG: Einstellungen nicht lesbar ({exc})")
        return {}


def save(path: Path, values: dict, log=None) -> None:
    """Speichert die Einstellungen atomar (nur erlaubte Schluessel)."""
    # bestehende Werte laden und mit den neuen zusammenfuehren, damit ein
    # Speichern eines Teilformulars nicht die anderen Werte loescht
    current = load(path, log)
    current.update({k: values[k] for k in SETTINGS_KEYS if k in values})
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.json")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(current, fh)
    tmp.replace(path)
    if log:
        safe = {k: ("***" if k in SECRET_KEYS and v else v) for k, v in current.items()}
        log(f"Einstellungen gespeichert: {safe}")


def migrate_from_legacy(defaults: dict, legacy_opts: dict, path: Path, log=None) -> None:
    """Einmalige Migration: uebernimmt Werte aus einer alten Supervisor-
    Konfiguration (vor der Umstellung auf die Web-UI-Konfiguration) in die
    neue Einstellungsdatei, damit nichts verloren geht. Laeuft nur, wenn
    noch keine Einstellungsdatei existiert.
    """
    if path.exists():
        return
    migrated = {}
    for k in SETTINGS_KEYS:
        if k in legacy_opts and legacy_opts[k] != defaults.get(k):
            migrated[k] = legacy_opts[k]
    if migrated:
        save(path, migrated, log)
        if log:
            log(f"Einstellungen aus vorheriger Konfiguration uebernommen: "
                f"{list(migrated.keys())}")


def effective(defaults: dict, path: Path, log=None) -> dict:
    """Liefert die effektiven Einstellungen: Defaults, ueberschrieben von
    den gespeicherten Web-UI-Einstellungen."""
    result = {k: defaults[k] for k in SETTINGS_KEYS if k in defaults}
    result.update(load(path, log))
    return result
