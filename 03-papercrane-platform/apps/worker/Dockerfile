# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------
# Paper Crane Worker — multi-stage Docker build
# Build from repo root: docker build -f apps/worker/Dockerfile .
# ---------------------------------------------------------------

ARG NODE_VERSION=20.15.0
ARG PNPM_VERSION=9.12.3

# =========== stage 1: base ===========
FROM node:${NODE_VERSION}-alpine AS base
ARG PNPM_VERSION
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"
RUN apk add --no-cache libc6-compat tini curl \
  && corepack enable \
  && corepack prepare pnpm@${PNPM_VERSION} --activate
WORKDIR /app

# =========== stage 2: pruner ===========
FROM base AS pruner
COPY . .
RUN pnpm dlx turbo@2.3.3 prune @papercrane/worker --docker

# =========== stage 3: deps ===========
FROM base AS deps
COPY --from=pruner /app/out/json/ ./
COPY --from=pruner /app/out/pnpm-lock.yaml ./pnpm-lock.yaml
COPY --from=pruner /app/out/pnpm-workspace.yaml ./pnpm-workspace.yaml
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile

# =========== stage 4: builder ===========
FROM base AS builder
COPY --from=deps /app/ ./
COPY --from=pruner /app/out/full/ ./
# `tools/` is intentionally not a pnpm workspace, so Turbo prune omits it.
# Copy the Modal Python apps from the unpruned source tree explicitly.
COPY --from=pruner /app/tools ./tools
COPY turbo.json tsconfig.base.json ./
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile
RUN pnpm turbo run build --filter=@papercrane/worker...

# =========== stage 5: runner ===========
FROM node:${NODE_VERSION}-alpine AS runner
ENV NODE_ENV=production
ENV WORKER_PORT=3003
ENV PORT_HEALTH=3003
ENV HOST=0.0.0.0
RUN apk add --no-cache tini curl python3 py3-pip \
  && pip3 install --break-system-packages "modal>=1.0" \
  && addgroup -S app -g 1001 \
  && adduser -S app -u 1001 -G app
WORKDIR /app

COPY --from=builder --chown=app:app /app/node_modules ./node_modules
# Workspace packages export TypeScript source; use the same tsx loader as local verification.
COPY --from=builder --chown=app:app /app/apps/worker/src ./apps/worker/src
COPY --from=builder --chown=app:app /app/apps/worker/package.json ./apps/worker/package.json
COPY --from=builder --chown=app:app /app/apps/worker/tsconfig.json ./apps/worker/tsconfig.json
COPY --from=builder --chown=app:app /app/apps/worker/scripts ./apps/worker/scripts
COPY --from=builder --chown=app:app /app/apps/worker/node_modules ./apps/worker/node_modules
COPY --from=builder --chown=app:app /app/packages ./packages
COPY --from=builder --chown=app:app /app/tools ./tools
COPY --from=builder --chown=app:app /app/package.json /app/pnpm-workspace.yaml /app/tsconfig.base.json ./

USER app
EXPOSE 3003

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -fsS http://127.0.0.1:3003/healthz || exit 1

ENTRYPOINT ["/sbin/tini", "--"]
WORKDIR /app/apps/worker
CMD ["node", "--import", "tsx", "src/server.ts"]
