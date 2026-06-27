#!/bin/bash
set -e

# [Flow: Step 1 (LAN 접속 시도) -> Step 2 (실패 시 WAN fallback) -> Step 3 (rsync 동기화) -> Step 4 (Docker 재빌드/재시작) -> Step 5 (상태 확인)]

TARGET=""

# 1. 접속 경로 선택: LAN 우선, 실패 시 WAN fallback
if ssh -o ConnectTimeout=5 -o BatchMode=yes a1 "true" 2>/dev/null; then
  TARGET=a1
  echo "[deploy] LAN 경로(a1)로 연결됨"
else
  echo "[deploy] LAN 경로 실패, WAN 경로(wan-1)로 fallback"
  if ssh -o ConnectTimeout=10 -o BatchMode=yes wan-1 "true" 2>/dev/null; then
    TARGET=wan-1
    echo "[deploy] WAN 경로(wan-1)로 연결됨"
  else
    echo "[deploy] LAN/WAN 모두 연결 실패. a1 서버 상태를 확인하세요."
    exit 1
  fi
fi

# 2. 동기화: 로컬 app -> 타겟 chungu-app (env 파일 제외)
rsync -avz --delete \
  --exclude='.env' \
  --exclude='node_modules' \
  --exclude='__pycache__' \
  --exclude='.pyc' \
  --exclude='dist' \
  --exclude='.vite' \
  --exclude='docs/build' \
  --exclude='docs/.docusaurus' \
  /Users/jun16/repo/chungu/app/ \
  $TARGET:~/chungu-app/

# 3. 이미지 재빌드 및 재시작
ssh $TARGET 'cd ~/chungu-app && docker compose down && docker compose up --build -d'

# 4. 상태 확인
sleep 5
ssh $TARGET 'cd ~/chungu-app && docker compose ps'
