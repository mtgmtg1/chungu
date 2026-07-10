"""PROOF Sandbox 모듈 — Kata Containers 기반 에이전트 격리 실행 환경

[Flow: SandboxManager (VM 생명주기) -> Workspace (결과 파일 준비) -> Communicator (vsock 통신)
  -> Security (명령어 필터링) -> Collector (결과 수집)]

이 패키지는 Kata Containers + Cloud Hypervisor microVM 을 관리하여
에이전트가 격리된 환경에서 문서/오디오/이미지 처리를 수행할 수 있도록 한다.
"""

from .collector import ResultCollector
from .communicator import VsockCommunicator
from .manager import SandboxManager
from .security import check_command, log_blocked_command, sanitize_command
from .workspace import WorkspaceManager

__all__ = [
    "SandboxManager",
    "WorkspaceManager",
    "VsockCommunicator",
    "ResultCollector",
    "check_command",
    "log_blocked_command",
    "sanitize_command",
]
