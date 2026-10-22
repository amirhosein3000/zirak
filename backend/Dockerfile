FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data
COPY pyproject.toml ./
COPY zirak ./zirak
COPY config ./config
COPY tests/fixtures/wallex ./tests/fixtures/wallex
RUN pip install --no-cache-dir .
VOLUME ["/data"]
EXPOSE 8000
# REPLAY_DIR points at the bundled real Wallex sample; the recorder DB in /data wins when it has data.
ENV REPLAY_DIR=/app/tests/fixtures/wallex
# The commit this image was built from, recorded in every run's manifest (the code that traded).
ARG GIT_COMMIT=unknown
ENV ZIRAK_COMMIT=$GIT_COMMIT
CMD ["uvicorn", "zirak.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
