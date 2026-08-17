FROM python:3.11-slim

LABEL io.hass.version="4.11.0" \
      io.hass.type="app" \
      io.hass.arch="amd64|aarch64"

# curl fuer den Ollama-Healthcheck und Ollama-Installer; Ollama selbst wird
# installiert, damit ocr_provider=ollama_local funktioniert. Wer nur Cloud
# oder externes Ollama nutzt, laesst diesen Provider einfach ungenutzt.
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    curl -fsSL https://ollama.com/install.sh | sh && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY fetch_image.py rotate.py ollama_ocr.py ocr_providers.py plausibility.py tuning.py app.py ./
COPY tuner.html index.html run.sh ./
RUN chmod +x run.sh

EXPOSE 5000 8099

CMD ["./run.sh"]
