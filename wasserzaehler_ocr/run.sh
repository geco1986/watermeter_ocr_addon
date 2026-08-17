#!/usr/bin/env bash
# Entrypoint des Add-ons.
# Bei ocr_provider=ollama_local wird Ollama beim ersten Start heruntergeladen
# (persistent in /data), gestartet und das Modell geladen. Sonst wird die App
# direkt gestartet - dann ist kein Ollama-Download noetig.

set -e

OPTIONS=/data/options.json
PROVIDER=$(python3 -c "import json;print(json.load(open('$OPTIONS')).get('ocr_provider','ollama_remote'))" 2>/dev/null || echo "ollama_remote")

if [ "$PROVIDER" = "ollama_local" ]; then
  echo "[run] ocr_provider=ollama_local"
  OLLAMA_BIN=/data/ollama/bin/ollama

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
    if curl -fsSL "https://ollama.com/download/ollama-linux-${OLLAMA_ARCH}.tgz" -o /tmp/ollama.tgz; then
      tar -C /data/ollama -xzf /tmp/ollama.tgz
      rm -f /tmp/ollama.tgz
      echo "[run] Ollama installiert nach /data/ollama"
    else
      echo "[run] FEHLER: Ollama-Download fehlgeschlagen. Pruefe die Internetverbindung."
      echo "[run] Starte App trotzdem - Auswertung schlaegt bis dahin fehl."
    fi
  fi

  if [ -x "$OLLAMA_BIN" ]; then
    MODEL=$(python3 -c "import json;print(json.load(open('$OPTIONS')).get('ollama_model','moondream'))" 2>/dev/null || echo "moondream")
    export OLLAMA_HOST=127.0.0.1:11434
    export OLLAMA_KV_CACHE_TYPE=f16
    export OLLAMA_FLASH_ATTENTION=0
    export OLLAMA_MODELS=/data/ollama_models
    mkdir -p /data/ollama_models
    "$OLLAMA_BIN" serve &

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
