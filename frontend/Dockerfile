# syntax=docker/dockerfile:1.7

# ---------------------------------------------------------------------------
# Build the static bundle
# ---------------------------------------------------------------------------
FROM node:24-alpine AS builder

WORKDIR /build

# `npm ci` against the lockfile only -- reproducible, and cached until the
# lockfile itself changes.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Vite inlines env vars at build time, so the API base URL is a build
# argument rather than a runtime one. It is left empty by default because
# nginx proxies /api to the API on the same origin (see nginx.conf), which
# avoids CORS entirely.
ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build

# ---------------------------------------------------------------------------
# Serve
# ---------------------------------------------------------------------------
FROM nginx:1.27-alpine AS runtime

RUN rm -rf /usr/share/nginx/html/*
COPY --from=builder /build/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

# The stock nginx image already runs workers as the unprivileged `nginx`
# user; port 8080 is used so the master does not need root to bind either.
EXPOSE 8080

# `127.0.0.1`, not `localhost`: inside the container `localhost` also resolves
# to `::1`, BusyBox wget tries IPv6 first, and nginx's `listen 8080` binds
# IPv4 only -- so the probe gets "connection refused" while the site is
# perfectly reachable from outside. An explicit address removes the ambiguity.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget --quiet --spider http://127.0.0.1:8080/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
