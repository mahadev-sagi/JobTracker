# -----------------------------------------------------------------------------
# JobTracker frontend — Vite dev server.
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

FROM nginx:stable-alpine AS production
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 5173
