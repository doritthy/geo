FROM node:20-alpine AS base

WORKDIR /app

COPY package.json package-lock.json* ./
# postinstall copies CesiumJS runtime assets into public/cesium
COPY scripts ./scripts
RUN npm install

COPY . .

ENV NEXT_TELEMETRY_DISABLED=1

EXPOSE 3000

CMD ["npm", "run", "dev"]
