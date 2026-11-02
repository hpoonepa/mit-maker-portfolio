# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------
# Paper Crane API — multi-stage Docker build
# Build from repo root: docker build -f apps/api/Dockerfile .
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
# Use turbo prune to produce a minimal subset for the api
FROM base AS pruner
COPY . .
RUN pnpm dlx turbo@2.3.3 prune @papercrane/api --docker

# =========== stage 3: deps (install only) ===========
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
COPY turbo.json tsconfig.base.json ./
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile
RUN pnpm turbo run build --filter=@papercrane/api...

# =========== stage 5: runner ===========
FROM node:${NODE_VERSION}-alpine AS runner
ENV NODE_ENV=production
ENV PORT=8080
ENV HOST=0.0.0.0
RUN apk add --no-cache tini curl python3 py3-pip \
  && pip3 install --break-system-packages "modal>=1.0,<2" \
  && addgroup -S app -g 1001 \
  && adduser -S app -u 1001 -G app
WORKDIR /app

# Copy production node_modules + built workspace packages
COPY --from=builder --chown=app:app /app/node_modules ./node_modules
# Workspace packages export TypeScript source; use the same tsx loader as local verification.
COPY --from=builder --chown=app:app /app/apps/api/src ./apps/api/src
COPY --from=builder --chown=app:app /app/apps/api/package.json ./apps/api/package.json
COPY --from=builder --chown=app:app /app/apps/api/tsconfig.json ./apps/api/tsconfig.json
COPY --from=builder --chown=app:app /app/apps/api/node_modules ./apps/api/node_modules
COPY --from=builder --chown=app:app /app/packages ./packages
COPY --from=builder --chown=app:app /app/package.json /app/pnpm-workspace.yaml /app/tsconfig.base.json ./

USER app
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/healthz || exit 1

ENTRYPOINT ["/sbin/tini", "--"]
WORKDIR /app/apps/api
CMD ["node", "--import", "tsx", "src/server.ts"]
