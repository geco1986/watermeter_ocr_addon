#!/usr/bin/env bash
# Entrypoint des Add-ons.
# Startet - falls ocr_provider = ollama_local - einen lokalen Ollama-Server
# im Container, laedt das Modell und startet dann die Python-App.

set -e

OPTIONS=/data/options.json
PROVIDER=$(python3 -c "import json;print(json.load(open('$OPTIONS')).get('ocr_provider','ollama_remote'))" 2>/dev/null || echo "ollama_remote")

if [ "$PROVIDER" = "ollama_local" ]; then
  echo "[run] ocr_provider=ollama_local -> starte lokalen Ollama-Server"
  MODEL=$(python3 -c "import json;print(json.load(open('$OPTIONS')).get('ollama_model','moondream'))" 2>/dev/null || echo "moondream")

  # Ollama im Hintergrund starten
  export OLLAMA_HOST=127.0.0.1:11434
  export OLLAMA_KV_CACHE_TYPE=f16
  export OLLAMA_FLASH_ATTENTION=0
  # Modelle in /data ablegen (persistent ueber Add-on-Neustarts hinweg),
  # damit sie nicht jedes Mal neu geladen werden muessen.
  export OLLAMA_MODELS=/data/ollama_models
  mkdir -p /data/ollama_models
  ollama serve &
  OLLAMA_PID=$!

  # Warten bis erreichbar
  echo "[run] warte auf Ollama ..."
  for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
      echo "[run] Ollama ist bereit"
      break
    fi
    sleep 1
  done

  # Modell laden (falls noch nicht vorhanden)
  echo "[run] stelle Modell bereit: $MODEL"
  ollama pull "$MODEL" || echo "[run] WARN: konnte Modell nicht laden (evtl. offline)"
fi

echo "[run] starte App"
exec python3 app.py
