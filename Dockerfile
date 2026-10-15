# FastAPI ML prediction service
FROM python:3.12-slim

WORKDIR /app

# System deps for numpy/scipy wheels fallback
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code + trained model artifacts.
# NOTE: data/ is excluded via .dockerignore (models are only ~40 MB;
# they are baked into the image so restarts never re-download anything).
COPY src/ ./src/
COPY api/ ./api/
COPY scripts/ ./scripts/
COPY models/ ./models/

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=4).status==200 else 1)"

CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000"]
