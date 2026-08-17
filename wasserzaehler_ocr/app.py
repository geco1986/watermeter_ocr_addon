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
import ollama_ocr
import plausibility
import tuning

OPTIONS_PATH = Path("/data/options.json")

DEFAULTS = {
    "camera_entity": "camera.esp32_cam_esp32_kamera",
    "light_entity": "light.esp32_cam_kamera_blitzlicht",
    "light_warmup": 10,
    "src_path": "/config/watermeter/watermeter_image.jpg",
    "dst_path": "/config/watermeter/watermeter_rotated.jpg",
    "save_source": True,
    "rotate_angle": 53,
    "fill_color": "black",
    "crop_top": 400,
    "crop_bottom": 340,
    "crop_left": 75,
    "crop_right": 200,
    "jpeg_quality": 92,
    "jpeg_subsampling": 0,
    "ollama_url": "http://192.168.3.3:11434/api/generate",
    "ollama_model": "gemma4:e2b",
    "ollama_keep_alive": 0,
    "ollama_timeout": 120,
    "ollama_force_json": True,
    "ocr_main_digits": 5,
    "ocr_decimal_digits": 3,
    "plausibility_check": True,
    "max_increase": 5.0,
    "allow_equal": True,
    "reject_implausible": True,
    "hold_last_on_failure": True,
    "last_value_path": "/config/watermeter/last_value.json",
    "tuning_path": "/config/watermeter/tuning.json",
}


def load_options():
    opts = dict(DEFAULTS)
    if OPTIONS_PATH.exists():
        try:
            with OPTIONS_PATH.open(encoding="utf-8") as fh:
                opts.update(json.load(fh))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"WARNUNG: options.json nicht lesbar ({exc}), nutze Defaults",
                  file=sys.stderr)
    return opts


OPTS = load_options()

# Logging direkt nach stdout - Home Assistant zeigt das im Add-on-Protokoll an.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
_LOGGER = logging.getLogger("wasserzaehler")


def log(msg: str) -> None:
    """Schreibt eine Zeile ins Add-on-Protokoll (stdout)."""
    _LOGGER.info(msg)


app = Flask(__name__)


@app.route("/process", methods=["GET"])
def process():
    log("--- Start /process ---")
    try:
        # 1. Bild von der Kamera holen
        # Wenn save_source aktiv ist, legen wir das Rohbild unter src_path ab,
        # sonst direkt als Arbeitsdatei.
        raw_target = Path(OPTS["src_path"]) if OPTS.get("save_source", True) \
            else Path(OPTS["dst_path"]).with_suffix(".raw.jpg")

        light_entity = OPTS.get("light_entity", "")
        warmup = int(OPTS.get("light_warmup", 10))

        try:
            # Lampe an, kurz warten bis sie voll ausgeleuchtet ist
            if light_entity:
                fetch_image.set_light(light_entity, True,
                                      timeout=15, log=log)
                if warmup > 0:
                    log(f"Warte {warmup}s auf Ausleuchtung ...")
                    time.sleep(warmup)

            # Bild holen
            fetch_image.fetch_camera_image(
                camera_entity=OPTS["camera_entity"],
                dst_path=raw_target,
                timeout=int(OPTS["ollama_timeout"]),
                log=log,
            )
        finally:
            # Lampe immer wieder aus - auch wenn der Abruf fehlschlug
            if light_entity:
                fetch_image.set_light(light_entity, False,
                                      timeout=15, log=log)

        # 2. Rotation + Zuschnitt (Rohbild -> dst_path)
        # Effektive Werte: Add-on-Optionen, ueberschrieben von Tuner-Werten
        eff = tuning.effective(OPTS, Path(OPTS["tuning_path"]), log)
        rotate.rotate_and_crop(
            src_path=raw_target,
            dst_path=Path(OPTS["dst_path"]),
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
        result = ollama_ocr.read_digits_ollama(
            image_path=OPTS["dst_path"],
            ollama_url=OPTS["ollama_url"],
            model=OPTS["ollama_model"],
            keep_alive=int(OPTS["ollama_keep_alive"]),
            timeout=int(OPTS["ollama_timeout"]),
            main_digits=int(OPTS["ocr_main_digits"]),
            decimal_digits=int(OPTS["ocr_decimal_digits"]),
            log=log,
            force_json=bool(OPTS.get("ollama_force_json", True)),
        )

        log(f"OCR-Ergebnis: {result}")

        # 4. Zustand laden (letzter Wert, Zeit, Fehlerzaehler)
        state_path = Path(OPTS["last_value_path"])
        state = plausibility.load_state(state_path, log)
        last_value = state["value"]
        last_timestamp = state["timestamp"]
        error_count = state["error_count"]

        now = time.time()
        ocr_failed = result.get("raw_digits") is None

        # 5. Plausibilitaetspruefung (nur wenn OCR ueberhaupt Ziffern lieferte)
        plausible = True
        reason = None
        if not ocr_failed and OPTS.get("plausibility_check", True):
            value = result["value"]
            plausible, reason = plausibility.check(
                value=value,
                last_value=last_value,
                max_increase=float(OPTS["max_increase"]),
                allow_equal=bool(OPTS["allow_equal"]),
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
        hold = bool(OPTS.get("hold_last_on_failure", True))

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
        # Status 200, solange ein gueltiger (frischer ODER gehaltener) Wert
        # vorliegt. Nur ganz ohne Wert (erster Lauf gescheitert) -> 422.
        status = 200 if result.get("value") is not None else 422
        return jsonify(result), status

    except FileNotFoundError as exc:
        log(f"FEHLER: {exc}")
        return jsonify({"raw_digits": None, "error": str(exc)}), 404
    except ValueError as exc:
        log(f"FEHLER: {exc}")
        return jsonify({"raw_digits": None, "error": str(exc)}), 400
    except Exception:
        tb = traceback.format_exc()
        log("UNBEHANDELTER FEHLER:\n" + tb)
        return jsonify({"raw_digits": None, "error": "interner Fehler"}), 500


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

    state_path = Path(OPTS["last_value_path"])
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
    dst = Path(OPTS["dst_path"])
    if not dst.exists():
        return "kein Ergebnisbild vorhanden", 404
    return send_file(str(dst), mimetype="image/jpeg")


@app.route("/tuner", methods=["GET"])
def tuner_page():
    """Liefert die Tuner-Webseite."""
    here = Path(__file__).parent / "tuner.html"
    return here.read_text(encoding="utf-8"), 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/tuner/current", methods=["GET"])
def tuner_current():
    """Aktuelle effektive Rotations-/Zuschnittwerte (fuer das Formular)."""
    eff = tuning.effective(OPTS, Path(OPTS["tuning_path"]), log)
    # Sicherstellen, dass alle erwarteten Schluessel da sind
    for k in tuning.TUNABLE_KEYS:
        eff.setdefault(k, OPTS.get(k))
    return jsonify(eff)


@app.route("/tuner/fetch_source", methods=["POST"])
def tuner_fetch_source():
    """Holt ein frisches Kamerabild (mit Lampe) fuer den Tuner."""
    raw_target = Path(OPTS["src_path"])
    light_entity = OPTS.get("light_entity", "")
    warmup = int(OPTS.get("light_warmup", 10))
    try:
        try:
            if light_entity:
                fetch_image.set_light(light_entity, True, timeout=15, log=log)
                if warmup > 0:
                    time.sleep(warmup)
            fetch_image.fetch_camera_image(
                camera_entity=OPTS["camera_entity"],
                dst_path=raw_target,
                timeout=int(OPTS["ollama_timeout"]),
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
    src = Path(OPTS["src_path"])
    if not src.exists():
        return "kein Quellbild vorhanden", 404
    return send_file(str(src), mimetype="image/jpeg")


@app.route("/tuner/preview.jpg", methods=["GET"])
def tuner_preview():
    """Rendert eine Vorschau mit den uebergebenen Werten."""
    src = Path(OPTS["src_path"])
    try:
        img = rotate.render(
            src_path=src,
            angle=float(request.args.get("rotate_angle", OPTS["rotate_angle"])),
            fill_color=request.args.get("fill_color", OPTS["fill_color"]),
            crop_top=int(request.args.get("crop_top", OPTS["crop_top"])),
            crop_bottom=int(request.args.get("crop_bottom", OPTS["crop_bottom"])),
            crop_left=int(request.args.get("crop_left", OPTS["crop_left"])),
            crop_right=int(request.args.get("crop_right", OPTS["crop_right"])),
            log=None,
        )
        quality = int(request.args.get("jpeg_quality", OPTS["jpeg_quality"]))
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
    data = request.get_json(silent=True) or {}
    try:
        tuning.save(Path(OPTS["tuning_path"]), data, log)
        return jsonify({"ok": True})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/tuner/reset", methods=["POST"])
def tuner_reset():
    """Loescht die getunten Werte (zurueck zur Add-on-Konfig)."""
    tuning.clear(Path(OPTS["tuning_path"]), log)
    return jsonify({"ok": True})


if __name__ == "__main__":
    log(f"Add-on gestartet, Python {sys.version.split()[0]}")
    safe_opts = {k: v for k, v in OPTS.items()}
    log(f"Optionen: {safe_opts}")

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
