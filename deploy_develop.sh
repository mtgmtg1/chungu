#!/bin/bash
set -e

# [Flow: Step 1 (LAN/Tailscale/WAN 순 접속 시도) -> Step 3 (rsync 동기화) -> Step 4 (Docker 재빌드/재시작) -> Step 5 (상태 확인)]
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

REMOTE_DIR="chungu-dev/app"
COMPOSE_PROJECT="chungu-dev"

# 1. 접속 경로 선택: LAN -> Tailscale -> WAN 순으로 시도한다.
# LAN 은 집 안에서만 되고, WAN 은 통신사 포트포워딩이라 막히는 경우가 있다.
# Tailscale(ts-a1)은 어느 네트워크에서도 붙으므로 중간 폴백으로 둔다 (~/.ssh/config 정의).
TARGET=""
for candidate in a1 ts-a1 wan-1; do
  if ssh -o ConnectTimeout=10 -o BatchMode=yes "$candidate" "true" 2>/dev/null; then
    TARGET=$candidate
    echo "[deploy:develop] 경로($candidate)로 연결됨"
    break
  fi
  echo "[deploy:develop] $candidate 연결 실패 — 다음 경로 시도"
done
if [ -z "$TARGET" ]; then
  echo "[deploy:develop] LAN/Tailscale/WAN 모두 연결 실패. a1 서버 상태와 Tailscale 연결을 확인하세요."
  exit 1
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
