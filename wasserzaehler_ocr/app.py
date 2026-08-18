"""Wasserzaehler Rotate & OCR - Home-Assistant-Add-on (Ollama-Variante).

Kette pro /process-Aufruf:
  1. Bild von der HA-Kamera-Entitaet holen (camera_proxy)
  2. Rotieren + Zuschneiden (Logik aus cam_rotate.py)
  3. Zugeschnittenes Bild an ausgelagerten Ollama-Vision-Server schicken
  4. Ergebnis als JSON an Home Assistant zurueckgeben

Endpunkte:
  GET /process  -> ganze Kette; liefert JSON
  GET /health   -> {"status": "ok"}
"""

import json
import io
import logging
import sys
import time
import traceback
from pathlib import Path

from flask import Flask, jsonify, request, send_file

import fetch_image
import rotate
import ocr_providers
import plausibility
import tuning
import settings
import sysinfo

OPTIONS_PATH = Path("/data/options.json")
SETTINGS_PATH = Path("/data/settings.json")

# Interne, feste Pfade - nicht ueber die Konfiguration einstellbar.
PATHS = {
    "src_path": "/data/watermeter_image.jpg",
    "dst_path": "/data/watermeter_rotated.jpg",
    "last_value_path": "/data/last_value.json",
    "tuning_path": "/data/tuning.json",
}

# Werte, die weder ueber die Supervisor-Konfiguration noch ueber die
# Web-UI-Einstellungsseite veraendert werden (interne Konstanten).
INTERNAL_DEFAULTS = {
    "save_source": True,
    "rotate_angle": 53,
    "fill_color": "black",
    "crop_top": 400,
    "crop_bottom": 340,
    "crop_left": 75,
    "crop_right": 200,
    "jpeg_quality": 92,
    "jpeg_subsampling": 0,
    "ollama_keep_alive": 0,
    "ollama_force_json": True,
    "allow_equal": True,
    "reject_implausible": True,
}

# Defaults fuer alles, was ueber die Konfiguration-Webseite einstellbar ist
# (settings.py SETTINGS_KEYS). Diese Werte gelten, solange settings.json
# noch keinen eigenen Wert dafuer hat.
SETTINGS_DEFAULTS = {
    "camera_entity": "",
    "light_entity": "",
    "light_warmup": 10,
    "ocr_provider": "ollama_remote",
    "ollama_url": "",
    "ollama_model": "moondream",
    "ollama_timeout": 120,
    "openai_api_key": "",
    "openai_model": "gpt-4o-mini",
    "gemini_api_key": "",
    "gemini_model": "gemini-2.0-flash",
    "claude_api_key": "",
    "claude_model": "claude-3-5-sonnet-20241022",
    "ocr_main_digits": 5,
    "ocr_decimal_digits": 3,
    "plausibility_check": True,
    "max_increase": 5.0,
    "hold_last_on_failure": True,
}

DEFAULTS = {**PATHS, **INTERNAL_DEFAULTS, **SETTINGS_DEFAULTS}


def load_options():
    """Liest die (heute meist leere) Supervisor-Konfiguration - dient nur
    noch als Kompatibilitaets-/Migrationsquelle fuer sehr alte Installationen."""
    opts = {}
    if OPTIONS_PATH.exists():
        try:
            with OPTIONS_PATH.open(encoding="utf-8") as fh:
                opts = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"WARNUNG: options.json nicht lesbar ({exc})", file=sys.stderr)
    return opts


LEGACY_OPTS = load_options()


def get_config(log=None):
    """Liefert die aktuell gueltige, vollstaendige Konfiguration.

    Wird pro Request neu berechnet, damit Aenderungen ueber die
    Konfiguration-Webseite sofort greifen - ohne Add-on-Neustart.
    """
    cfg = dict(DEFAULTS)
    cfg.update(settings.effective(SETTINGS_DEFAULTS, SETTINGS_PATH, log))
    return cfg

# Logging direkt nach stdout - Home Assistant zeigt das im Add-on-Protokoll an.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
_LOGGER = logging.getLogger("wasserzaehler")

# Ringpuffer der letzten Log-Zeilen (fuer die Anzeige auf der Uebersichtsseite)
from collections import deque
from datetime import datetime
_LOG_BUFFER = deque(maxlen=60)

# Live-Prozessstatus, den die Uebersichtsseite pollt
PROCESS_STATE = {
    "running": False,
    "phase": "idle",          # idle | fetch | rotate | ocr | plausibility | done | error
    "phase_text": "bereit",
    "started_at": None,
    "finished_at": None,
    "last_result": None,      # letztes /process-Ergebnis-dict
}


def log(msg: str) -> None:
    """Schreibt eine Zeile ins Add-on-Protokoll (stdout) und in den Puffer."""
    _LOGGER.info(msg)
    stamp = datetime.now().strftime("%H:%M:%S")
    _LOG_BUFFER.append(f"{stamp}  {msg}")


# Einmalige Migration: Werte aus einer alten Supervisor-Konfiguration (vor
# der Umstellung auf die Web-UI-Konfiguration) in die neuen Einstellungen
# uebernehmen, falls noch keine settings.json existiert.
settings.migrate_from_legacy(SETTINGS_DEFAULTS, LEGACY_OPTS, SETTINGS_PATH, log=log)


def set_phase(phase: str, text: str) -> None:
    """Aktualisiert den Live-Prozessstatus."""
    PROCESS_STATE["phase"] = phase
    PROCESS_STATE["phase_text"] = text
    log(f"[Phase] {text}")


app = Flask(__name__)


@app.route("/process", methods=["GET"])
def process():
    cfg = get_config(log)
    log("--- Start /process ---")
    PROCESS_STATE["running"] = True
    PROCESS_STATE["started_at"] = time.time()
    PROCESS_STATE["finished_at"] = None
    try:
        # 1. Bild von der Kamera holen
        # Wenn save_source aktiv ist, legen wir das Rohbild unter src_path ab,
        # sonst direkt als Arbeitsdatei.
        raw_target = Path(cfg["src_path"]) if cfg.get("save_source", True) \
            else Path(cfg["dst_path"]).with_suffix(".raw.jpg")

        light_entity = cfg.get("light_entity", "")
        warmup = int(cfg.get("light_warmup", 10))

        try:
            # Lampe an, kurz warten bis sie voll ausgeleuchtet ist
            if light_entity:
                set_phase("fetch", "Lampe an, warte auf Ausleuchtung …")
                fetch_image.set_light(light_entity, True,
                                      timeout=15, log=log)
                if warmup > 0:
                    time.sleep(warmup)
            else:
                set_phase("fetch", "Hole Bild von der Kamera …")

            # Bild holen
            set_phase("fetch", "Hole Bild von der Kamera …")
            fetch_image.fetch_camera_image(
                camera_entity=cfg["camera_entity"],
                dst_path=raw_target,
                timeout=int(cfg["ollama_timeout"]),
                log=log,
            )
        finally:
            # Lampe immer wieder aus - auch wenn der Abruf fehlschlug
            if light_entity:
                fetch_image.set_light(light_entity, False,
                                      timeout=15, log=log)

        # 2. Rotation + Zuschnitt (Rohbild -> dst_path)
        # Effektive Werte: Add-on-Optionen, ueberschrieben von Tuner-Werten
        set_phase("rotate", "Rotiere und schneide zu …")
        eff = tuning.effective(cfg, Path(cfg["tuning_path"]), log)
        rotate.rotate_and_crop(
            src_path=raw_target,
            dst_path=Path(cfg["dst_path"]),
            angle=float(eff["rotate_angle"]),
            fill_color=eff["fill_color"],
            crop_top=int(eff["crop_top"]),
            crop_bottom=int(eff["crop_bottom"]),
            crop_left=int(eff["crop_left"]),
            crop_right=int(eff["crop_right"]),
            quality=int(eff["jpeg_quality"]),
            subsampling=int(eff["jpeg_subsampling"]),
            log=log,
        )

        # 3. OCR ueber ausgelagerten Ollama-Server
        provider = cfg.get("ocr_provider", "ollama_remote")
        # Effektive Optionen fuer den OCR-Aufruf. Bei lokalem Ollama zeigt die
        # URL immer auf den Server im Container selbst.
        ocr_opts = dict(cfg)
        if provider == "ollama_local":
            ocr_opts["ollama_url"] = "http://127.0.0.1:11434/api/generate"

        model_label = {
            "tesseract": "Tesseract (lokal, kein KI-Modell)",
            "ollama_local": f"Ollama lokal: {cfg['ollama_model']}",
            "ollama_remote": f"Ollama: {cfg['ollama_model']}",
            "openai": f"OpenAI: {cfg['openai_model']}",
            "gemini": f"Gemini: {cfg['gemini_model']}",
            "claude": f"Claude: {cfg['claude_model']}",
        }.get(provider, provider)
        set_phase("ocr", f"OCR läuft ({model_label}) …")

        result = ocr_providers.read_digits(
            provider=provider,
            image_path=cfg["dst_path"],
            opts=ocr_opts,
            main_digits=int(cfg["ocr_main_digits"]),
            decimal_digits=int(cfg["ocr_decimal_digits"]),
            timeout=int(cfg["ollama_timeout"]),
            log=log,
        )

        log(f"OCR-Ergebnis: {result}")
        set_phase("plausibility", "Prüfe Plausibilität …")

        # 4. Zustand laden (letzter Wert, Zeit, Fehlerzaehler)
        state_path = Path(cfg["last_value_path"])
        state = plausibility.load_state(state_path, log)
        last_value = state["value"]
        last_timestamp = state["timestamp"]
        error_count = state["error_count"]

        now = time.time()
        ocr_failed = result.get("raw_digits") is None

        # 5. Plausibilitaetspruefung (nur wenn OCR ueberhaupt Ziffern lieferte)
        plausible = True
        reason = None
        if not ocr_failed and cfg.get("plausibility_check", True):
            value = result["value"]
            plausible, reason = plausibility.check(
                value=value,
                last_value=last_value,
                max_increase=float(cfg["max_increase"]),
                allow_equal=bool(cfg["allow_equal"]),
                log=log,
            )
            result["plausible"] = plausible
            result["last_value"] = last_value
            if not plausible:
                log(f"UNPLAUSIBEL: {reason}")
                result["error"] = reason
                result["rejected"] = True

        # Ein frischer, gueltiger Wert liegt vor, wenn OCR erfolgreich UND plausibel war
        valid = (not ocr_failed) and plausible
        hold = bool(cfg.get("hold_last_on_failure", True))

        # 6. Durchflussrate + Status + Fehlerzaehler + Zustand aktualisieren
        if valid:
            value = result["value"]
            rate = plausibility.flow_rate_l_min(
                value=value, last_value=last_value,
                last_timestamp=last_timestamp, now=now, log=log,
            )
            result["flow_rate_l_min"] = rate
            result["status"] = "ok"
            result["error_count"] = 0
            result["held"] = False
            # neuen guten Zustand speichern
            plausibility.save_state(state_path, {
                "value": value, "timestamp": now, "error_count": 0,
            }, log)
        else:
            # Kein frischer gueltiger Wert (OCR fehlgeschlagen ODER unplausibel).
            error_count += 1
            result["flow_rate_l_min"] = 0.0
            result["error_count"] = error_count
            result["status"] = result.get("error", "Fehler")

            if hold and last_value is not None:
                # Letzten guten Wert weiter als gueltigen Zaehlerstand liefern,
                # damit der Sensor nicht auf 'unbekannt' faellt. Die frische
                # OCR (raw_digits) bleibt null - sie ist ja fehlgeschlagen.
                result["value"] = last_value
                result["held"] = True
                log(f"Halte letzten guten Wert: {last_value}")
            else:
                # Kein Vorwert vorhanden (z. B. erster Lauf) - nichts zu halten.
                result["value"] = None
                result["held"] = False

            # Zustand: letzten guten Wert/Zeit behalten, nur Fehlerzaehler hoch
            plausibility.save_state(state_path, {
                "value": last_value, "timestamp": last_timestamp,
                "error_count": error_count,
            }, log)

        log(f"Ergebnis: {result}")
        # Zeitpunkt der letzten erfolgreichen Ablesung merken
        if result.get("raw_digits") is not None and not result.get("held"):
            result["last_read_at"] = now
        set_phase("done", "Fertig.")
        PROCESS_STATE["last_result"] = result
        # Status 200, solange ein gueltiger (frischer ODER gehaltener) Wert
        # vorliegt. Nur ganz ohne Wert (erster Lauf gescheitert) -> 422.
        status = 200 if result.get("value") is not None else 422
        return jsonify(result), status

    except FileNotFoundError as exc:
        log(f"FEHLER: {exc}")
        set_phase("error", f"Fehler: {exc}")
        err = {"raw_digits": None, "value": None, "error": str(exc),
               "status": str(exc)}
        PROCESS_STATE["last_result"] = err
        return jsonify(err), 404
    except ValueError as exc:
        log(f"FEHLER: {exc}")
        set_phase("error", f"Fehler: {exc}")
        err = {"raw_digits": None, "value": None, "error": str(exc),
               "status": str(exc)}
        PROCESS_STATE["last_result"] = err
        return jsonify(err), 400
    except Exception:
        tb = traceback.format_exc()
        log("UNBEHANDELTER FEHLER:\n" + tb)
        set_phase("error", "interner Fehler")
        err = {"raw_digits": None, "value": None, "error": "interner Fehler",
               "status": "interner Fehler"}
        PROCESS_STATE["last_result"] = err
        return jsonify(err), 500
    finally:
        PROCESS_STATE["running"] = False
        PROCESS_STATE["finished_at"] = time.time()


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/set_value", methods=["GET", "POST"])
def set_value():
    """Setzt den gespeicherten Zaehlerstand manuell (Korrektur).

    Nuetzlich, wenn ein legitimer grosser Sprung von der Plausibilitaets-
    pruefung blockiert wird. Der Zeitstempel wird auf jetzt gesetzt, damit
    die Durchflussberechnung frisch ab diesem Moment startet. Der
    Fehlerzaehler wird zurueckgesetzt.

    Aufruf: /set_value?value=1265.500  (oder POST mit JSON {"value": 1265.5})
    """
    cfg = get_config(log)
    # Wert aus Query-Parameter oder JSON-Body holen
    raw = request.args.get("value")
    if raw is None and request.is_json:
        raw = (request.get_json(silent=True) or {}).get("value")

    if raw is None:
        return jsonify({"ok": False, "error": "kein 'value' angegeben"}), 400

    try:
        value = float(raw)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": f"'{raw}' ist keine Zahl"}), 400

    state_path = Path(cfg["last_value_path"])
    now = time.time()
    plausibility.save_state(state_path, {
        "value": value, "timestamp": now, "error_count": 0,
    }, log)
    log(f"Wert manuell gesetzt: {value} (Zeitstempel neu, Fehlerzaehler 0)")

    return jsonify({"ok": True, "value": value})


@app.route("/", methods=["GET"])
def index():
    """Startseite (Landing-Page) mit den beiden Aktionen."""
    here = Path(__file__).parent / "index.html"
    return here.read_text(encoding="utf-8"), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/tuner/dst.jpg", methods=["GET"])
def tuner_dst():
    """Liefert das zuletzt zugeschnittene Ergebnisbild (fuer die Landing-Page)."""
    cfg = get_config(log)
    dst = Path(cfg["dst_path"])
    if not dst.exists():
        return "kein Ergebnisbild vorhanden", 404
    return send_file(str(dst), mimetype="image/jpeg")


@app.route("/status", methods=["GET"])
def status_endpoint():
    """Live-Prozessstatus + letztes Ergebnis + Zustand fuer die Uebersicht."""
    cfg = get_config(log)
    state = plausibility.load_state(Path(cfg["last_value_path"]), log)
    running = PROCESS_STATE["running"]
    elapsed = None
    if PROCESS_STATE["started_at"]:
        end = PROCESS_STATE["finished_at"] or time.time()
        elapsed = round(end - PROCESS_STATE["started_at"], 1)
    return jsonify({
        "running": running,
        "phase": PROCESS_STATE["phase"],
        "phase_text": PROCESS_STATE["phase_text"],
        "elapsed_s": elapsed,
        "last_result": PROCESS_STATE["last_result"],
        "stored_value": state["value"],
        "stored_timestamp": state["timestamp"],
        "error_count": state["error_count"],
        "provider": cfg.get("ocr_provider", "ollama_remote"),
        "now": time.time(),
    })


@app.route("/logs", methods=["GET"])
def logs_endpoint():
    """Die letzten Log-Zeilen (fuer die Anzeige auf der Uebersichtsseite)."""
    return jsonify({"lines": list(_LOG_BUFFER)})


@app.route("/ollama_status", methods=["GET"])
def ollama_status():
    """Prueft den aktiven OCR-Anbieter (Ollama erreichbar / Cloud-Key gesetzt)."""
    cfg = get_config(log)
    import urllib.request

    provider = cfg.get("ocr_provider", "ollama_remote")

    if provider == "tesseract":
        try:
            import pytesseract
            version = str(pytesseract.get_tesseract_version())
            return jsonify({"provider": provider, "reachable": True,
                            "model": f"Tesseract {version}", "model_present": True})
        except Exception as exc:  # noqa: BLE001
            return jsonify({"provider": provider, "reachable": False,
                            "model": "Tesseract", "model_present": False,
                            "error": str(exc)})

    if provider in ("ollama_local", "ollama_remote"):
        base = cfg["ollama_url"].replace("/api/generate", "")
        if provider == "ollama_local":
            base = "http://127.0.0.1:11434"
        tags_url = f"{base}/api/tags"
        model = cfg["ollama_model"]
        try:
            with urllib.request.urlopen(tags_url, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            names = [m.get("name", "") for m in data.get("models", [])]
            present = any(n == model or n.split(":")[0] == model.split(":")[0]
                          for n in names)
            return jsonify({"provider": provider, "reachable": True,
                            "model": model, "model_present": present,
                            "available_models": names})
        except Exception as exc:  # noqa: BLE001
            return jsonify({"provider": provider, "reachable": False,
                            "model": model, "model_present": False,
                            "error": str(exc)})

    # Cloud-Anbieter: wir pruefen nur, ob ein Schluessel gesetzt ist
    key_map = {
        "openai": ("openai_api_key", "openai_model"),
        "gemini": ("gemini_api_key", "gemini_model"),
        "claude": ("claude_api_key", "claude_model"),
    }
    keyname, modelname = key_map.get(provider, (None, None))
    has_key = bool(cfg.get(keyname, "")) if keyname else False
    return jsonify({
        "provider": provider,
        "reachable": has_key,
        "model": cfg.get(modelname, "") if modelname else "",
        "model_present": has_key,
        "error": None if has_key else "kein API-Schlüssel gesetzt",
    })


@app.route("/settings", methods=["GET"])
def settings_get():
    """Aktuelle Einstellungen für das Konfigurationsformular.

    API-Schlüssel werden nicht im Klartext zurückgegeben - nur ob einer
    gesetzt ist (has_*_key). Das Formular zeigt dann ein Platzhalter-Feld;
    ein leeres Feld beim Speichern lässt den bestehenden Schlüssel unangetastet.
    """
    cfg = get_config(log)
    result = {k: cfg.get(k) for k in settings.SETTINGS_KEYS}
    for key in settings.SECRET_KEYS:
        result[f"has_{key}"] = bool(result.get(key))
        result[key] = ""  # nie den echten Schlüssel ausliefern
    return jsonify(result)


@app.route("/settings", methods=["POST"])
def settings_post():
    """Speichert Einstellungen aus dem Konfigurationsformular.

    Leere Felder bei API-Schlüsseln überschreiben einen bereits gesetzten
    Schlüssel NICHT (so muss man ihn nicht bei jeder Änderung neu eingeben).
    """
    data = request.get_json(silent=True) or {}
    current = settings.load(SETTINGS_PATH, log)

    to_save = {}
    for key in settings.SETTINGS_KEYS:
        if key not in data:
            continue
        value = data[key]
        if key in settings.SECRET_KEYS and (value is None or value == ""):
            continue  # leeres Schlüsselfeld -> bestehenden Wert behalten
        to_save[key] = value

    try:
        settings.save(SETTINGS_PATH, to_save, log)
        return jsonify({"ok": True})
    except Exception as exc:  # noqa: BLE001
        log(f"FEHLER beim Speichern der Einstellungen: {exc}")
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/system_info", methods=["GET"])
def system_info():
    """RAM-Info und Modellempfehlung für die Konfigurationsseite."""
    return jsonify(sysinfo.get_recommendation(log))


@app.route("/config", methods=["GET"])
def config_page():
    """Liefert die Konfigurations-Webseite."""
    here = Path(__file__).parent / "config.html"
    return here.read_text(encoding="utf-8"), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/tuner", methods=["GET"])
def tuner_page():
    """Liefert die Tuner-Webseite."""
    here = Path(__file__).parent / "tuner.html"
    return here.read_text(encoding="utf-8"), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/tuner/current", methods=["GET"])
def tuner_current():
    """Aktuelle effektive Rotations-/Zuschnittwerte (fuer das Formular)."""
    cfg = get_config(log)
    eff = tuning.effective(cfg, Path(cfg["tuning_path"]), log)
    # Sicherstellen, dass alle erwarteten Schluessel da sind
    for k in tuning.TUNABLE_KEYS:
        eff.setdefault(k, cfg.get(k))
    return jsonify(eff)


@app.route("/tuner/fetch_source", methods=["POST"])
def tuner_fetch_source():
    """Holt ein frisches Kamerabild (mit Lampe) fuer den Tuner."""
    cfg = get_config(log)
    raw_target = Path(cfg["src_path"])
    light_entity = cfg.get("light_entity", "")
    warmup = int(cfg.get("light_warmup", 10))
    try:
        try:
            if light_entity:
                fetch_image.set_light(light_entity, True, timeout=15, log=log)
                if warmup > 0:
                    time.sleep(warmup)
            fetch_image.fetch_camera_image(
                camera_entity=cfg["camera_entity"],
                dst_path=raw_target,
                timeout=int(cfg["ollama_timeout"]),
                log=log,
            )
        finally:
            if light_entity:
                fetch_image.set_light(light_entity, False, timeout=15, log=log)
        return jsonify({"ok": True})
    except Exception as exc:  # noqa: BLE001
        log(f"Tuner-Bildabruf fehlgeschlagen: {exc}")
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/tuner/source.jpg", methods=["GET"])
def tuner_source():
    """Liefert das aktuelle Quellbild."""
    cfg = get_config(log)
    src = Path(cfg["src_path"])
    if not src.exists():
        return "kein Quellbild vorhanden", 404
    return send_file(str(src), mimetype="image/jpeg")


@app.route("/tuner/preview.jpg", methods=["GET"])
def tuner_preview():
    """Rendert eine Vorschau mit den uebergebenen Werten."""
    cfg = get_config(log)
    src = Path(cfg["src_path"])
    try:
        img = rotate.render(
            src_path=src,
            angle=float(request.args.get("rotate_angle", cfg["rotate_angle"])),
            fill_color=request.args.get("fill_color", cfg["fill_color"]),
            crop_top=int(request.args.get("crop_top", cfg["crop_top"])),
            crop_bottom=int(request.args.get("crop_bottom", cfg["crop_bottom"])),
            crop_left=int(request.args.get("crop_left", cfg["crop_left"])),
            crop_right=int(request.args.get("crop_right", cfg["crop_right"])),
            log=None,
        )
        quality = int(request.args.get("jpeg_quality", cfg["jpeg_quality"]))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality)
        buf.seek(0)
        return send_file(buf, mimetype="image/jpeg")
    except FileNotFoundError:
        return "kein Quellbild", 404
    except ValueError as exc:
        return str(exc), 422


@app.route("/tuner/save", methods=["POST"])
def tuner_save():
    """Speichert die getunten Werte (ueberschreiben die Add-on-Konfig)."""
    cfg = get_config(log)
    data = request.get_json(silent=True) or {}
    try:
        tuning.save(Path(cfg["tuning_path"]), data, log)
        return jsonify({"ok": True})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/tuner/reset", methods=["POST"])
def tuner_reset():
    """Loescht die getunten Werte (zurueck zur Add-on-Konfig)."""
    cfg = get_config(log)
    tuning.clear(Path(cfg["tuning_path"]), log)
    return jsonify({"ok": True})


if __name__ == "__main__":
    log(f"Add-on gestartet, Python {sys.version.split()[0]}")
    startup_cfg = get_config(log)
    safe_cfg = {k: ("***" if k in settings.SECRET_KEYS and v else v)
                for k, v in startup_cfg.items()}
    log(f"Konfiguration: {safe_cfg}")

    # Die App lauscht auf zwei Ports:
    #  - 5000: HTTP-API (wird von der Integration / REST-Sensor genutzt)
    #  - 8099: Ingress (der "Benutzeroberfläche öffnen"-Button in HA)
    # Port 8099 laeuft in einem Thread, 5000 im Hauptthread.
    from threading import Thread
    from werkzeug.serving import make_server

    ingress_srv = make_server("0.0.0.0", 8099, app, threaded=True)
    Thread(target=ingress_srv.serve_forever, daemon=True).start()
    log("Ingress-Server auf Port 8099 gestartet")

    api_srv = make_server("0.0.0.0", 5000, app, threaded=True)
    log("API-Server auf Port 5000 gestartet")
    api_srv.serve_forever()
