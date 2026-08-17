FROM python:3.11-slim

LABEL io.hass.version="4.11.1" \
      io.hass.type="app" \
      io.hass.arch="amd64|aarch64"

# Nur schlanke Basiswerkzeuge. Ollama wird NICHT ins Image gebacken, sondern
# vom run.sh beim ersten Start heruntergeladen - und nur dann, wenn
# ocr_provider=ollama_local gewaehlt ist. So bleibt der Build robust und das
# Image klein, wenn du Cloud oder externes Ollama nutzt.
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates tar && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY fetch_image.py rotate.py ollama_ocr.py ocr_providers.py plausibility.py tuning.py app.py ./
COPY tuner.html index.html run.sh ./
RUN chmod +x run.sh

EXPOSE 5000 8099

CMD ["./run.sh"]
