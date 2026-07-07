# [Flow: Step 1 (Node.js 베이스 이미지) -> Step 2 (의존성 설치) -> Step 3 (TypeScript 빌드) -> Step 4 (런타임 이미지)]
# Vercel AI SDK 5.x 기반 Node.js AI 백엔드 컨테이너.
# FastAPI(api 서비스)가 /api/ai/* 요청을 이 컨테이너로 리버스 프록시한다.

# --- Build stage ---
FROM node:20-slim AS builder
WORKDIR /app

COPY ai-backend/package.json ai-backend/package-lock.json* ./
RUN npm ci || npm install

COPY ai-backend/tsconfig.json ./
COPY ai-backend/src/ ./src/
RUN npm run build

# --- Runtime stage ---
FROM node:20-slim AS runtime
WORKDIR /app

COPY ai-backend/package.json ai-backend/package-lock.json* ./
RUN npm ci --omit=dev || npm install --omit=dev

COPY --from=builder /app/dist ./dist

ENV PORT=3001
ENV NODE_ENV=production
EXPOSE 3001

CMD ["node", "dist/server.js"]
