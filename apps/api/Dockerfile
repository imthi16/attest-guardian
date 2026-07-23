# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /build
# Optional dependency extras to install into the image, e.g. "[paddle]" for a
# PaddleOCR-enabled worker. Empty by default so the base image stays slim.
ARG PIP_EXTRAS=""
COPY pyproject.toml README.md ./
COPY app ./app
RUN python -m pip install --prefix=/install ".${PIP_EXTRAS}"

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
RUN addgroup --system --gid 10001 attest \
    && adduser --system --uid 10001 --ingroup attest --home /app attest
COPY --from=builder /install /usr/local
COPY --chown=attest:attest app ./app
RUN python -c "from app.main import app; assert app.title == 'Attest Guardian API'"
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
