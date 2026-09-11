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
RUN npm ci

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

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://localhost/health || exit 1

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
