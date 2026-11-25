# ALEA web app + Stage 11 prediction API (read-only over the prospective ledger).
# Build:  docker build -t alea-api .
# Run:    docker run --rm -p 127.0.0.1:8080:8080 -v "$PWD/ledger-data:/data:ro" alea-api
# Hosted: docker run --rm -p 8080:8080 \
#           -e ALEA_LEDGER_SYNC_URL=https://raw.githubusercontent.com/gopolang-453/alea/prospective-ledger alea-api
#         (no volume needed: the ledger is downloaded, gate-verified and refreshed every 30 min)
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    ALEA_LEDGER=/data/ledger.sqlite ALEA_REGISTRY=/app/config/model_registry.json \
    ALEA_HOST=0.0.0.0 ALEA_PORT=8080
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY alea_predictor_v2_4_1.py SHA256SUMS.txt ./
COPY frozen/ frozen/
COPY alea_value_engine_v0_2_1.py ./
COPY config/ config/
COPY stages/ stages/
COPY scripts/ scripts/
COPY web/ web/
RUN sha256sum -c SHA256SUMS.txt && useradd --system --no-create-home alea \
    && mkdir -p /data && chown alea /data
USER alea
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health').status==200 else 1)"
CMD ["python", "scripts/serve_api.py"]
