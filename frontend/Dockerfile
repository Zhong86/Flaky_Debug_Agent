# syntax=docker/dockerfile:1
# Monitoring dashboard (Next.js). Built by deploy/compose.yaml with frontend/ as the
# build context.
FROM node:24-bookworm-slim

WORKDIR /app
RUN chown node:node /app
USER node

COPY --chown=node:node package.json package-lock.json ./
RUN npm ci

COPY --chown=node:node . .
# Inlined into the browser bundle at build time. "/api" means same origin: Caddy
# sends /api/* to the backend, so the dashboard works behind any public URL.
ARG NEXT_PUBLIC_API_BASE_URL=/api
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} NEXT_TELEMETRY_DISABLED=1
RUN npm run build

ENV NODE_ENV=production
EXPOSE 3000
CMD ["npm", "run", "start", "--", "-H", "0.0.0.0", "-p", "3000"]
