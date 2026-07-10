#!/usr/bin/env python3
"""PROOF Sandbox Communicator — Kata VM 과 vsock 통신

[Flow: Step 1 (vsock 연결) -> Step 2 (명령 전송) -> Step 3 (결과 수신)]

이 모듈은 Kata VM 내부의 entrypoint.sh (vsock 리스너) 와 통신한다.
vsock 은 호스트-게스트 간 소켓 통신으로, 네트워크 스택을 거치지 않아 빠르다.
"""

import json
import logging
import socket
import time
from typing import Any

logger = logging.getLogger(__name__)

# vsock 상수
VMADDR_CID_HOST = 2  # 호스트 CID
VMADDR_CID_ANY = -1  # 모든 CID
VSOCK_PORT = 1024    # entrypoint.sh 의 vsock 리스너 포트
READY_TIMEOUT = 30   # VM 부팅 대기 시간 (초)


class VsockCommunicator:
    """Kata VM 과 vsock 으로 통신하는 클래스.

    [Flow: connect -> send_command -> recv_response -> close]

    vsock 을 통해 JSON 명령을 전송하고 JSON 응답을 수신한다.
    """

    def __init__(self, sandbox_id: str, container_name: str, port: int = VSOCK_PORT):
        """VsockCommunicator 초기화.

        매개변수:
            sandbox_id: sandbox ID
            container_name: 컨테이너 이름 (vsock CID 조회용)
            port: vsock 포트
        """
        self.sandbox_id = sandbox_id
        self.container_name = container_name
        self.port = port
        self.sock: socket.socket | None = None

    def _get_vsock_cid(self) -> int | None:
        """컨테이너의 vsock CID 를 조회한다.

        반환값:
            vsock CID (int) 또는 None (조회 실패 시)
        """
        # Kata VM 의 vsock CID 는 컨테이너 ID 에서 파생되거나
        # kata-runtime 명령으로 조회할 수 있다.
        # 실제 구현에서는 containerd metadata 또는 kata-agent 에서 조회.
        # 여기서는 sandbox_id 의 해시를 사용하여 가상 CID 생성.
        # 실제 환경에서는 아래 방법 중 하나를 사용:
        # 1. kata-runtime sandbox list --json 에서 vsock CID 추출
        # 2. containerd-shim-kata-v2 프로세스의 인자에서 추출
        # 3. Kata 설정에서 vsock_cid_range 사용

        # 임시: sandbox_id 해시 기반 가상 CID
        # 실제 구현 시 nerdctl inspect 또는 kata-runtime 에서 조회
        try:
            import subprocess
            result = subprocess.run(
                ["nerdctl", "inspect", "--format", "{{.State.Pid}}", self.container_name],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                pid = int(result.stdout.strip())
                # Kata VM 의 vsock CID 는 일반적으로 PID 기반이 아님
                # 실제로는 kata-runtime 에서 조회해야 함
                # 여기서는 임시로 PID 를 CID 로 사용 (실제 구현 시 수정 필요)
                return pid
        except Exception:
            pass

        return None

    def connect(self, timeout: int = 10) -> bool:
        """vsock 으로 VM 에 연결한다.

        매개변수:
            timeout: 연결 타임아웃 (초)

        반환값:
            연결 성공 여부
        """
        cid = self._get_vsock_cid()
        if cid is None:
            logger.warning("vsock CID 조회 실패, fallback to nerdctl exec")
            return False

        try:
            self.sock = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
            self.sock.settimeout(timeout)
            self.sock.connect((cid, self.port))
            logger.info("vsock 연결 성공: cid=%d, port=%d", cid, self.port)
            return True
        except Exception as e:
            logger.warning("vsock 연결 실패: %s, fallback to nerdctl exec", e)
            self.sock = None
            return False

    def send_command(self, command: str, timeout: int = 300) -> dict[str, Any]:
        """vsock 으로 명령을 전송하고 결과를 수신한다.

        매개변수:
            command: 실행할 셸 명령어
            timeout: 명령 타임아웃 (초)

        반환값:
            {"exit_code": int, "stdout": str, "stderr": str} 또는 {"error": str}
        """
        if self.sock is None:
            if not self.connect():
                return {"error": "vsock connection failed"}

        try:
            # 명령 전송
            cmd_data = json.dumps({"command": command}).encode()
            self.sock.sendall(cmd_data)
            self.sock.shutdown(socket.SHUT_WR)  # 전송 완료 신호

            # 응답 수신
            self.sock.settimeout(timeout)
            response_data = b""
            while True:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                response_data += chunk

            if response_data:
                return json.loads(response_data.decode())
            return {"error": "empty response"}

        except socket.timeout:
            return {"error": f"command timeout ({timeout}s)"}
        except Exception as e:
            return {"error": str(e)}
        finally:
            self.close()

    def close(self) -> None:
        """vsock 연결을 종료한다."""
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def wait_for_ready(self, timeout: int = READY_TIMEOUT) -> bool:
        """VM 이 준비될 때까지 대기한다.

        매개변수:
            timeout: 대기 시간 (초)

        반환값:
            VM 준비 완료 여부
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.connect(timeout=5):
                # ping 명령으로 준비 확인
                result = self.send_command("echo ready", timeout=5)
                if "stdout" in result and "ready" in result.get("stdout", ""):
                    logger.info("VM 준비 완료: %s", self.container_name)
                    return True
            time.sleep(1)

        logger.warning("VM 준비 타임아웃: %s (vsock 미지원일 수 있음, nerdctl exec 사용)", self.container_name)
        # vsock 이 지원되지 않는 경우 nerdctl exec 로 fallback
        # SandboxManager.execute_command 가 nerdctl exec 를 사용하므로
        # 여기서 False 를 반환해도 동작에는 문제 없음
        return False
