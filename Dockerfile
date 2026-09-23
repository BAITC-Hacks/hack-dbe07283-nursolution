FROM python:3.12-slim AS app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MATCHER_USE_LLM=false

WORKDIR /app

# Cache dependencies independently from application changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home app

COPY api.py schemas.py smart_matcher.py ./
COPY app/ ./app/
COPY data/ ./data/
COPY frontend/ ./frontend/

USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=4s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).close()"

CMD ["python", "-m", "uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]

# Optional test image; test files never enter the final runtime image.
FROM app AS test
USER root
COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY tests/ ./tests/
USER app
HEALTHCHECK NONE
CMD ["python", "-m", "unittest", "-v"]

FROM app AS runtime
