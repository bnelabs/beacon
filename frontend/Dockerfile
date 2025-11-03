# ======================
# Stage 1: Dependencies
# ======================
FROM node:20-alpine AS deps
WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install --legacy-peer-deps

# ======================
# Stage 2: Builder
# ======================
FROM node:20-alpine AS builder
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
FROM nginx:1.27-alpine
WORKDIR /usr/share/nginx/html

RUN rm -rf /etc/nginx/conf.d/default.conf

COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=builder /app/dist .

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://localhost/health || exit 1

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
