#!/bin/bash
set -e

# [Flow: Step 1 (LAN/Tailscale/WAN 순 접속 시도) -> Step 3 (rsync 동기화) -> Step 4 (Docker 재빌드/재시작) -> Step 5 (상태 확인)]

# 1. 접속 경로 선택: LAN -> Tailscale -> WAN 순으로 시도한다.
# LAN 은 집 안에서만 되고, WAN 은 통신사 포트포워딩이라 막히는 경우가 있다.
# Tailscale(ts-a1)은 어느 네트워크에서도 붙으므로 중간 폴백으로 둔다 (~/.ssh/config 정의).
TARGET=""
for candidate in a1 ts-a1 wan-1; do
  if ssh -o ConnectTimeout=10 -o BatchMode=yes "$candidate" "true" 2>/dev/null; then
    TARGET=$candidate
    echo "[deploy] 경로($candidate)로 연결됨"
    break
  fi
  echo "[deploy] $candidate 연결 실패 — 다음 경로 시도"
done
if [ -z "$TARGET" ]; then
  echo "[deploy] LAN/Tailscale/WAN 모두 연결 실패. a1 서버 상태와 Tailscale 연결을 확인하세요."
  exit 1
fi

# 2. 동기화: 로컬 app -> 타겟 chungu-app/app (env 파일 제외)
# a1의 chungu-app/은 repo root이며, 실제 앱 코드는 chungu-app/app/ 아래에 있다.
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
  $TARGET:~/chungu-app/app/

# 3. 이미지 재빌드 및 재시작
ssh $TARGET 'cd ~/chungu-app/app && COMPOSE_PROJECT_NAME=chungu-app docker compose down && COMPOSE_PROJECT_NAME=chungu-app docker compose up --build -d'

# 4. 상태 확인
sleep 5
ssh $TARGET 'cd ~/chungu-app/app && COMPOSE_PROJECT_NAME=chungu-app docker compose ps'
