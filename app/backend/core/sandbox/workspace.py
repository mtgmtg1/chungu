#!/usr/bin/env python3
"""PROOF Sandbox Workspace Manager — 결과 파일 준비 및 git 초기화

[Flow: Step 1 (workspace 디렉토리 생성) -> Step 2 (Supabase Storage에서 결과 파일 다운로드)
  -> Step 3 (디렉토리 구조 구성) -> Step 4 (git 초기화)]

이 모듈은 Kata VM 시작 전에 /data/jobs/{job_id} 디렉토리를 준비한다.
결과 페이지의 원본 파일, 추출 결과, 주석 JSON 을 다운로드하여 구성한다.
"""

import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# workspace 디렉토리 구조
WORKSPACE_SUBDIRS = ["original", "extracted", "annotations", "agent_output", ".agent_log"]


class WorkspaceManager:
    """sandbox workspace 를 준비하고 관리하는 클래스.

    각 sandbox 의 workspace 는 /data/jobs/{job_id} 에 생성된다.
    Kata VM 은 이 디렉토리를 virtio-fs 로 /workspace 에 마운트한다.
    """

    def __init__(self, workspace_root: Path = Path("/data/jobs")):
        """WorkspaceManager 초기화.

        매개변수:
            workspace_root: workspace 루트 디렉토리 (기본: /data/jobs)
        """
        self.workspace_root = workspace_root

    def prepare_workspace(self, job_id: str, user_id: str) -> Path:
        """sandbox workspace 를 준비한다.

        [Flow: 디렉토리 생성 -> 결과 파일 다운로드 -> git 초기화]

        매개변수:
            job_id: Job ID
            user_id: 사용자 ID

        반환값:
            workspace 경로 (Path)
        """
        workspace_path = self.workspace_root / job_id

        # Step 1: 디렉토리 구조 생성
        self._create_directory_structure(workspace_path)

        # Step 2: 결과 파일 다운로드 (Supabase Storage에서)
        # 실제 구현은 supabase_client 를 사용하여 다운로드
        # 여기서는 디렉토리만 준비하고, 파일 다운로드는 별도 메서드로 분리
        logger.info("workspace 준비: %s (job=%s, user=%s)", workspace_path, job_id, user_id)

        # Step 3: git 초기화
        self._init_git(workspace_path)

        # Step 4: git 초기화 후 생성된 .git 디렉토리 소유자 변경
        # _create_directory_structure 에서 chown 을 먼저 하지만, git init/commit 이
        # root 권한으로 실행되어 .git 내부 파일이 root 소유가 되므로 다시 변경.
        try:
            import os
            for item in workspace_path.rglob("*"):
                os.chown(item, 1000, 1000)
            os.chown(workspace_path, 1000, 1000)
        except PermissionError:
            logger.warning("workspace 소유자 재변경 실패 (권한 없음): %s", workspace_path)
        except Exception as e:
            logger.warning("workspace 소유자 재변경 중 오류: %s", e)

        return workspace_path

    def _create_directory_structure(self, workspace_path: Path) -> None:
        """workspace 디렉토리 구조를 생성한다.

        [Flow: 디렉토리 생성 -> .gitignore 작성 -> 소유자를 agent(1000:1000)로 변경]

        Kata VM 컨테이너는 --user 1000:1000 으로 실행되므로,
        workspace 디렉토리의 소유자를 1000:1000 으로 변경해야 쓰기 가능.

        매개변수:
            workspace_path: workspace 루트 경로
        """
        workspace_path.mkdir(parents=True, exist_ok=True)

        for subdir in WORKSPACE_SUBDIRS:
            (workspace_path / subdir).mkdir(exist_ok=True)

        # .gitignore 생성
        gitignore_path = workspace_path / ".gitignore"
        if not gitignore_path.exists():
            gitignore_path.write_text(
                "# 에이전트 로그\n.agent_log/\n\n"
                "# 임시 파일\n*.tmp\n*.bak\n*~\n\n"
                "# Python 캐시\n__pycache__/\n*.pyc\n*.pyo\n\n"
                "# Node.js\nnode_modules/\nnpm-debug.log*\n",
                encoding="utf-8",
            )

        # 소유자를 agent(UID 1000, GID 1000)로 변경
        # backend 컨테이너는 privileged 모드로 실행되므로 chown 가능
        try:
            import os
            for item in workspace_path.rglob("*"):
                os.chown(item, 1000, 1000)
            os.chown(workspace_path, 1000, 1000)
        except PermissionError:
            logger.warning("workspace 소유자 변경 실패 (권한 없음): %s", workspace_path)
        except Exception as e:
            logger.warning("workspace 소유자 변경 중 오류: %s", e)

    def _init_git(self, workspace_path: Path) -> None:
        """workspace 에 git 저장소를 초기화한다.

        매개변수:
            workspace_path: workspace 루트 경로
        """
        git_dir = workspace_path / ".git"
        if git_dir.exists():
            logger.debug("git 저장소 이미 존재: %s", workspace_path)
            return

        try:
            subprocess.run(
                ["git", "init"], cwd=workspace_path, capture_output=True, check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "PROOF Agent"],
                cwd=workspace_path, capture_output=True, check=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "agent@proof.local"],
                cwd=workspace_path, capture_output=True, check=True,
            )
            # 초기 커밋
            subprocess.run(
                ["git", "add", ".gitignore"],
                cwd=workspace_path, capture_output=True, check=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "Initial commit: workspace initialized", "--allow-empty"],
                cwd=workspace_path, capture_output=True, check=True,
            )
            logger.info("git 초기화 완료: %s", workspace_path)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.warning("git 초기화 실패 (무시): %s", e)

    def download_job_files(
        self,
        workspace_path: Path,
        job_data: dict[str, Any],
        supabase_client: Any | None = None,
    ) -> dict[str, int]:
        """Job 의 결과 파일을 Supabase Storage 에서 workspace 로 다운로드한다.

        [Flow: 원본 파일 다운로드 -> 추출 결과 다운로드 -> 주석 JSON 다운로드]

        매개변수:
            workspace_path: workspace 루트 경로
            job_data: Job 데이터 (extracted_files, annotated_pdf_files 등)
            supabase_client: Supabase 클라이언트 (None 이면 스킵)

        반환값:
            {"original": int, "extracted": int, "annotations": int} 다운로드 파일 수
        """
        counts = {"original": 0, "extracted": 0, "annotations": 0}

        if supabase_client is None:
            logger.warning("supabase_client 가 없어 파일 다운로드를 스킵합니다")
            return counts

        # 원본 파일 다운로드
        original_files = job_data.get("original_files", [])
        for f in original_files:
            storage_path = f.get("storage_path")
            filename = f.get("filename", "unknown")
            if storage_path:
                dest = workspace_path / "original" / filename
                try:
                    supabase_client.storage.from_("jobs").download(storage_path, str(dest))
                    counts["original"] += 1
                except Exception as e:
                    logger.warning("원본 파일 다운로드 실패: %s -> %s", storage_path, e)

        # 추출 결과 다운로드
        extracted_files = job_data.get("extracted_files", [])
        for f in extracted_files:
            storage_path = f.get("storage_path")
            filename = f.get("filename", "unknown")
            if storage_path:
                dest = workspace_path / "extracted" / filename
                try:
                    supabase_client.storage.from_("jobs").download(storage_path, str(dest))
                    counts["extracted"] += 1
                except Exception as e:
                    logger.warning("추출 결과 다운로드 실패: %s -> %s", storage_path, e)

        # 주석 JSON 다운로드
        annotation_files = job_data.get("annotated_pdf_files", [])
        for f in annotation_files:
            storage_path = f.get("annotations_storage_path")
            if storage_path:
                dest = workspace_path / "annotations" / f"{f.get('annotation_index', 0)}.json"
                try:
                    supabase_client.storage.from_("jobs").download(storage_path, str(dest))
                    counts["annotations"] += 1
                except Exception as e:
                    logger.warning("주석 JSON 다운로드 실패: %s -> %s", storage_path, e)

        logger.info(
            "파일 다운로드 완료: original=%d, extracted=%d, annotations=%d",
            counts["original"], counts["extracted"], counts["annotations"],
        )
        return counts

    def cleanup_workspace(self, workspace_path: Path, preserve_days: int = 7) -> bool:
        """workspace 를 정리한다 (보존 기간 경과 시).

        매개변수:
            workspace_path: workspace 루트 경로
            preserve_days: 보존 기간 (일)

        반환값:
            정리 성공 여부
        """
        if not workspace_path.exists():
            return True

        # 수정 시간 확인
        import time
        mtime = workspace_path.stat().st_mtime
        age_seconds = time.time() - mtime
        if age_seconds < preserve_days * 86400:
            logger.debug("workspace 보존 (age=%.1f일): %s", age_seconds / 86400, workspace_path)
            return False

        try:
            import shutil
            shutil.rmtree(workspace_path)
            logger.info("workspace 정리 완료: %s", workspace_path)
            return True
        except Exception as e:
            logger.error("workspace 정리 실패: %s -> %s", workspace_path, e)
            return False
