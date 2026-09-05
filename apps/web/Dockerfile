# syntax=docker/dockerfile:1.7

ARG NODE_VERSION=22.22.0
ARG NGINX_VERSION=1.29.5-alpine

FROM node:${NODE_VERSION}-alpine AS builder

ENV NODE_ENV=development \
    VITE_APP_ENV=production \
    VITE_API_BASE_URL=""

WORKDIR /build

# Install exactly the dependency graphs recorded in both npm lock files.
COPY contracts/package.json contracts/package-lock.json /build/contracts/
COPY apps/web/package.json apps/web/package-lock.json /build/apps/web/
RUN npm ci --prefix /build/contracts \
    && npm ci --prefix /build/apps/web

COPY contracts /build/contracts
COPY apps/api/openapi.json /build/apps/api/openapi.json
COPY apps/web /build/apps/web

RUN npm --prefix /build/apps/web run build


FROM nginxinc/nginx-unprivileged:${NGINX_VERSION} AS runtime

ENV DOCREVIEW_API_UPSTREAM=http://api:8000

COPY apps/web/nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=builder /build/apps/web/dist /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD ["wget", "--quiet", "--tries=1", "--spider", "http://127.0.0.1:8080/healthz"]
