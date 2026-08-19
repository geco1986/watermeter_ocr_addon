"""OCR-Anbieter fuer die Wasserzaehler-Erkennung.

Kapselt verschiedene Vision-Backends hinter einer einheitlichen Funktion
read_digits(). Unterstuetzt:
  - ollama   : lokaler oder externer Ollama-Server (/api/generate)
  - openai   : OpenAI Vision (Chat Completions, z. B. gpt-4o / gpt-4o-mini)
  - gemini   : Google Gemini (generateContent)
  - claude   : Anthropic Claude (messages)

Alle liefern dasselbe Ergebnis-dict:
  {"raw_digits": "01260624", "value": 1260.624}     bei Erfolg
  {"raw_digits": None, "error": "..."}               bei Problemen
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


def _build_prompt(main_digits, decimal_digits):
    total = main_digits + decimal_digits
    return PROMPT_TEMPLATE.format(
        total=total, main=main_digits, decimal=decimal_digits,
        example="0" * total,
    )


def _b64(image_path):
    with open(image_path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("ascii")


def _finalize(text, main_digits, decimal_digits, log):
    """Extrahiert die Ziffern aus einer Modellantwort und baut das Ergebnis."""
    total = main_digits + decimal_digits
    log(f"Roh-Antwort: {text!r}")

    digits = None
    # Erst versuchen, JSON mit raw_digits zu lesen
    try:
        # evtl. ist die Antwort in ```json ... ``` gewickelt
        cleaned = re.sub(r"```[a-zA-Z]*", "", text).replace("```", "").strip()
        inner = json.loads(cleaned)
        raw = inner.get("raw_digits")
        if raw is not None:
            digits = re.sub(r"[^0-9]", "", str(raw))
    except (json.JSONDecodeError, AttributeError, TypeError):
        digits = re.sub(r"[^0-9]", "", text or "")

    if not digits:
        return {"raw_digits": None, "error": f"keine Ziffern in Antwort: {text!r}"}

    if len(digits) != total:
        return {"raw_digits": None,
                "error": f"erwartet {total} Ziffern, erkannt {len(digits)}: '{digits}'"}

    result = {"raw_digits": digits}
    if decimal_digits > 0:
        result["value"] = float(f"{int(digits[:main_digits])}.{digits[main_digits:]}")
    else:
        result["value"] = float(int(digits))
    return result


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------

def _ollama(image_path, opts, main_digits, decimal_digits, timeout, log):
    url = opts["ollama_url"]
    model = opts["ollama_model"]
    keep_alive = int(opts.get("ollama_keep_alive", 0))
    prompt = _build_prompt(main_digits, decimal_digits)

    options = {"temperature": 0, "num_predict": 50, "keep_alive": keep_alive}
    num_thread = int(opts.get("ollama_num_thread", 0) or 0)
    if num_thread > 0:
        # Begrenzt, wie viele CPU-Threads Ollama fuer DIESE Anfrage nutzt -
        # funktioniert sowohl beim eingebauten als auch bei einem externen
        # Ollama-Server, da es Teil der Anfrage selbst ist.
        options["num_thread"] = num_thread

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "images": [_b64(image_path)],
        "options": options,
    }
    if bool(opts.get("ollama_force_json", True)):
        payload["format"] = "json"

    log(f"Sende Bild an Ollama ({model}"
        f"{f', num_thread={num_thread}' if num_thread > 0 else ''}) ...")
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
    except requests.exceptions.Timeout:
        return {"raw_digits": None, "error": f"Ollama-Timeout nach {timeout}s"}
    except requests.exceptions.RequestException as exc:
        return {"raw_digits": None, "error": f"Ollama nicht erreichbar: {exc}"}

    if keep_alive == 0:
        try:
            requests.post(url, json={"model": model, "keep_alive": 0}, timeout=10)
        except requests.exceptions.RequestException:
            pass

    if resp.status_code != 200:
        return {"raw_digits": None,
                "error": f"Ollama HTTP {resp.status_code}: {resp.text[:200]}"}
    try:
        text = resp.json().get("response", "")
    except json.JSONDecodeError:
        return {"raw_digits": None, "error": "Ollama-Antwort kein JSON"}
    return _finalize(text, main_digits, decimal_digits, log)


# ---------------------------------------------------------------------------
# OpenAI (Chat Completions, Vision)
# ---------------------------------------------------------------------------

def _openai(image_path, opts, main_digits, decimal_digits, timeout, log):
    api_key = opts.get("openai_api_key", "")
    if not api_key:
        return {"raw_digits": None, "error": "OpenAI: kein API-Schlüssel gesetzt"}
    model = opts.get("openai_model", "gpt-4o-mini")
    prompt = _build_prompt(main_digits, decimal_digits)
    img = _b64(image_path)

    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 50,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{img}"}},
            ],
        }],
    }
    log(f"Sende Bild an OpenAI ({model}) ...")
    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}",
                     "Content-Type": "application/json"},
            json=payload, timeout=timeout,
        )
    except requests.exceptions.RequestException as exc:
        return {"raw_digits": None, "error": f"OpenAI nicht erreichbar: {exc}"}
    if resp.status_code != 200:
        return {"raw_digits": None,
                "error": f"OpenAI HTTP {resp.status_code}: {resp.text[:200]}"}
    try:
        text = resp.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, json.JSONDecodeError):
        return {"raw_digits": None, "error": "OpenAI-Antwort unerwartet"}
    return _finalize(text, main_digits, decimal_digits, log)


# ---------------------------------------------------------------------------
# Google Gemini (generateContent)
# ---------------------------------------------------------------------------

def _gemini(image_path, opts, main_digits, decimal_digits, timeout, log):
    api_key = opts.get("gemini_api_key", "")
    if not api_key:
        return {"raw_digits": None, "error": "Gemini: kein API-Schlüssel gesetzt"}
    model = opts.get("gemini_model", "gemini-2.0-flash")
    prompt = _build_prompt(main_digits, decimal_digits)
    img = _b64(image_path)

    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={api_key}")
    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": "image/jpeg", "data": img}},
            ]
        }],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 50},
    }
    log(f"Sende Bild an Gemini ({model}) ...")
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        return {"raw_digits": None, "error": f"Gemini nicht erreichbar: {exc}"}
    if resp.status_code != 200:
        return {"raw_digits": None,
                "error": f"Gemini HTTP {resp.status_code}: {resp.text[:200]}"}
    try:
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, json.JSONDecodeError):
        return {"raw_digits": None, "error": "Gemini-Antwort unerwartet"}
    return _finalize(text, main_digits, decimal_digits, log)


# ---------------------------------------------------------------------------
# Anthropic Claude (messages)
# ---------------------------------------------------------------------------

def _claude(image_path, opts, main_digits, decimal_digits, timeout, log):
    api_key = opts.get("claude_api_key", "")
    if not api_key:
        return {"raw_digits": None, "error": "Claude: kein API-Schlüssel gesetzt"}
    model = opts.get("claude_model", "claude-3-5-sonnet-20241022")
    prompt = _build_prompt(main_digits, decimal_digits)
    img = _b64(image_path)

    payload = {
        "model": model,
        "max_tokens": 50,
        "temperature": 0,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/jpeg", "data": img}},
                {"type": "text", "text": prompt},
            ],
        }],
    }
    log(f"Sende Bild an Claude ({model}) ...")
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key,
                     "anthropic-version": "2023-06-01",
                     "Content-Type": "application/json"},
            json=payload, timeout=timeout,
        )
    except requests.exceptions.RequestException as exc:
        return {"raw_digits": None, "error": f"Claude nicht erreichbar: {exc}"}
    if resp.status_code != 200:
        return {"raw_digits": None,
                "error": f"Claude HTTP {resp.status_code}: {resp.text[:200]}"}
    try:
        text = resp.json()["content"][0]["text"]
    except (KeyError, IndexError, json.JSONDecodeError):
        return {"raw_digits": None, "error": "Claude-Antwort unerwartet"}
    return _finalize(text, main_digits, decimal_digits, log)


# ---------------------------------------------------------------------------
# Tesseract (lokale klassische OCR, kein KI-Modell noetig)
# ---------------------------------------------------------------------------

def _tesseract(image_path, opts, main_digits, decimal_digits, timeout, log):
    try:
        import pytesseract
        from PIL import Image, ImageOps
    except ImportError as exc:
        return {"raw_digits": None, "error": f"Tesseract nicht verfügbar: {exc}"}

    log("Lese Bild mit Tesseract (lokale OCR, kein KI-Modell) ...")
    try:
        img = Image.open(image_path).convert("L")
        # Hochskalieren hilft Tesseract bei kleinen Zaehlerausschnitten
        img = img.resize((img.width * 3, img.height * 3), Image.LANCZOS)
        img = ImageOps.autocontrast(img)
        # Harter Schwellenwert (Schwarz/Weiss) - bringt bei gestanzten
        # Ziffern oft mehr als reines Scharfzeichnen.
        img = img.point(lambda x: 255 if x > 140 else 0)
        config = "--psm 7 -c tessedit_char_whitelist=0123456789"
        text = pytesseract.image_to_string(img, config=config)
    except Exception as exc:  # noqa: BLE001
        return {"raw_digits": None, "error": f"Tesseract-Fehler: {exc}"}

    return _finalize(text, main_digits, decimal_digits, log)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

PROVIDERS = {
    "tesseract": _tesseract,
    "ollama_local": _ollama,
    "ollama_remote": _ollama,
    "openai": _openai,
    "gemini": _gemini,
    "claude": _claude,
}


def read_digits(provider, image_path, opts, main_digits, decimal_digits, timeout, log):
    """Ruft den konfigurierten Anbieter auf."""
    fn = PROVIDERS.get(provider)
    if fn is None:
        return {"raw_digits": None, "error": f"unbekannter Anbieter: {provider}"}
    return fn(image_path, opts, main_digits, decimal_digits, timeout, log)
