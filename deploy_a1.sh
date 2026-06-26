#!/bin/bash
set -e

# 1. 동기화: 로컬 app -> a1 chungu-app (env 파일 제외)
rsync -avz --delete \
  --exclude='.env' \
  --exclude='node_modules' \
  --exclude='__pycache__' \
  --exclude='.pyc' \
  --exclude='dist' \
  --exclude='.vite' \
  /Users/jun16/repo/chungu/app/ \
  a1:~/chungu-app/

# 2. a1에서 이미지 재빌드 및 재시작
ssh a1 'cd ~/chungu-app && docker compose down && docker compose up --build -d'

# 3. 상태 확인
sleep 5
ssh a1 'cd ~/chungu-app && docker compose ps'
