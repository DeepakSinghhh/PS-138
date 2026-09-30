# Single image: builds the React dashboard, then serves it together with the FastAPI backend.
FROM node:22-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npx vite build

FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 GREENFLEET_WARMUP=1
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY data/ data/
COPY docs/ docs/
COPY reports/ reports/
COPY --from=web /app/frontend/dist frontend/dist
WORKDIR /app/backend
EXPOSE 8000
# hosts such as Render set PORT; default 8000
CMD ["sh", "-c", "exec uvicorn greenfleet.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
