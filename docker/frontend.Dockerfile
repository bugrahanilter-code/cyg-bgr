# ---------------------------------------------------------------------------
# Frontend image: Vite build served by nginx, which also proxies /api
# Build context is the repository root.
# ---------------------------------------------------------------------------
FROM node:20-alpine AS build

WORKDIR /app
COPY frontend/package.json ./package.json
RUN npm install

COPY frontend/ ./
ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
# The type check runs in CI; the image build only bundles the application so a
# type-only problem can never stop the platform from starting locally.
RUN npm run build:app

FROM nginx:alpine
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
