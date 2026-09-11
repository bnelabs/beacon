# syntax=docker/dockerfile:1.7
# ======================
# Stage 1: Dependencies
# ======================
FROM node:24-alpine AS deps
WORKDIR /app

COPY package.json package-lock.json* ./
# `npm ci` installs the exact locked tree, including peer dependencies.
# The previous `npm install --legacy-peer-deps` skipped peer deps entirely, so
# `@deck.gl/widgets` (a peer of @deck.gl/react) was absent and `npm run build`
# failed inside the image with "Rollup failed to resolve import
# '@deck.gl/widgets'". `npm ci` is also faster and reproducible.
# The npm cache is a BuildKit cache mount so rebuilds reuse the downloaded
# tarballs even when package-lock.json changes.
RUN --mount=type=cache,target=/root/.npm \
    npm ci

# ======================
# Stage 2: Builder
# ======================
FROM node:24-alpine AS builder
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

ARG VITE_API_BASE_URL=http://localhost:3456
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
ENV NODE_ENV=production

RUN npm run build

# ======================
# Stage 3: Production
# ======================
FROM nginx:1.30-alpine
WORKDIR /usr/share/nginx/html

RUN rm -rf /etc/nginx/conf.d/default.conf

COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=builder /app/dist .

# why 127.0.0.1 and not localhost: nginx listens on 0.0.0.0:80 only (see
# nginx.conf), but this image ships a /etc/hosts that maps `localhost` to ::1
# *and* 127.0.0.1, and busybox wget prefers the IPv6 address. Probing
# `http://localhost/health` therefore got "connection refused" and the container
# reported unhealthy for its entire life while serving every real request
# correctly on IPv4. Addressing the loopback explicitly says what is meant.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://127.0.0.1/health || exit 1

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
