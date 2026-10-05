# -----------------------------------------------------------------------------
# JobTracker frontend — Vite dev server, and the production web image.
#
# docker-compose bind-mounts ./frontend over /app and keeps node_modules in an
# anonymous volume, so this image only needs the toolchain plus a warm
# node_modules layer.
# -----------------------------------------------------------------------------
FROM node:20-alpine AS development

WORKDIR /app

# Copy manifests first so the dependency layer is cached independently of source.
# The glob on the lockfile keeps the build working before one is generated.
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY . .

EXPOSE 5173

# --host binds 0.0.0.0 so the port is reachable from outside the container.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]

FROM development AS build
RUN npm run build

# -----------------------------------------------------------------------------
# Production: Caddy serves the compiled app, terminates HTTPS (certificates are
# obtained and renewed automatically) and proxies /api to the backend. Its
# configuration is mounted from infra/deploy/Caddyfile, so it can change
# without rebuilding this image.
# -----------------------------------------------------------------------------
FROM caddy:2-alpine AS web
COPY --from=build /app/dist /srv
EXPOSE 80 443
