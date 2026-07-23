#!/usr/bin/env python3
"""PROOF Sandbox Manager — Kata Containers microVM 생명주기 관리

[Flow: Step 1 (sandbox 생성 요청) -> Step 2 (workspace 준비) -> Step 3 (Kata VM 시작)
  -> Step 4 (명령 실행/상태 조회) -> Step 5 (종료/정리)]

이 모듈은 containerd + Kata Containers + Cloud Hypervisor 를 사용하여
에이전트 격리 실행 환경(microVM)을 생성/관리/종료한다.
각 sandbox 는 1개의 Kata VM 에 대응하며, /data/jobs/{job_id} 를 virtio-fs 로 마운트한다.
"""

import json
import logging
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .communicator import VsockCommunicator
from .security import check_command, log_blocked_command, sanitize_command
from .workspace import WorkspaceManager

logger = logging.getLogger(__name__)

# --- 설정 (config.py 에서 import 하거나 환경 변수에서 로드) ---
DATA_DIR = Path("/data/jobs")
KATA_RUNTIME = "io.containerd.kata-clh.v2"
KATA_RUNTIME_DENSE = "io.containerd.kata-clh-dense.v2"
SANDBOX_IMAGE = "proof-agent:latest"  # containerd 에 로드된 에이전트 이미지
DEFAULT_TIMEOUT = 1800  # 30분
MAX_CONCURRENT = 150  # 기본 모드
MAX_CONCURRENT_DENSE = 300  # 고밀도 모드


class SandboxManager:
    """Kata Containers microVM 생명주기를 관리하는 클래스.

    [Flow: create_sandbox -> execute_command -> get_status -> destroy_sandbox]

    각 sandbox 는 1개의 Kata VM 에 대응한다.
    workspace (/data/jobs/{job_id}) 를 virtio-fs 로 VM 내부 /workspace 에 마운트한다.
    """

    def __init__(
        self,
        runtime: str = KATA_RUNTIME,
        workspace_root: Path = DATA_DIR,
        default_timeout: int = DEFAULT_TIMEOUT,
    ):
        """SandboxManager 초기화.

        매개변수:
            runtime: containerd RuntimeClass (kata-clh 또는 kata-clh-dense)
            workspace_root: workspace 루트 디렉토리 (/data/jobs)
            default_timeout: sandbox 기본 타임아웃 (초)
        """
        self.runtime = runtime
        self.workspace_root = workspace_root
        self.default_timeout = default_timeout
        self.workspace_mgr = WorkspaceManager(workspace_root)

    def _to_host_path(self, container_path: Path) -> str:
        """컨테이너 내부 경로를 호스트 경로로 변환한다.

        [Flow: /data/... -> /var/lib/docker/volumes/.../_data/... 변환]

        nerdctl 이 호스트 containerd 를 통해 sandbox VM 을 생성하므로,
        바인드 마운트 source 는 호스트의 절대 경로여야 한다.
        /data 는 Docker volume appdata 에 마운트되어 있으므로
        /var/lib/docker/volumes/chungu-app_appdata/_data 로 치환한다.

        매개변수:
            container_path: 컨테이너 내부 경로 (예: /data/jobs/{job_id})

        반환값:
            호스트 절대 경로 문자열
        """
        import os
        # 환경변수 HOST_DATA_DIR 이 있으면 사용 (명시적 매핑)
        host_data_dir = os.environ.get("HOST_DATA_DIR")
        if host_data_dir:
            return str(container_path).replace("/data", host_data_dir, 1)
        # 기본: Docker volume appdata 마운트 포인트 추정
        return str(container_path).replace(
            "/data", "/var/lib/docker/volumes/chungu-app_appdata/_data", 1
        )

    def _wait_for_container_running(self, container_name: str, timeout: int = 30) -> str:
        """컨테이너가 running 상태가 될 때까지 폴링한다.

        [Flow: nerdctl inspect 폴링 -> running 확인 또는 타임아웃]

        매개변수:
            container_name: 컨테이너 이름
            timeout: 최대 대기 시간 (초)

        반환값:
            "running" 또는 "starting" (타임아웃 시)
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            status_result = self.get_status(container_name)
            if status_result.get("status") == "running":
                return "running"
            time.sleep(2)
        return "starting"

    def create_sandbox(
        self,
        job_id: str,
        user_id: str,
        resource_limits: dict[str, Any] | None = None,
        dense_mode: bool = False,
        job_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """새 sandbox 를 생성한다.

        [Flow: workspace 준비(파일 매핑 포함) -> containerd 컨테이너 생성 -> VM 부팅 대기 -> 상태 반환]

        매개변수:
            job_id: 연결된 Job ID
            user_id: 사용자 ID
            resource_limits: CPU/memory/disk 제한 (예: {"cpu": 2, "memory_mb": 4096})
            dense_mode: 고밀도 모드 (300+ VM) 사용 여부
            job_data: Job 데이터 딕셔너리 (original_filename, extracted_files 등).
                전달하면 workspace 준비 시 파일명 매핑(input.pdf → 원본 파일명)을 수행.

        반환값:
            {"sandbox_id": str, "container_id": str, "status": "running", "workspace": str}
        """
        sandbox_id = uuid.uuid4().hex[:16]
        runtime = KATA_RUNTIME_DENSE if dense_mode else self.runtime

        logger.info("sandbox 생성 시작: id=%s, job=%s, user=%s, runtime=%s", sandbox_id, job_id, user_id, runtime)

        # Step 1: workspace 준비 (파일명 매핑 + git init)
        # job_data 가 있으면 input.{ext} → original/{원본파일명} 매핑 수행.
        workspace_path = self.workspace_mgr.prepare_workspace(job_id, user_id, job_data=job_data)

        # Step 2: containerd 컨테이너 생성 (nerdctl 또는 ctr 사용)
        container_name = f"proof-sandbox-{sandbox_id}"
        cpu_limit = resource_limits.get("cpu", 1) if resource_limits else 1
        mem_limit = resource_limits.get("memory_mb", 4096) if resource_limits else 4096

        # [Flow: 컨테이너 내부 경로 -> 호스트 경로 변환]
        # nerdctl이 호스트 containerd를 통해 실행되므로, 바인드 마운트 source 는
        # 호스트의 절대 경로여야 한다. /data 는 Docker volume appdata 에 마운트됨.
        host_workspace = self._to_host_path(workspace_path)

        cmd = [
            "nerdctl",
            "-n",
            "k8s.io",
            "run",
            "-d",
            "--runtime", runtime,
            "--name", container_name,
            "--cpus", str(cpu_limit),
            "--memory", f"{mem_limit}m",
            "--mount", f"type=bind,source={host_workspace},target=/workspace",
            # seccomp 프로필은 Kata 런타임이 게스트에 전달 (disable_guest_seccomp=false).
            # --security-opt seccomp=... 를 사용하면 Kata shim 이 capget 시스콜을 차단당해
            # "caps error: capget failure: Operation not permitted" 로 컨테이너 생성 실패.
            "--cap-drop", "ALL",
            "--cap-add", "CHOWN",
            "--cap-add", "DAC_OVERRIDE",
            "--cap-add", "FOWNER",
            "--cap-add", "FSETID",
            "--cap-add", "SETGID",
            "--cap-add", "SETUID",
            "--cap-add", "NET_BIND_SERVICE",
            "--user", "1000:1000",
            "--read-only",
            "--tmpfs", "/tmp:size=512m",
            SANDBOX_IMAGE,
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                logger.error("컨테이너 생성 실패: %s", result.stderr)
                return {
                    "sandbox_id": sandbox_id,
                    "status": "error",
                    "error": f"container creation failed: {result.stderr}",
                }

            container_id = result.stdout.strip()

            # Step 3: VM 부팅 대기 — nerdctl inspect 로 컨테이너가 running 상태가 될 때까지 폴링
            # vsock 통신이 불가능한 환경에서도 nerdctl exec 로 명령 실행이 가능하므로
            # 컨테이너 상태 기반으로 running 여부 판단.
            status = self._wait_for_container_running(container_name, timeout=30)

            # vsock 통신 시도 (선택적 — 실패해도 nerdctl exec 로 동작 가능)
            try:
                communicator = VsockCommunicator(sandbox_id, container_name)
                communicator.wait_for_ready(timeout=5)
            except Exception:
                pass  # vsock 실패는 무시 — nerdctl exec 폴백 사용

            logger.info("sandbox 생성 완료: id=%s, container=%s, status=%s", sandbox_id, container_id[:12], status)

            return {
                "sandbox_id": sandbox_id,
                "container_id": container_id,
                "container_name": container_name,
                "status": status,
                "workspace": str(workspace_path),
                "runtime": runtime,
                "resource_limits": {
                    "cpu": cpu_limit,
                    "memory_mb": mem_limit,
                },
                "created_at": datetime.now().isoformat(),
            }

        except subprocess.TimeoutExpired:
            logger.error("컨테이너 생성 타임아웃: %s", container_name)
            return {"sandbox_id": sandbox_id, "status": "error", "error": "container creation timeout"}
        except Exception as e:
            logger.error("sandbox 생성 중 예외: %s", e)
            return {"sandbox_id": sandbox_id, "status": "error", "error": str(e)}

    def execute_command(
        self,
        sandbox_id: str,
        container_name: str,
        command: str,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """sandbox 내부에서 셸 명령을 실행한다.

        [Flow: 명령어 보안 검사 -> vsock/nerdctl exec 로 실행 -> 결과 반환]

        매개변수:
            sandbox_id: sandbox ID
            container_name: 컨테이너 이름
            command: 실행할 셸 명령어
            timeout: 명령 타임아웃 (초)

        반환값:
            {"exit_code": int, "stdout": str, "stderr": str} 또는 {"error": str}
        """
        # Step 1: 명령어 보안 검사 (블랙리스트 필터링)
        allowed, reason = check_command(command)
        if not allowed:
            log_blocked_command(command, reason)
            return {"error": f"command blocked by security policy: {reason}"}

        # Step 2: 명령어 정제 (환경 변수 주입 제거)
        sanitized = sanitize_command(command)

        # Step 3: nerdctl exec 로 명령 실행
        # --workdir /workspace/agent_output: 에이전트가 상대경로로 파일을 생성하면
        # 자동으로 agent_output/ (수집 대상 디렉토리)에 저장되도록 기본 작업 디렉토리 설정.
        # 절대경로(/workspace/original/... 등)는 그대로 사용 가능.
        cmd_timeout = timeout or 300  # 기본 5분
        cmd = [
            "nerdctl",
            "-n",
            "k8s.io",
            "exec",
            "--user", "1000:1000",
            "--workdir", "/workspace/agent_output",
            container_name,
            "/bin/sh", "-c", sanitized,
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=cmd_timeout)
            return {
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except subprocess.TimeoutExpired:
            return {"error": f"command timeout ({cmd_timeout}s)"}
        except Exception as e:
            return {"error": str(e)}

    def get_status(self, container_name: str) -> dict[str, Any]:
        """sandbox 상태를 조회한다.

        매개변수:
            container_name: 컨테이너 이름

        반환값:
            {"status": "running"|"stopped"|"error", "cpu_usage": ..., "memory_usage": ...}
        """
        cmd = ["nerdctl", "-n", "k8s.io", "inspect", "--format", "{{json .State}}", container_name]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                return {"status": "error", "error": result.stderr}

            state = json.loads(result.stdout)
            return {
                "status": state.get("Status", "unknown"),
                "pid": state.get("Pid", 0),
                "started_at": state.get("StartedAt", ""),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def destroy_sandbox(self, container_name: str, workspace_path: Path | None = None) -> dict[str, Any]:
        """sandbox 를 종료하고 정리한다.

        [Flow: 컨테이너 중지 -> 컨테이너 삭제 -> workspace 정리 (옵션)]

        매개변수:
            container_name: 컨테이너 이름
            workspace_path: workspace 경로 (None 이면 정리하지 않음)

        반환값:
            {"status": "destroyed", "container": container_name}
        """
        logger.info("sandbox 종료: %s", container_name)

        # Step 1: 컨테이너 중지
        try:
            subprocess.run(["nerdctl", "-n", "k8s.io", "stop", container_name], capture_output=True, timeout=30)
        except Exception as e:
            logger.warning("컨테이너 중지 실패 (무시): %s", e)

        # Step 2: 컨테이너 삭제
        try:
            subprocess.run(["nerdctl", "-n", "k8s.io", "rm", "-f", container_name], capture_output=True, timeout=30)
        except Exception as e:
            logger.warning("컨테이너 삭제 실패 (무시): %s", e)

        # Step 3: workspace 정리 (옵션)
        if workspace_path and workspace_path.exists():
            # workspace 는 보존 기간 동안 유지 (별도 Celery task 로 정리)
            logger.info("workspace 보존: %s (별도 정리 task 가 처리)", workspace_path)

        return {"status": "destroyed", "container": container_name}

    def list_files(self, container_name: str, path: str = "/workspace") -> dict[str, Any]:
        """workspace 내 파일 목록을 조회한다.

        [Flow: nerdctl exec 로 ls -la 실행 -> 출력 파싱 -> 파일/디렉토리 목록 반환]

        매개변수:
            container_name: 컨테이너 이름
            path: 조회할 경로 (/workspace 하위)

        반환값:
            {"files": [{"name": str, "size": int, "type": "file"|"dir"}]}
        """
        cmd = [
            "nerdctl", "-n", "k8s.io", "exec", "--user", "1000:1000",
            container_name,
            "/bin/sh", "-c", f"ls -la {path} 2>/dev/null",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                return {"files": [], "error": result.stderr}

            files = []
            for line in result.stdout.strip().split("\n"):
                # 'total' 헤더 라인 스킵
                if line.startswith("total"):
                    continue
                parts = line.split(None, 8)
                if len(parts) < 9:
                    continue
                perms = parts[0]
                size = parts[4]
                name = parts[8]
                # 심볼릭 링크의 '-> target' 부분 제거
                if " -> " in name:
                    name = name.split(" -> ")[0]
                files.append({
                    "name": name,
                    "size": int(size) if size.isdigit() else 0,
                    "type": "dir" if perms.startswith("d") else "file",
                })

            return {"files": files}
        except Exception as e:
            return {"files": [], "error": str(e)}

    def read_file(self, container_name: str, path: str, max_size: int = 1024 * 1024) -> dict[str, Any]:
        """workspace 내 파일을 읽는다.

        매개변수:
            container_name: 컨테이너 이름
            path: 파일 경로 (/workspace 하위)
            max_size: 최대 읽기 크기 (바이트)

        반환값:
            {"content": str, "size": int} 또는 {"error": str}
        """
        cmd = [
            "nerdctl", "-n", "k8s.io", "exec", "--user", "1000:1000",
            container_name,
            "/bin/sh", "-c", f"cat {path} 2>/dev/null | head -c {max_size}",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode != 0:
                return {"error": result.stderr or "file not found"}
            return {"content": result.stdout, "size": len(result.stdout)}
        except Exception as e:
            return {"error": str(e)}

    def write_file(self, container_name: str, path: str, content: str) -> dict[str, Any]:
        """workspace 에 파일을 쓴다.

        [Flow: content 를 base64 인코딩 -> nerdctl exec 로 디코딩하여 파일 작성]

        stdin pipe 방식(cat > file)은 nerdctl exec + Kata 조합에서 hang 발생하므로,
        base64 인코딩된 내용을 명령어 인자로 전달하여 디코딩하는 방식 사용.

        매개변수:
            container_name: 컨테이너 이름
            path: 파일 경로 (/workspace 하위)
            content: 파일 내용

        반환값:
            {"status": "ok", "path": str} 또는 {"error": str}
        """
        import base64
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        cmd = [
            "nerdctl", "-n", "k8s.io", "exec", "--user", "1000:1000",
            container_name,
            "/bin/sh", "-c", f"echo '{encoded}' | base64 -d > {path}",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode != 0:
                return {"error": result.stderr}
            return {"status": "ok", "path": path}
        except Exception as e:
            return {"error": str(e)}

    def git_commit(self, container_name: str, message: str = "Agent changes") -> dict[str, Any]:
        """workspace 의 변경사항을 git commit 한다.

        매개변수:
            container_name: 컨테이너 이름
            message: commit 메시지

        반환값:
            {"status": "ok", "commit": str} 또는 {"error": str}
        """
        commands = [
            f"cd /workspace && git add -A",
            f"cd /workspace && git diff --cached --quiet || git commit -m '{message}' --allow-empty",
            f"cd /workspace && git rev-parse HEAD",
        ]

        results = []
        for cmd_str in commands:
            result = self.execute_command("", container_name, cmd_str, timeout=10)
            results.append(result)
            if "error" in result:
                return {"error": result["error"]}

        commit_hash = results[-1].get("stdout", "").strip()
        return {"status": "ok", "commit": commit_hash}

    def git_diff(self, container_name: str, cached: bool = False) -> dict[str, Any]:
        """git diff 를 조회한다.

        매개변수:
            container_name: 컨테이너 이름
            cached: staged 변경사항만 조회 여부

        반환값:
            {"diff": str} 또는 {"error": str}
        """
        flag = "--cached" if cached else ""
        result = self.execute_command("", container_name, f"cd /workspace && git diff {flag}", timeout=10)
        if "error" in result:
            return result
        return {"diff": result.get("stdout", "")}
