#!/usr/bin/env bash
# Entrypoint des Add-ons.
# Bei ocr_provider=ollama_local wird Ollama beim ersten Start heruntergeladen
# (persistent in /data), gestartet und das Modell geladen. Sonst wird die App
# direkt gestartet - dann ist kein Ollama-Download noetig.
#
# Die Einstellungen kommen aus /data/settings.json (Konfiguration-Webseite).
# Falls die Datei noch nicht existiert (frischer Start nach einem Update von
# einer alten Version), wird als Fallback die alte /data/options.json
# gelesen - die eigentliche Migration in settings.json macht dann app.py.

set -e

SETTINGS=/data/settings.json
OPTIONS=/data/options.json

get_value() {
  # Liest key aus settings.json, sonst aus options.json, sonst Default.
  key="$1"; default="$2"
  python3 -c "
import json

def load(p):
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return {}

s = load('$SETTINGS')
o = load('$OPTIONS')
v = s.get('$key', o.get('$key', '$default'))
print(v)
" 2>/dev/null || echo "$default"
}

PROVIDER=$(get_value ocr_provider ollama_remote)

if [ "$PROVIDER" = "ollama_local" ]; then
  echo "[run] ocr_provider=ollama_local"

  # Binary evtl. schon vorhanden? (persistente Installation in /data)
  OLLAMA_BIN="$(find /data/ollama -type f -name ollama 2>/dev/null | head -1)"

  # Ollama-Binary bei Bedarf herunterladen (persistent in /data)
  if [ ! -x "$OLLAMA_BIN" ]; then
    echo "[run] lade Ollama-Binary herunter ..."
    ARCH="$(dpkg --print-architecture)"
    case "$ARCH" in
      amd64) OLLAMA_ARCH="amd64" ;;
      arm64) OLLAMA_ARCH="arm64" ;;
      *) echo "[run] FEHLER: nicht unterstuetzte Architektur $ARCH"; exit 1 ;;
    esac
    mkdir -p /data/ollama
    BASE="https://ollama.com/download/ollama-linux-${OLLAMA_ARCH}"
    OK=0

    # Bevorzugt das aktuelle .tar.zst-Format (-L folgt Redirects, -f meldet 404)
    echo "[run] versuche ${BASE}.tar.zst ..."
    if curl -fSL "${BASE}.tar.zst" -o /tmp/ollama.tar.zst; then
      if tar --use-compress-program=unzstd -C /data/ollama -xf /tmp/ollama.tar.zst; then
        OK=1
      fi
      rm -f /tmp/ollama.tar.zst
    fi

    # Fallback: aelteres .tgz-Format
    if [ "$OK" != "1" ]; then
      echo "[run] versuche ${BASE}.tgz ..."
      if curl -fSL "${BASE}.tgz" -o /tmp/ollama.tgz; then
        if tar -C /data/ollama -xzf /tmp/ollama.tgz; then
          OK=1
        fi
        rm -f /tmp/ollama.tgz
      fi
    fi

    if [ "$OK" = "1" ]; then
      echo "[run] Ollama installiert nach /data/ollama"
      OLLAMA_BIN="$(find /data/ollama -type f -name ollama 2>/dev/null | head -1)"
      [ -n "$OLLAMA_BIN" ] && chmod +x "$OLLAMA_BIN"
    else
      echo "[run] FEHLER: Ollama-Download fehlgeschlagen (beide Formate)."
      echo "[run] Starte App trotzdem - Auswertung mit ollama_local schlaegt fehl."
    fi
  fi

  if [ -x "$OLLAMA_BIN" ]; then
    MODEL=$(get_value ollama_model moondream)
    CPU_PERCENT=$(get_value ollama_local_cpu_percent 0)
    export OLLAMA_HOST=127.0.0.1:11434
    export OLLAMA_KV_CACHE_TYPE=f16
    export OLLAMA_FLASH_ATTENTION=0
    export OLLAMA_MODELS=/data/ollama_models
    mkdir -p /data/ollama_models

    if [ "$CPU_PERCENT" != "0" ] && command -v cpulimit >/dev/null 2>&1; then
      echo "[run] begrenze lokales Ollama auf ${CPU_PERCENT}% CPU (cpulimit, inkl. Kindprozesse)"
      cpulimit -l "$CPU_PERCENT" -i -- "$OLLAMA_BIN" serve &
    else
      "$OLLAMA_BIN" serve &
    fi

    echo "[run] warte auf Ollama ..."
    for i in $(seq 1 30); do
      if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
        echo "[run] Ollama ist bereit"; break
      fi
      sleep 1
    done

    echo "[run] stelle Modell bereit: $MODEL"
    "$OLLAMA_BIN" pull "$MODEL" || echo "[run] WARN: konnte Modell nicht laden"
  fi
fi

echo "[run] starte App"
exec python3 app.py
