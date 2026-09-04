#!/bin/bash
set -e

# [Flow: Step 1 (LAN 접속 시도) -> Step 2 (실패 시 WAN fallback) -> Step 3 (rsync 동기화) -> Step 4 (Docker 재빌드/재시작) -> Step 5 (상태 확인)]
#
# develop 환경 배포 스크립트 — 프로덕션(deploy_a1.sh)과 동일한 a1 서버에
# 별도 프로젝트명(chungu-dev) + 별도 포트로 격리 실행.
#
# 포트 구성 (프로덕션과 충돌하지 않도록 분리):
#   API:        28190  (프로덕션 28181)
#   Docling:    28192  (프로덕션 28182)
#   LLMLingua:  8002   (프로덕션 8001)
#
# 접속: https://proof-develop.teamcat.app

TARGET=""
REMOTE_DIR="chungu-dev/app"
COMPOSE_PROJECT="chungu-dev"

# 1. 접속 경로 선택: LAN 우선, 실패 시 WAN fallback
if ssh -o ConnectTimeout=5 -o BatchMode=yes a1 "true" 2>/dev/null; then
  TARGET=a1
  echo "[deploy:develop] LAN 경로(a1)로 연결됨"
else
  echo "[deploy:develop] LAN 경로 실패, WAN 경로(wan-1)로 fallback"
  if ssh -o ConnectTimeout=10 -o BatchMode=yes wan-1 "true" 2>/dev/null; then
    TARGET=wan-1
    echo "[deploy:develop] WAN 경로(wan-1)로 연결됨"
  else
    echo "[deploy:develop] LAN/WAN 모두 연결 실패. a1 서버 상태를 확인하세요."
    exit 1
  fi
fi

# 2. 원격 디렉토리 준비
ssh $TARGET "mkdir -p ~/$REMOTE_DIR"

# 3. 동기화: 로컬 app -> 타겟 chungu-dev/app (env 파일 제외)
rsync -avz --delete \
  --exclude='.env' \
  --exclude='node_modules' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='dist' \
  --exclude='.vite' \
  --exclude='docs/build' \
  --exclude='docs/.docusaurus' \
  --exclude='.venv' \
  --exclude='venv' \
  /Users/jun16/repo/chungu/app/ \
  $TARGET:~/$REMOTE_DIR/

# 4. .env 준비: 프로덕션 .env 복사 후 develop 포트로 덮어쓰기 (이미 있으면 스킵)
ssh $TARGET "if [ ! -f ~/$REMOTE_DIR/.env ]; then \
  cp ~/chungu-app/app/.env ~/$REMOTE_DIR/.env && \
  sed -i 's/^APP_PORT=28181/APP_PORT=28190/' ~/$REMOTE_DIR/.env && \
  echo 'DOCLING_SERVICE_PORT=28192' >> ~/$REMOTE_DIR/.env && \
  echo '[deploy:develop] .env 생성 완료 (포트 28190/28192)'; \
else \
  echo '[deploy:develop] .env 이미 존재 — 유지'; \
fi"

# 5. LLMLingua 포트 충돌 방지: docker-compose.yml의 하드코딩된 8001을 환경변수화
ssh $TARGET "grep -q 'LLMLINGUA_PORT' ~/$REMOTE_DIR/docker-compose.yml || \
  sed -i 's/\"8001:8000\"/\"\${LLMLINGUA_PORT:-8001}:8000\"/' ~/$REMOTE_DIR/docker-compose.yml"

# 6. 이미지 재빌드 및 재시작 (별도 프로젝트명 + 별도 포트)
ssh $TARGET "cd ~/$REMOTE_DIR && \
  COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT \
  LLMLINGUA_PORT=8002 \
  docker compose down && \
  COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT \
  LLMLINGUA_PORT=8002 \
  docker compose up --build -d"

# 7. 상태 확인
sleep 5
ssh $TARGET "cd ~/$REMOTE_DIR && COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT docker compose ps"

echo ""
echo "[deploy:develop] 배포 완료 — https://proof-develop.teamcat.app"
