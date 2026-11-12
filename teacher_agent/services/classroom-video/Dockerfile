ARG NODE_IMAGE=node:22.22.2-bookworm-slim@sha256:f3a68cf41a855d227d1b0ab832bed9749469ef38cf4f58182fb8c893bc462383
FROM ${NODE_IMAGE}
ARG NPM_REGISTRY=https://registry.npmjs.org
ARG DEBIAN_MIRROR=http://deb.debian.org
RUN sed -i "s|http://deb.debian.org|${DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources \
 && apt-get update && apt-get install -y --no-install-recommends chromium ffmpeg ca-certificates fonts-noto-cjk fonts-liberation \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --registry=${NPM_REGISTRY} --no-audit --no-fund
COPY server.mjs readiness.mjs ./
RUN groupadd --gid 1001 renderer && useradd --uid 1001 --gid 1001 --create-home renderer \
 && mkdir -p /videos && chown renderer:renderer /videos
USER renderer
ENV NODE_ENV=production CHROMIUM_PATH=/usr/bin/chromium
EXPOSE 9010
CMD ["node", "server.mjs"]
