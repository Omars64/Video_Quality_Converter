FROM denoland/deno:bin-2.9.5 AS deno_bin
FROM python:3.13-slim

COPY --from=deno_bin /deno /usr/local/bin/deno

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg aria2 ca-certificates libreoffice-writer fonts-dejavu-core chromium xvfb xauth \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY chromium-token /usr/local/bin/chromium-token
RUN chmod 755 /usr/local/bin/chromium-token

ENV VQI_DATA_DIR=/data
ENV VQI_WORKER_COUNT=1
ENV PYTHONUNBUFFERED=1
RUN useradd --create-home appuser && mkdir -p /data && chown appuser:appuser /data
USER appuser
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
