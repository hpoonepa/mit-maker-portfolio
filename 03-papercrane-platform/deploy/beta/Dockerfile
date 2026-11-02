# syntax=docker/dockerfile:1.7
FROM node:22-bookworm-slim AS source
RUN corepack enable && corepack prepare pnpm@9.12.3 --activate
WORKDIR /app
COPY . .
RUN pnpm dlx turbo@2.3.3 prune @papercrane/api @papercrane/worker --docker

FROM node:22-bookworm-slim AS dependencies
RUN apt-get update && apt-get install -y --no-install-recommends openssl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && corepack enable && corepack prepare pnpm@9.12.3 --activate
WORKDIR /app
COPY --from=source /app/out/json/ ./
COPY --from=source /app/out/pnpm-lock.yaml ./pnpm-lock.yaml
COPY --from=source /app/out/pnpm-workspace.yaml ./pnpm-workspace.yaml
# Prisma's schema is not present in Turbo's manifest-only layer yet.
RUN pnpm install --frozen-lockfile --ignore-scripts
COPY --from=source /app/out/full/ ./
RUN pnpm --filter @papercrane/db exec prisma generate

FROM node:22-bookworm-slim AS runtime
ENV NODE_ENV=production
ENV PATH="/opt/modal/bin:${PATH}"
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates openssl redis-server python3 python3-venv tini gosu curl \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/modal \
    && /opt/modal/bin/pip install --no-cache-dir 'modal>=1.0,<2'
WORKDIR /app
COPY --from=dependencies --chown=node:node /app/ ./
COPY --from=source --chown=node:node /app/tools ./tools
COPY --from=source --chown=node:node /app/deploy/beta ./deploy/beta
COPY --from=source --chown=node:node /app/tsconfig.base.json ./tsconfig.base.json
EXPOSE 8080
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "mkdir -p /data/redis && chown node:node /data/redis && exec gosu node node deploy/beta/start.mjs"]
