#!/usr/bin/env python3
"""PROOF Sandbox Workspace Manager — 결과 파일 준비 및 git 초기화

[Flow: Step 1 (workspace 디렉토리 생성) -> Step 2 (Supabase Storage에서 결과 파일 다운로드)
  -> Step 3 (파일명 매핑 — input.pdf → 원본 파일명) -> Step 4 (git 초기화)
  -> Step 5 (_file_mapping.json 생성)]

이 모듈은 Kata VM 시작 전에 /data/jobs/{job_id} 디렉토리를 준비한다.
결과 페이지의 원본 파일, 추출 결과, 주석 JSON 을 다운로드하여 구성한다.

파일명 매핑:
  Job 처리 파이프라인(tasks.py)은 원본 파일을 input.{확장자} 로 정규화하여 저장한다.
  sandbox workspace 는 같은 디렉토리를 마운트하므로, 사용자가 보는 파일명(예: "보고서.pdf")과
  sandbox 내부 파일명(예: "input.pdf")이 불일치한다.
  이 매니저는 original/ 디렉토리에 원본 파일명으로 파일을 배치하고,
  _file_mapping.json 으로 사용자 파일명 ↔ 실제 파일명 매핑을 제공한다.
"""

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# workspace 디렉토리 구조
WORKSPACE_SUBDIRS = ["original", "extracted", "annotations", "agent_output", ".agent_log"]

# 파일명 매핑 메타데이터 파일명
FILE_MAPPING_FILENAME = "_file_mapping.json"


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

    def prepare_workspace(
        self,
        job_id: str,
        user_id: str,
        job_data: dict[str, Any] | None = None,
    ) -> Path:
        """sandbox workspace 를 준비한다.

        [Flow: 디렉토리 생성 -> 기존 처리 파일명 매핑 -> 결과 파일 다운로드
          -> _file_mapping.json 생성 -> git 초기화 -> 소유자 변경]

        매개변수:
            job_id: Job ID
            user_id: 사용자 ID
            job_data: Job 데이터 딕셔너리 (original_filename, extracted_files,
                pdf_storage_path 등). None 이면 파일 매핑/다운로드를 스킵한다.

        반환값:
            workspace 경로 (Path)
        """
        workspace_path = self.workspace_root / job_id

        # Step 1: 디렉토리 구조 생성
        self._create_directory_structure(workspace_path)

        # Step 2: 기존 처리 파일(input.{ext})을 원본 파일명으로 original/ 에 매핑
        # tasks.py 가 work_dir(=workspace_path) 에 input.pdf 로 저장해 둔 파일을
        # original/{원본파일명} 으로 복사하여 사용자가 보는 이름으로 접근 가능하게 함.
        file_mapping: dict[str, str] = {}
        if job_data:
            file_mapping = self._map_input_files_to_original_names(workspace_path, job_data)

        # Step 3: Supabase Storage 에서 결과 파일 다운로드 (추출 결과, 주석 등)
        # job_data 가 있고 supabase_client 를 사용할 수 있는 경우에만 수행.
        # 실제 다운로드는 download_job_files 메서드로 분리 — prepare_workspace 에서는
        # 디렉토리 준비 + 기존 파일 매핑만 담당.
        logger.info(
            "workspace 준비: %s (job=%s, user=%s, mapped_files=%d)",
            workspace_path, job_id, user_id, len(file_mapping),
        )

        # Step 4: _file_mapping.json 생성 (에이전트가 사용자 파일명 → 실제 파일명 조회용)
        if file_mapping:
            self._write_file_mapping(workspace_path, file_mapping)

        # Step 5: git 초기화
        self._init_git(workspace_path)

        # Step 6: git 초기화 후 생성된 .git 디렉토리 소유자 변경
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

    def _map_input_files_to_original_names(
        self,
        workspace_path: Path,
        job_data: dict[str, Any],
    ) -> dict[str, str]:
        """tasks.py 가 저장한 input.{ext} 파일을 원본 파일명으로 original/ 에 복사한다.

        [Flow: Step 1 (job_data에서 원본 파일명 추출) -> Step 2 (input.{ext} 파일 탐색)
          -> Step 3 (original/ 디렉토리에 원본 파일명으로 복사) -> Step 4 (매핑 dict 반환)]

        tasks.py 의 단일 파일 처리 루틴은 원본 파일을 work_dir / f"input{input_ext}" 로
        저장한다. work_dir 은 workspace_path 와 동일하므로, sandbox 마운트 시
        /workspace/input.pdf 로 보인다. 사용자는 original_filename(예: "보고서.pdf")로
        파일을 참조하므로, original/ 디렉토리에 원본 파일명으로 복사본을 만든다.

        매개변수:
            workspace_path: workspace 루트 경로
            job_data: Job 데이터 (original_filename, extracted_files 포함)

        반환값:
            {사용자_파일명: sandbox_내부_경로} 매핑 딕셔너리
        """
        mapping: dict[str, str] = {}
        original_dir = workspace_path / "original"

        # Step 1: 단일 파일 Job (PDF/DOCX/HWP) — input.{ext} → 원본 파일명
        original_filename = job_data.get("original_filename", "")
        if original_filename:
            ext = Path(original_filename).suffix or ".pdf"
            input_file = workspace_path / f"input{ext}"
            if input_file.exists():
                dest = original_dir / original_filename
                try:
                    shutil.copy2(input_file, dest)
                    mapping[original_filename] = f"original/{original_filename}"
                    logger.info("파일 매핑: %s -> %s", input_file.name, dest)
                except Exception as e:
                    logger.warning("파일 매핑 실패: %s -> %s", input_file, e)

        # Step 2: 멀티미디어/아카이브 Job — extracted_files 의 각 파일을 original/ 에 배치
        # extracted_files 항목은 {"path": "파일명", "type": ..., "storage_path": ...} 구조.
        # work_dir 에 이미 파일이 있으면 복사, 없으면 Storage 에서 다운로드 필요.
        extracted_files = job_data.get("extracted_files", [])
        for f_info in extracted_files:
            if not isinstance(f_info, dict):
                continue
            filename = f_info.get("path", "") or f_info.get("filename", "")
            if not filename:
                continue
            # work_dir 루트 또는 하위 디렉토리에 파일이 있을 수 있음
            src = workspace_path / filename
            if src.exists() and src.is_file():
                dest = original_dir / Path(filename).name
                try:
                    shutil.copy2(src, dest)
                    mapping[Path(filename).name] = f"original/{Path(filename).name}"
                except Exception as e:
                    logger.warning("추출 파일 매핑 실패: %s -> %s", src, e)

        return mapping

    def _write_file_mapping(
        self,
        workspace_path: Path,
        file_mapping: dict[str, str],
    ) -> None:
        """_file_mapping.json 메타데이터 파일을 workspace 루트에 작성한다.

        에이전트가 사용자가 말하는 파일명(예: "보고서.pdf")으로 실제 sandbox 내부
        경로(예: "original/보고서.pdf")를 찾을 수 있도록 매핑 정보를 JSON 으로 저장한다.

        매개변수:
            workspace_path: workspace 루트 경로
            file_mapping: {사용자_파일명: sandbox_내부_경로} 매핑
        """
        mapping_path = workspace_path / FILE_MAPPING_FILENAME
        try:
            mapping_path.write_text(
                json.dumps(file_mapping, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("파일 매핑 메타데이터 작성: %s (%d files)", mapping_path, len(file_mapping))
        except Exception as e:
            logger.warning("파일 매핑 메타데이터 작성 실패: %s -> %s", mapping_path, e)

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

        [Flow: 원본 파일 다운로드 -> 추출 결과 다운로드 -> 주석 JSON 다운로드
          -> 파일 매핑 업데이트]

        job_data 는 Job SQLAlchemy 모델의 __dict__ 또는 수동으로 구성한 딕셔너리.
        단일 파일 Job: original_filename + pdf_storage_path 사용.
        멀티미디어 Job: extracted_files (각 항목에 storage_path 포함) 사용.

        매개변수:
            workspace_path: workspace 루트 경로
            job_data: Job 데이터 (original_filename, pdf_storage_path,
                extracted_files, annotated_pdf_files 등)
            supabase_client: Supabase 클라이언트 (None 이면 스킵)

        반환값:
            {"original": int, "extracted": int, "annotations": int} 다운로드 파일 수
        """
        counts = {"original": 0, "extracted": 0, "annotations": 0}

        if supabase_client is None:
            logger.warning("supabase_client 가 없어 파일 다운로드를 스킵합니다")
            return counts

        file_mapping: dict[str, str] = {}

        # Step 1: 원본 파일 다운로드 — 단일 파일 Job (PDF/DOCX/HWP)
        # tasks.py 가 input.{ext} 로 저장해 두지만, Storage 에서 원본 파일명으로 직접 다운로드.
        original_filename = job_data.get("original_filename", "")
        pdf_storage_path = job_data.get("pdf_storage_path", "")
        if pdf_storage_path and original_filename:
            dest = workspace_path / "original" / original_filename
            try:
                data = supabase_client.storage.from_("pdfs").download(pdf_storage_path)
                dest.write_bytes(data if isinstance(data, bytes) else data.read())
                counts["original"] += 1
                file_mapping[original_filename] = f"original/{original_filename}"
            except Exception as e:
                logger.warning("원본 파일 다운로드 실패: %s -> %s", pdf_storage_path, e)

        # Step 2: 추출 결과 다운로드 — 멀티미디어/아카이브 Job
        # extracted_files 항목: {"path": "파일명", "type": ..., "storage_path": ...,
        #   "result_markdown": ..., "searchable_pdf_storage_path": ...}
        extracted_files = job_data.get("extracted_files", [])
        for f_info in extracted_files:
            if not isinstance(f_info, dict):
                continue
            filename = f_info.get("path", "") or f_info.get("filename", "")
            storage_path = f_info.get("storage_path", "")
            if not filename:
                continue
            # 추출 결과 마크다운 저장
            result_markdown = f_info.get("result_markdown", "")
            if result_markdown:
                md_dest = workspace_path / "extracted" / f"{Path(filename).stem}.md"
                try:
                    md_dest.write_text(result_markdown, encoding="utf-8")
                    counts["extracted"] += 1
                except Exception as e:
                    logger.warning("추출 결과 저장 실패: %s -> %s", filename, e)
            # 원본 미디어 파일 (이미지/오디오/비디오) Storage 에서 다운로드
            if storage_path:
                dest = workspace_path / "original" / Path(filename).name
                try:
                    # 이미지는 images 버킷, 그 외는 pdfs 버킷일 수 있음 — storage_path 접두사로 판단
                    bucket = "images" if f_info.get("type") == "image" else "pdfs"
                    data = supabase_client.storage.from_(bucket).download(storage_path)
                    dest.write_bytes(data if isinstance(data, bytes) else data.read())
                    counts["original"] += 1
                    file_mapping[Path(filename).name] = f"original/{Path(filename).name}"
                except Exception as e:
                    logger.warning("추출 파일 다운로드 실패: %s -> %s", storage_path, e)

        # Step 3: 주석 JSON 다운로드
        annotation_files = job_data.get("annotated_pdf_files", [])
        for f in annotation_files:
            if not isinstance(f, dict):
                continue
            storage_path = f.get("annotations_storage_path", "")
            if storage_path:
                dest = workspace_path / "annotations" / f"{f.get('annotation_index', 0)}.json"
                try:
                    data = supabase_client.storage.from_("jobs").download(storage_path)
                    dest.write_bytes(data if isinstance(data, bytes) else data.read())
                    counts["annotations"] += 1
                except Exception as e:
                    logger.warning("주석 JSON 다운로드 실패: %s -> %s", storage_path, e)

        # Step 4: 파일 매핑 메타데이터 업데이트
        if file_mapping:
            self._write_file_mapping(workspace_path, file_mapping)

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
