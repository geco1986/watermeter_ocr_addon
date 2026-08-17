"""OCR ueber ausgelagerten Ollama-Vision-Server.

Uebernimmt die Logik des urspruenglichen Shell-Skripts: Bild als Base64 an
/api/generate schicken, JSON-Antwort mit raw_digits parsen, Modell danach
explizit aus dem RAM entladen (keep_alive-Handling).
"""

import base64
import json
import re

import requests


PROMPT_TEMPLATE = (
    "You are a precise OCR system for reading water meters. "
    "The meter has exactly {main} main digits (black/white) and exactly "
    "{decimal} decimal digits (red). You must read all {total} digits from "
    "left to right. ALWAYS and EXCLUSIVELY return the result as a valid JSON "
    "object with just one key called raw_digits. Replace the placeholder with "
    "the real value: {{ \"raw_digits\": \"{example}\" }} "
    "Respond only with the JSON code."
)


def read_digits_ollama(
    image_path,
    ollama_url: str,
    model: str,
    keep_alive: int,
    timeout: int,
    main_digits: int,
    decimal_digits: int,
    log,
    force_json: bool = True,
):
    """Schickt das Bild an Ollama und liefert das Ergebnis-dict.

    Rueckgabe wie beim alten Skript:
      {"raw_digits": "01260624"}            bei Erfolg
      {"raw_digits": null, "error": "..."}  bei Problemen
    Zusaetzlich "value" mit Dezimalpunkt, falls Nachkommastellen definiert.
    """
    total = main_digits + decimal_digits
    example = "0" * total

    with open(image_path, "rb") as fh:
        img_b64 = base64.b64encode(fh.read()).decode("ascii")

    prompt = PROMPT_TEMPLATE.format(
        total=total, main=main_digits, decimal=decimal_digits, example=example
    )

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "images": [img_b64],
        "options": {
            "temperature": 0,
            "num_predict": 50,
            "keep_alive": keep_alive,
        },
    }
    # format: json erzwingt sauberes JSON - gemma & Co. respektieren das (wie
    # im urspruenglich funktionierenden Skript). Kleine Modelle wie moondream
    # koennen damit Probleme haben; dann diese Option auf false setzen. Der
    # Parser unten hat zusaetzlich einen Ziffern-Fallback.
    if force_json:
        payload["format"] = "json"

    log(f"Sende Bild an Ollama ({model}) ...")
    try:
        resp = requests.post(ollama_url, json=payload, timeout=timeout)
    except requests.exceptions.Timeout:
        return {"raw_digits": None,
                "error": f"Ollama-Timeout nach {timeout}s (Modell zu langsam?)"}
    except requests.exceptions.RequestException as exc:
        return {"raw_digits": None,
                "error": f"Ollama nicht erreichbar: {exc}"}

    # Modell explizit aus dem RAM entladen (wie im alten Skript)
    if keep_alive == 0:
        try:
            requests.post(
                ollama_url,
                json={"model": model, "keep_alive": 0},
                timeout=10,
            )
        except requests.exceptions.RequestException:
            pass  # nicht kritisch

    if resp.status_code != 200:
        return {"raw_digits": None,
                "error": f"Ollama HTTP {resp.status_code}: {resp.text[:200]}"}

    # Ollama verpackt die eigentliche Antwort in .response (als String)
    try:
        outer = resp.json()
        model_response = outer.get("response", "")
    except json.JSONDecodeError:
        return {"raw_digits": None, "error": "Ollama-Antwort kein JSON"}

    log(f"Ollama roh: {model_response!r}")

    # Die response ist selbst wieder ein JSON-String mit raw_digits
    digits = None
    try:
        inner = json.loads(model_response)
        raw = inner.get("raw_digits")
        if raw is not None:
            digits = re.sub(r"[^0-9]", "", str(raw))
    except (json.JSONDecodeError, AttributeError):
        # Fallback: einfach alle Ziffern aus der Rohantwort ziehen
        digits = re.sub(r"[^0-9]", "", model_response)

    if not digits:
        return {"raw_digits": None,
                "error": f"keine Ziffern in Antwort: {model_response!r}"}

    if len(digits) != total:
        return {
            "raw_digits": None,
            "error": f"erwartet {total} Ziffern, erkannt {len(digits)}: '{digits}'",
        }

    result = {"raw_digits": digits}
    if decimal_digits > 0:
        whole = digits[:main_digits]
        frac = digits[main_digits:]
        result["value"] = float(f"{int(whole)}.{frac}")
    else:
        result["value"] = float(int(digits))

    return result
