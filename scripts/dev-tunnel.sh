#!/usr/bin/env bash
# [Flow: Step 1 (SSH 키 자동 탐색) -> Step 2 (LAN SSH 연결 시도) -> Step 3 (실패 시 WAN SSH 연결) -> Step 4 (28181/backend, 28000/Supabase 포트 로컬 포워드)]
# 사용법:
#   ./scripts/dev-tunnel.sh
#   SSH_KEY=~/.ssh/a1.pem A1_WAN_HOST=wan.a1.example.com ./scripts/dev-tunnel.sh
# 터널이 연결되면 별도 터미널에서 Vite 개발 서버를 실행하세요:
#   VITE_DEV_BACKEND_URL=http://localhost:28181 npm run dev

set -euo pipefail

LOCAL_BACKEND_PORT=${LOCAL_BACKEND_PORT:-28181}
LOCAL_SUPABASE_PORT=${LOCAL_SUPABASE_PORT:-28000}
A1_LAN_IP=${A1_LAN_IP:-192.168.1.50}
A1_USER=${A1_USER:-jun}
A1_WAN_HOST=${A1_WAN_HOST:-}
SSH_KEY_DIR=${SSH_KEY_DIR:-$HOME/Documents/ssh-key-backup}
SSH_KEY=${SSH_KEY:-}

# SSH 키 파일을 찾습니다.
if [ -z "$SSH_KEY" ] && [ -d "$SSH_KEY_DIR" ]; then
  SSH_KEY=$(find "$SSH_KEY_DIR" -maxdepth 1 -type f | head -n 1)
fi

if [ -z "$SSH_KEY" ] || [ ! -f "$SSH_KEY" ]; then
  echo "오류: SSH 키를 찾을 수 없습니다." >&2
  echo "SSH_KEY_DIR 또는 SSH_KEY 환경변수를 설정하고, ~/Documents/ssh-key-backup/에 키가 있는지 확인하세요." >&2
  exit 1
fi

echo "사용할 SSH 키: $SSH_KEY"

run_tunnel() {
  local host=$1
  echo "SSH 터널링 시도: ${A1_USER}@${host} -> local ${LOCAL_BACKEND_PORT}(backend), ${LOCAL_SUPABASE_PORT}(supabase)"
  ssh -i "$SSH_KEY" -o ConnectTimeout=5 \
      -L "${LOCAL_BACKEND_PORT}:localhost:28181" \
      -L "${LOCAL_SUPABASE_PORT}:localhost:28000" \
      "${A1_USER}@${host}" -N
}

echo "a1로 SSH 터널링을 시작합니다. 종료하려면 Ctrl+C를 누르세요."

if run_tunnel "$A1_LAN_IP"; then
  echo "LAN 터널이 종료되었습니다."
elif [ -n "$A1_WAN_HOST" ]; then
  echo "LAN 연결 실패. WAN(${A1_WAN_HOST})으로 시도합니다."
  run_tunnel "$A1_WAN_HOST"
else
  echo "LAN 연결에 실패했고, WAN 호스트가 설정되지 않았습니다." >&2
  echo "A1_WAN_HOST 환경변수를 설정하거나, a1의 WAN 접속 정보를 스크립트에 채워넣으세요." >&2
  exit 1
fi
