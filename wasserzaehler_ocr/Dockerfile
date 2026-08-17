FROM python:3.11-slim

LABEL io.hass.version="4.8.0" \
      io.hass.type="app" \
      io.hass.arch="amd64|aarch64"

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY fetch_image.py rotate.py ollama_ocr.py plausibility.py tuning.py app.py ./
COPY tuner.html ./

EXPOSE 5000

CMD ["python3", "app.py"]
