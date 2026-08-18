FROM python:3.11-slim

LABEL io.hass.version="5.1.0" \
      io.hass.type="app" \
      io.hass.arch="amd64|aarch64"

# curl/tar/zstd: fuer den optionalen Ollama-Download zur Laufzeit (nur bei
#   ocr_provider=ollama_local, siehe run.sh).
# tesseract-ocr: fuer den Anbieter "tesseract" (klassische, lokale OCR ohne
#   KI-Modell - schnellste und genuegsamste Option, siehe README).
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl ca-certificates tar zstd \
        tesseract-ocr tesseract-ocr-eng && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY fetch_image.py rotate.py ocr_providers.py plausibility.py tuning.py \
     settings.py sysinfo.py app.py ./
COPY tuner.html index.html config.html run.sh ./
RUN chmod +x run.sh

EXPOSE 5000 8099

CMD ["./run.sh"]
