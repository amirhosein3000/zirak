FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data
COPY pyproject.toml ./
COPY zirak ./zirak
COPY tests/fixtures/sample ./tests/fixtures/sample
RUN pip install --no-cache-dir .
VOLUME ["/data"]
EXPOSE 8000
# REPLAY_DIR points at the bundled sample; the recorder DB in /data is preferred when it has data.
ENV REPLAY_DIR=/app/tests/fixtures/sample
CMD ["uvicorn", "zirak.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
