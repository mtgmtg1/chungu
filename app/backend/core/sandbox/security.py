"""PROOF Sandbox 보안 모듈 — 명령어 블랙리스트 필터링

[Flow: 명령어 입력 -> 정규식 패턴 매칭 -> 차단/허용 결정 -> 로그 기록]

이 모듈은 Sandbox Manager 의 execute_command() 에서 호출되어
에이전트가 시스템 파괴 명령을 실행하지 못하도록 사전에 차단한다.
seccomp/AppArmor/capabilities 와 함께 다층 방어의 최종 레이어를 담당한다.
"""

import re
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# ========================================
# 명령어 블랙리스트 패턴
# ========================================
# 각 패턴은 정규식으로, 명령어 문자열 전체에서 매칭을 시도한다.
# 매칭 시 명령 실행을 차단하고 보안 로그에 기록한다.

BLOCKED_PATTERNS: list[Tuple[str, str]] = [
    # --- 파일시스템 파괴 ---
    # rm -rf / (단, /workspace 하위는 허용)
    (r"\brm\s+-rf?\s+/(?!workspace)\b", "rm -rf on non-workspace path"),
    (r"\brm\s+-rf?\s+/(?:bin|sbin|usr|etc|var|opt|lib|lib64|root|home|boot|dev|proc|sys)\b", "rm -rf on system directory"),
    # rm -rf ~ 또는 $HOME
    (r"\brm\s+-rf?\s+(?:~|\$HOME)", "rm -rf on home directory"),

    # --- 블록 디바이스 파괴 ---
    (r"\bdd\s+.*\bof=/dev/(?:sd|nvme|vd|xd|loop|dm|md)", "dd to block device"),
    (r"\bshred\s+/dev/", "shred on block device"),
    (r"\bmkfs(?:\.\w+)?\s+/dev/", "filesystem format on block device"),
    (r"\bfdisk\s+/dev/", "fdisk on block device"),
    (r"\bparted\s+/dev/", "parted on block device"),

    # --- 파일시스템 마운트 (seccomp/AppArmor 도 차단하지만 이중 방어) ---
    (r"\bmount\s+", "mount command"),
    (r"\bumount\b", "umount command"),

    # --- 커널 파라미터/모듈 ---
    (r"\bsysctl\s+", "sysctl command"),
    (r"\binsmod\b", "kernel module insert"),
    (r"\brmmod\b", "kernel module remove"),
    (r"\bmodprobe\b", "kernel module probe"),

    # --- 시스템 종료/재부팅 ---
    (r"\breboot\b", "reboot command"),
    (r"\bshutdown\b", "shutdown command"),
    (r"\bhalt\b", "halt command"),
    (r"\bpoweroff\b", "poweroff command"),
    (r"\binit\s+0\b", "init 0 (halt)"),
    (r"\binit\s+6\b", "init 6 (reboot)"),

    # --- 포크 밤 ---
    (r":\(\)\s*\{\s*:.*\}\s*;", "fork bomb"),

    # --- 파이프 to 셸 (원격 코드 실행) ---
    (r"\bcurl\s+.*\|\s*(?:sh|bash|zsh|dash|ksh)\b", "curl piped to shell"),
    (r"\bwget\s+.*\|\s*(?:sh|bash|zsh|dash|ksh)\b", "wget piped to shell"),
    (r"\bcurl\s+.*\|\s*python", "curl piped to python"),
    (r"\bwget\s+.*\|\s*python", "wget piped to python"),

    # --- 권한 상승 ---
    (r"\bsudo\b", "sudo command"),
    (r"\bsu\s+", "su command"),
    (r"\bchmod\s+[0-7]*s", "setuid/setgid bit"),

    # --- 네임스페이스/컨테이너 탈출 ---
    (r"\bunshare\b", "unshare command"),
    (r"\bnsenter\b", "nsenter command"),
    (r"\bdocker\b", "docker command inside sandbox"),
    (r"\bkubectl\b", "kubectl command inside sandbox"),
    (r"\bcrictl\b", "crictl command inside sandbox"),

    # --- cron/at (지속성 확보 시도) ---
    (r"\bcrontab\b", "crontab manipulation"),
    (r"\bat\s+\d", "at command scheduling"),

    # --- /proc/sys 쓰기 (커널 파라미터 변경) ---
    (r"\becho\s+.*>\s*/proc/sys/", "write to /proc/sys"),
    (r"\becho\s+.*>\s*/sys/", "write to /sys"),
]

# 컴파일된 패턴 (성능을 위해 미리 컴파일)
_COMPILED_PATTERNS: list[Tuple[re.Pattern, str]] = [
    (re.compile(pattern, re.IGNORECASE), description)
    for pattern, description in BLOCKED_PATTERNS
]


def check_command(command: str) -> Tuple[bool, Optional[str]]:
    """명령어가 블랙리스트에 매칭되는지 검사한다.

    [Flow: 명령어 입력 -> 컴파일된 패턴 순회 -> 매칭 시 차단 + 로그 -> 허용]

    매개변수:
        command: 검사할 셸 명령어 문자열

    반환값:
        (allowed, reason) 튜플:
        - allowed=True, reason=None: 명령어 허용
        - allowed=False, reason=str: 명령어 차단, reason은 차단 사유
    """
    if not command or not command.strip():
        return True, None

    for pattern, description in _COMPILED_PATTERNS:
        if pattern.search(command):
            logger.warning(
                "명령어 차단: %s | 패턴: %s | 명령: %s",
                description,
                pattern.pattern,
                command[:200],  # 로그 크기 제한
            )
            return False, description

    return True, None


def log_blocked_command(
    command: str,
    reason: str,
    log_path: Optional[Path] = None,
) -> None:
    """차단된 명령어를 보안 로그 파일에 기록한다.

    매개변수:
        command: 차단된 명령어
        reason: 차단 사유
        log_path: 로그 파일 경로 (기본: /workspace/.agent_log/blocked.log)
    """
    if log_path is None:
        log_path = Path("/workspace/.agent_log/blocked.log")

    log_path.parent.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().isoformat()
    log_entry = f"[{timestamp}] BLOCKED ({reason}): {command[:500]}\n"

    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except OSError as e:
        logger.error("보안 로그 기록 실패: %s", e)


def sanitize_command(command: str) -> str:
    """명령어에서 위험한 환경 변수 주입을 제거한다.

    매개변수:
        command: 정제할 명령어 문자열

    반환값:
        정제된 명령어 문자열
    """
    # LD_PRELOAD 주입 차단 (공유 라이브러리 강제 로드)
    command = re.sub(r"LD_PRELOAD\s*=\s*\S+\s*", "", command)
    # LD_LIBRARY_PATH 조작 차단
    command = re.sub(r"LD_LIBRARY_PATH\s*=\s*\S+\s*", "", command)
    # PYTHONPATH 조작 차단 (Python 모듈 하이재킹)
    command = re.sub(r"PYTHONPATH\s*=\s*\S+\s*", "", command)
    # NODE_OPTIONS 조작 차단 (Node.js 모듈 하이재킹)
    command = re.sub(r"NODE_OPTIONS\s*=\s*['\"]?[^'\"&|]*['\"]?\s*", "", command)

    return command
