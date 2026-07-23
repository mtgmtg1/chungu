# [Flow: Step 1 (편집본/원본 마크다운 후보 생성) -> Step 2 (_get_markdown_content 호출)
#       -> Step 3 (편집본이 우선 선택되는지 검증)]
# _get_markdown_content가 edited_md와 원본 md 중 파일 마커 수가 같을 때
# edited_md를 우선 선택하는지 검증하는 회귀 테스트.
# 버그: 이전 _marker_count가 page 마커 수를 tie-breaker로 사용하여,
# save_result_page가 page 마커를 제거한 편집본보다 원본(파일+페이지 마커)이
# 더 높은 점수를 받아 편집 내용이 무시되었음.
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from unittest.mock import MagicMock, patch

from backend.api.jobs import _get_markdown_content
from backend.db.models import Job


def _make_job(
    edited_md_storage_path: str | None = None,
    md_storage_path: str | None = None,
) -> Job:
    """[Flow: 테스트용 Job 객체 생성 — storage path만 설정]"""
    job = Job()
    job.result_edited_md_storage_path = edited_md_storage_path
    job.result_md_storage_path = md_storage_path
    job.result_edited_md_path = ""
    job.result_md_path = ""
    return job


def _mock_storage_download(edited_content: str, original_content: str):
    """[Flow: Supabase storage.download을 모킹 — 경로별로 다른 내용 반환]"""
    def _download(path: str):
        if "edited_md" in path:
            return edited_content.encode("utf-8")
        return original_content.encode("utf-8")
    return _download


def test_edited_md_preferred_when_file_markers_equal():
    """[Flow: 파일 마커 수가 같으면 edited_md가 원본보다 우선 선택되어야 함]

    시나리오:
    - edited_md: `<!-- 파일 1 -->` 마커 1개, page 마커 0개 (save_result_page가 제거)
    - original_md: `<!-- 파일 1 -->` 마커 1개 + `<!-- Page 1 -->` 마커 1개
    - 기대: edited_md가 선택됨 (편집 내용 # 테스트 제목 포함)
    """
    edited = "<!-- 파일 1 -->\n\n# 테스트 제목\n\n## 내용"
    original = "<!-- 파일 1 -->\n\n<!-- Page 1 -->\n\n## 내용"
    job = _make_job(
        edited_md_storage_path="job/edited_md.md",
        md_storage_path="job/md.md",
    )

    mock_client = MagicMock()
    mock_client.storage.from_.return_value.download = _mock_storage_download(edited, original)

    with patch("backend.api.jobs.supabase_client.get_service_client", return_value=mock_client):
        result = _get_markdown_content(job)

    assert "# 테스트 제목" in result, f"편집본이 선택되어야 함. 결과: {result[:200]}"


def test_edited_md_with_test_title_reflected():
    """[Flow: 에이전트 도구로 추가한 테스트 제목이 _get_markdown_content에 반영되어야 함]

    실제 버그 재현 시나리오:
    - 에이전트가 insert_text + apply_edits로 `# 테스트 제목` 추가
    - save_result_page는 edited_md에 저장 (page 마커 제거됨)
    - 이후 preview_job이 _get_markdown_content 호출 시 edited_md를 선택해야 함
    """
    edited = "<!-- 파일 1 -->\n\n# 테스트 제목\n\n## 변호인 접견예약 확인증\n\n내용"
    original = "<!-- 파일 1 -->\n\n<!-- Page 1 -->\n\n## 변호인 접견예약 확인증\n\n내용"
    job = _make_job(
        edited_md_storage_path="job/edited_md.md",
        md_storage_path="job/md.md",
    )

    mock_client = MagicMock()
    mock_client.storage.from_.return_value.download = _mock_storage_download(edited, original)

    with patch("backend.api.jobs.supabase_client.get_service_client", return_value=mock_client):
        result = _get_markdown_content(job)

    assert "테스트 제목" in result, f"에이전트 편집 내용이 반영되어야 함. 결과: {result[:200]}"


def test_original_preferred_when_edited_has_no_file_markers():
    """[Flow: edited_md에 파일 마커가 없고 원본에만 있으면 원본이 선택되어야 함]

    이것은 기존 의도된 동작 (편집 손실 방지):
    - edited_md: 파일 마커 없음 (페이지 마커 손실된 편집본)
    - original: 파일 마커 있음
    - 기대: original이 선택됨
    """
    edited = "# 테스트 제목\n\n## 내용"
    original = "<!-- 파일 1 -->\n\n## 내용\n\n<!-- 파일 2 -->\n\n## 내용2"
    job = _make_job(
        edited_md_storage_path="job/edited_md.md",
        md_storage_path="job/md.md",
    )

    mock_client = MagicMock()
    mock_client.storage.from_.return_value.download = _mock_storage_download(edited, original)

    with patch("backend.api.jobs.supabase_client.get_service_client", return_value=mock_client):
        result = _get_markdown_content(job)

    assert "파일 2" in result, "파일 마커가 더 많은 원본이 선택되어야 함"
