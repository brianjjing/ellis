# Ellis in one container: the Case API serves the built web app from the same origin, so cookies, /api and the
# WebSockets (/api/a/voice, the live streams) need no cross-domain setup. Built and run by Coolify; see README
# "Deploying". Run ONE instance: the staff-agent runner and the live-update bus live in the API process.

# ---- web app (Vite) ---------------------------------------------------------------------------------------------
FROM node:22-alpine AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Case API ---------------------------------------------------------------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ELLIS_FILES_DIR=/data/files
WORKDIR /app/backend
# dependencies first (a layer that survives code-only changes), then the code; editable, so config/, prompts/,
# migrations/ and seed/ stay next to the package where ellis.config looks for them
COPY backend/pyproject.toml ./
RUN mkdir ellis && touch ellis/__init__.py && pip install -e ".[llm]"
COPY backend/ ./
COPY --from=web /app/frontend/dist /app/frontend/dist
RUN useradd --create-home --uid 10001 ellis && mkdir -p /data/files && chown -R ellis /data /app/backend
USER ellis
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
# --proxy-headers: Coolify's proxy terminates HTTPS in front of the container
CMD ["uvicorn", "ellis.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
