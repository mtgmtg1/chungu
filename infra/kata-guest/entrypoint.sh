#!/bin/bash
# PROOF 에이전트 런타임 진입점 (Kata VM 내부에서 실행)
#
# [Flow: Step 1 (workspace 확인) -> Step 2 (git 초기화) -> Step 3 (환경 변수 설정)
#  -> Step 4 (vsock 명령 수신 대기) -> Step 5 (종료 시 결과 동기화)]
#
# 이 스크립트는 Kata VM 부팅 후 비특권 사용자(agent, UID 1000)로 실행된다.
# 호스트의 Sandbox Manager 가 vsock 을 통해 명령을 전송하면 이 스크립트가 수신하여 실행한다.

set -euo pipefail

# --- 환경 변수 ---
WORKSPACE="/workspace"
BROWSERLESS_URL="${BROWSERLESS_URL:-http://192.168.1.50:20047}"
LOG_DIR="${WORKSPACE}/.agent_log"
VSOCK_PORT=1024  # Kata agent 통신 포트

mkdir -p "${LOG_DIR}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "${LOG_DIR}/entrypoint.log"
}

# ========================================
# Step 1: workspace 확인
# ========================================
check_workspace() {
    log "Step 1: workspace 확인"

    if [[ ! -d "${WORKSPACE}" ]]; then
        log "  workspace 디렉토리 생성: ${WORKSPACE}"
        mkdir -p "${WORKSPACE}"
    fi

    # workspace 권한 확인
    if [[ "$(stat -c %u "${WORKSPACE}" 2>/dev/null || echo 0)" -ne 1000 ]]; then
        log "  workspace 권한 조정 (UID 1000)"
        chown agent:agent "${WORKSPACE}" 2>/dev/null || true
    fi

    log "  workspace 준비 완료: ${WORKSPACE}"
}

# ========================================
# Step 2: git 초기화
# ========================================
init_git() {
    log "Step 2: git 초기화"

    if [[ ! -d "${WORKSPACE}/.git" ]]; then
        cd "${WORKSPACE}"
        git init
        git config user.name "PROOF Agent"
        git config user.email "agent@proof.local"

        # .gitignore 생성
        cat > .gitignore << 'GITIGNORE'
# 에이전트 로그
.agent_log/

# 임시 파일
*.tmp
*.bak
*~

# Python 캐시
__pycache__/
*.pyc
*.pyo

# Node.js
node_modules/
npm-debug.log*

# 대용량 미디어 (별도 관리)
*.raw
GITIGNORE

        git add .gitignore
        git commit -m "Initial commit: workspace initialized" --allow-empty
        log "  git 초기화 완료"
    else
        log "  git 저장소 이미 존재"
    fi
}

# ========================================
# Step 3: 환경 변수 설정
# ========================================
setup_environment() {
    log "Step 3: 환경 변수 설정"

    # browserless URL 을 환경 변수로 export
    export BROWSERLESS_URL
    log "  BROWSERLESS_URL=${BROWSERLESS_URL}"

    # Python 경로 확인
    log "  Python: $(python3 --version 2>&1)"
    log "  Node.js: $(node --version 2>&1)"
    log "  git: $(git --version 2>&1)"

    # 문서 처리 도구 확인
    log "  LibreOffice: $(soffice --version 2>&1 | head -1 || echo 'not found')"
    log "  Pandoc: $(pandoc --version 2>&1 | head -1 || echo 'not found')"
    log "  FFmpeg: $(ffmpeg -version 2>&1 | head -1 || echo 'not found')"
    log "  Tesseract: $(tesseract --version 2>&1 | head -1 || echo 'not found')"
    log "  ImageMagick: $(magick --version 2>&1 | head -1 || echo 'not found')"
}

# ========================================
# Step 4: vsock 명령 수신 대기
# ========================================
listen_commands() {
    log "Step 4: vsock 명령 수신 대기 (포트 ${VSOCK_PORT})"

    # vsock 이 사용 가능한 경우 명령 수신 대기
    if [[ -e /dev/vsock ]]; then
        log "  vsock 장치 확인: /dev/vsock"

        # vsock 리스너 (Python 스크립트로 구현 — Bash 에서는 vsock 처리가 제한적)
        python3 -c "
import socket
import subprocess
import json
import sys
import os

VMADDR_CID_HOST = 2
VSOCK_PORT = ${VSOCK_PORT}
WORKSPACE = '${WORKSPACE}'
LOG_DIR = '${LOG_DIR}'

# 명령어 블랙리스트 (Sandbox Manager 에서도 필터링하지만 이중 방어)
import re
BLOCKED_PATTERNS = [
    r'\\brm\\s+-rf\\s+/(?!workspace)',
    r'\\bdd\\s+.*of=/dev/',
    r'\\bmkfs\\b',
    r'\\bmount\\s+',
    r'\\bumount\\b',
    r'\\bsysctl\\s+',
    r'\\binsmod\\b', r'\\brmmod\\b',
    r'\\breboot\\b', r'\\bshutdown\\b', r'\\bhalt\\b',
    r':\\(\\){.*};:',
    r'\\bcurl\\s+.*\\|\\s*sh',
    r'\\bwget\\s+.*\\|\\s*sh',
]

def is_blocked(cmd):
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, cmd):
            return True, pattern
    return False, None

def handle_command(cmd_data):
    cmd = cmd_data.get('command', '')
    if not cmd:
        return {'error': 'empty command'}

    blocked, pattern = is_blocked(cmd)
    if blocked:
        with open(f'{LOG_DIR}/blocked.log', 'a') as f:
            f.write(f'[{__import__(\"datetime\").datetime.now()}] BLOCKED ({pattern}): {cmd}\\n')
        return {'error': f'command blocked by security policy', 'pattern': pattern}

    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=300,
            cwd=WORKSPACE
        )
        return {
            'exit_code': result.returncode,
            'stdout': result.stdout,
            'stderr': result.stderr
        }
    except subprocess.TimeoutExpired:
        return {'error': 'command timeout (300s)'}
    except Exception as e:
        return {'error': str(e)}

# vsock 서버 시작
try:
    server = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
    server.bind((VMADDR_CID_ANY, VSOCK_PORT))
    server.listen(5)
    print(f'[{__import__(\"datetime\").datetime.now()}] vsock listener started on port {VSOCK_PORT}', flush=True)

    while True:
        conn, _ = server.accept()
        try:
            data = b''
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            if data:
                cmd_data = json.loads(data.decode())
                result = handle_command(cmd_data)
                conn.send(json.dumps(result).encode())
        except Exception as e:
            print(f'Error: {e}', flush=True)
        finally:
            conn.close()
except Exception as e:
    print(f'vsock listener failed: {e}', flush=True)
    print('Falling back to idle mode...', flush=True)
    # vsock 이 실패하면 idle 모드로 대기
    import time
    while True:
        time.sleep(60)
" 2>&1 | tee -a "${LOG_DIR}/vsock.log"
    else
        log "  vsock 장치 없음 — idle 모드로 대기"
        # vsock 이 없으면 무한 대기 (호스트에서 종료 시까지)
        while true; do
            sleep 60
        done
    fi
}

# ========================================
# Step 5: 종료 시 결과 동기화
# ========================================
cleanup() {
    log "Step 5: 종료 — 결과 동기화"

    # 마지막 git commit (변경사항이 있는 경우)
    cd "${WORKSPACE}"
    git add -A 2>/dev/null || true
    git diff --cached --quiet 2>/dev/null || git commit -m "Agent session end: $(date '+%Y-%m-%d %H:%M:%S')" --allow-empty 2>/dev/null || true

    log "  종료 완료"
}
trap cleanup EXIT

# ========================================
# 메인 실행
# ========================================
main() {
    log "=========================================="
    log " PROOF 에이전트 런타임 시작"
    log "=========================================="

    check_workspace
    init_git
    setup_environment
    listen_commands
}

main "$@"
