# --- stage 1: build the frontend ---------------------------------------------
FROM node:22-alpine AS frontend

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


# --- stage 2: the add-on image -----------------------------------------------
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base-python:3.12-alpine3.20
FROM ${BUILD_FROM}

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MESH_SENTINEL_FRONTEND_DIR=/app/frontend

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --prefer-binary -r /app/requirements.txt

COPY backend/mesh_sentinel /app/mesh_sentinel
COPY --from=frontend /build/dist /app/frontend
COPY addon/run.sh /run.sh
RUN chmod a+x /run.sh

LABEL io.hass.type="addon" io.hass.version="0.1.0"

CMD ["/run.sh"]
