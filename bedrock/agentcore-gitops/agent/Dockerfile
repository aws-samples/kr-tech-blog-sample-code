FROM python:3.14.7-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6 AS builder
WORKDIR /app
RUN python -m venv /app/.venv
COPY requirements.lock ./
RUN /app/.venv/bin/pip install --no-cache-dir --require-hashes -r requirements.lock

FROM python:3.14.7-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
RUN useradd --uid 10001 --create-home appuser
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --chown=10001:10001 main.py ./
COPY --chown=10001:10001 gateway_probe.py ./
ARG BUILD_REVISION=local
ENV BUILD_REVISION=$BUILD_REVISION
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
EXPOSE 8080
CMD ["python", "main.py"]
