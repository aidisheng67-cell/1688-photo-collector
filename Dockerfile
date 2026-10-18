FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    COLLECTOR_CONFIG=/app/config/config.yaml \
    COLLECTOR_WORK=/data/work \
    COLLECTOR_OUTPUT=/data/output \
    COLLECTOR_CACHE=/data/cache/cache.sqlite \
    COLLECTOR_LOG=/data/logs \
    COLLECTOR_REVIEW=/data/review

# opencv-python-headless 仍依赖 glib / OpenMP 运行库
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY *.py ./
COPY config.example.yaml ./

RUN useradd --create-home --uid 10001 collector \
    && mkdir -p /data/work /data/output /data/cache /data/logs /data/review /app/config \
    && chown -R collector:collector /app /data

USER collector

VOLUME ["/data"]

CMD ["python", "watcher.py"]
