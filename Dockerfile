FROM node:20-bookworm-slim AS builder

ENV NODE_ENV=production \
    BUILDER_HOST=0.0.0.0 \
    BUILDER_PORT=8788
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts --no-audit --no-fund
COPY tools ./tools
USER node
HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD node -e "fetch('http://127.0.0.1:8788/health').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"
CMD ["node", "tools/pump_builder_service.mjs"]

FROM python:3.12-slim-bookworm AS app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY requirements.lock ./
RUN pip install --require-hashes -r requirements.lock

COPY kol_sniper ./kol_sniper
COPY sniper.py notify.py logger.py telegram_bot.py ./

RUN useradd --create-home --uid 10001 sniper && mkdir -p /app/data && chown sniper:sniper /app/data
USER sniper

VOLUME ["/app/data"]
HEALTHCHECK --interval=15s --timeout=3s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/health', timeout=2)"
CMD ["python", "sniper.py"]
