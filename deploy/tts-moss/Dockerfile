FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/cache \
    HF_HUB_DISABLE_TELEMETRY=1 \
    OMP_NUM_THREADS=4 \
    MKL_NUM_THREADS=4

RUN apt-get update \
    && apt-get install -y --no-install-recommends libsndfile1 libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 tts \
    && useradd --uid 10001 --gid tts --create-home tts \
    && mkdir -p /app /cache \
    && chown tts:tts /app /cache

WORKDIR /app
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=tts:tts server.py ./server.py

USER tts
VOLUME ["/cache"]
EXPOSE 8001
HEALTHCHECK --interval=30s --timeout=5s --start-period=30m --retries=3 \
    CMD python -c "import os, urllib.request; r = urllib.request.Request('http://127.0.0.1:8001/healthz', headers={'Authorization': 'Bearer ' + os.getenv('SHIM_API_KEY', '')}); urllib.request.urlopen(r, timeout=3).close()"
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1", "--no-access-log"]
