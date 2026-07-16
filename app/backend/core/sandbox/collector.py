#!/usr/bin/env python3
"""PROOF Sandbox Result Collector — sandbox 결과 파일 수집 및 Supabase Storage 업로드

[Flow: Step 1 (workspace 파일 스캔) -> Step 2 (변경 파일 식별 via git diff)
  -> Step 3 (Supabase Storage 업로드) -> Step 4 (DB job 레코드 업데이트)]

이 모듈은 sandbox 종료 후 workspace 의 변경된 파일을 수집하여
Supabase Storage 에 업로드하고 Job 레코드를 업데이트한다.
"""

import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 수집 대상 디렉토리 (workspace 하위)
COLLECT_DIRS = ["agent_output", "extracted", "annotations"]
# 수집 대상 파일 확장자
COLLECT_EXTENSIONS = {
    ".csv", ".md", ".xlsx", ".json", ".txt", ".html",
    ".png", ".jpg", ".jpeg", ".pdf", ".svg",
    ".mp3", ".wav", ".mp4", ".webm",
    ".zip", ".tar", ".gz",
    # 문서 미리보기 변환 대상
    ".pptx", ".ppt", ".ppsx", ".pps",
    ".docx", ".doc",
    ".hwp", ".hwpx",
}


class ResultCollector:
    """sandbox 결과 파일을 수집하여 Supabase Storage 에 업로드하는 클래스.

    [Flow: scan_workspace -> identify_changed_files -> upload_to_storage -> update_job_record]
    """

    def __init__(self, workspace_root: Path = Path("/data/jobs")):
        """ResultCollector 초기화.

        매개변수:
            workspace_root: workspace 루트 디렉토리
        """
        self.workspace_root = workspace_root

    def scan_workspace(self, workspace_path: Path) -> list[dict[str, Any]]:
        """workspace 내 수집 대상 파일을 스캔한다.

        [Flow: COLLECT_DIRS 순회 -> 확장자 필터 -> 파일 정보 수집]

        매개변수:
            workspace_path: workspace 루트 경로

        반환값:
            [{"path": str, "relative_path": str, "size": int, "extension": str}]
        """
        files = []

        for subdir in COLLECT_DIRS:
            dir_path = workspace_path / subdir
            if not dir_path.exists():
                continue

            for file_path in dir_path.rglob("*"):
                if not file_path.is_file():
                    continue
                if file_path.suffix.lower() not in COLLECT_EXTENSIONS:
                    continue

                stat = file_path.stat()
                files.append({
                    "path": str(file_path),
                    "relative_path": str(file_path.relative_to(workspace_path)),
                    "size": stat.st_size,
                    "extension": file_path.suffix.lower(),
                    "modified_at": stat.st_mtime,
                })

        logger.info("workspace 스캔 완료: %d개 파일 (%s)", len(files), workspace_path)
        return files

    def identify_changed_files(
        self,
        workspace_path: Path,
        since_commit: str | None = None,
    ) -> list[str]:
        """git diff 로 변경된 파일을 식별한다.

        매개변수:
            workspace_path: workspace 루트 경로
            since_commit: 이 커밋 이후 변경된 파일만 (None 이면 uncommitted 변경사항)

        반환값:
            변경된 파일의 상대 경로 리스트
        """
        try:
            if since_commit:
                cmd = ["git", "diff", "--name-only", since_commit, "HEAD"]
            else:
                # uncommitted + untracked
                cmd = ["git", "status", "--porcelain", "--untracked-files"]

            result = subprocess.run(
                cmd, cwd=workspace_path, capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                logger.warning("git diff 실패: %s", result.stderr)
                return []

            changed = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                # git status --porcelain 형식: "XY filename"
                # git diff --name-only 형식: "filename"
                parts = line.split(None, 1)
                filename = parts[-1] if parts else ""
                if filename:
                    changed.append(filename)

            logger.info("변경 파일 식별: %d개", len(changed))
            return changed

        except Exception as e:
            logger.error("git diff 실행 실패: %s", e)
            return []

    def upload_to_storage(
        self,
        files: list[dict[str, Any]],
        job_id: str,
        supabase_client: Any | None = None,
        bucket: str = "jobs",
    ) -> dict[str, Any]:
        """수집된 파일을 Supabase Storage 에 업로드한다.

        [Flow: 파일 순회 -> storage_path 생성 -> 업로드 -> 결과 누적]

        매개변수:
            files: scan_workspace() 결과
            job_id: Job ID
            supabase_client: Supabase 클라이언트
            bucket: Storage 버킷명

        반환값:
            {"uploaded": int, "failed": int, "files": [{"path": str, "storage_path": str}]}
        """
        result = {"uploaded": 0, "failed": 0, "files": []}

        if supabase_client is None:
            logger.warning("supabase_client 가 없어 업로드를 스킵합니다")
            return result

        for f in files:
            file_path = Path(f["path"])
            relative_path = f["relative_path"]
            # storage_path: {job_id}/agent_output/{relative_path}
            storage_path = f"{job_id}/{relative_path}"

            try:
                with open(file_path, "rb") as fp:
                    supabase_client.storage.from_(bucket).upload(
                        storage_path, fp.read(),
                        {"content-type": _guess_content_type(file_path.suffix)},
                    )
                result["uploaded"] += 1
                result["files"].append({
                    "path": str(file_path),
                    "storage_path": storage_path,
                    "size": f["size"],
                })
                logger.debug("업로드 성공: %s -> %s", relative_path, storage_path)
            except Exception as e:
                result["failed"] += 1
                logger.warning("업로드 실패: %s -> %s", relative_path, e)

        logger.info(
            "Storage 업로드 완료: uploaded=%d, failed=%d (job=%s)",
            result["uploaded"], result["failed"], job_id,
        )
        return result

    def collect_and_upload(
        self,
        workspace_path: Path,
        job_id: str,
        supabase_client: Any | None = None,
        since_commit: str | None = None,
    ) -> dict[str, Any]:
        """전체 수집 파이프라인을 실행한다.

        [Flow: 스캔 -> 변경 파일 식별 -> 업로드 -> 결과 반환]

        매개변수:
            workspace_path: workspace 루트 경로
            job_id: Job ID
            supabase_client: Supabase 클라이언트
            since_commit: 이 커밋 이후 변경된 파일만

        반환값:
            {"files": [...], "uploaded": int, "failed": int}
        """
        # Step 1: workspace 스캔
        all_files = self.scan_workspace(workspace_path)

        # Step 2: 변경 파일 식별
        changed_paths = set(self.identify_changed_files(workspace_path, since_commit))

        # 변경된 파일만 필터링 (since_commit 이 None 이면 모든 파일)
        if changed_paths:
            files_to_upload = [
                f for f in all_files if f["relative_path"] in changed_paths
            ]
        else:
            files_to_upload = all_files

        # Step 3: Storage 업로드
        upload_result = self.upload_to_storage(files_to_upload, job_id, supabase_client)

        return {
            "files": upload_result["files"],
            "uploaded": upload_result["uploaded"],
            "failed": upload_result["failed"],
            "total_scanned": len(all_files),
        }


def _guess_content_type(extension: str) -> str:
    """파일 확장자에서 Content-Type 을 추측한다.

    매개변수:
        extension: 파일 확장자 (예: ".csv")

    반환값:
        MIME 타입 문자열
    """
    content_types = {
        ".csv": "text/csv",
        ".md": "text/markdown",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".json": "application/json",
        ".txt": "text/plain",
        ".html": "text/html",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".pdf": "application/pdf",
        ".svg": "image/svg+xml",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".zip": "application/zip",
        ".tar": "application/x-tar",
        ".gz": "application/gzip",
        # 문서 미리보기 변환 대상 MIME
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".ppt": "application/vnd.ms-powerpoint",
        ".ppsx": "application/vnd.openxmlformats-officedocument.presentationml.slideshow",
        ".pps": "application/vnd.ms-powerpoint",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".doc": "application/msword",
        ".hwp": "application/x-hwp",
        ".hwpx": "application/vnd.hancom.hwpx",
    }
    return content_types.get(extension.lower(), "application/octet-stream")
