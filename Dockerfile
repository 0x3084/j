# --- dashboard build
FROM node:22-slim AS ui
WORKDIR /ui
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY dashboard/ ./
RUN npm run build

# --- python app
FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml ./
COPY qrs/ qrs/
RUN pip install --no-cache-dir -e .[dev] exchange_calendars
COPY configs/ configs/
COPY scripts/ scripts/
COPY tests/ tests/
COPY reports/ reports/
COPY --from=ui /ui/dist dashboard/dist
ENV QRS_DATA_DIR=/app/data
EXPOSE 8000
CMD ["sh", "-c", "[ -f data/processed/etf_daily.parquet ] || python -m scripts.ingest; uvicorn qrs.api.app:app --host 0.0.0.0 --port 8000"]
