#!/usr/bin/env python3
"""[Flow: Step 1 (_load_all_annotations 헬퍼 단위 테스트) -> Step 2 (다양한 Storage 상황 mock)
      -> Step 3 (AI 주석 / 사용자 주석 / 중복 제거 / page_no 필터링 검증)]

백엔드 _load_all_annotations 헬퍼가 의도대로 동작하는지 검증한다.
- 케이스 1: AI 주석도 없고 사용자 주석도 없으면 빈 리스트 반환 (404 아님)
- 케이스 2: AI 주석만 있으면 AI 주석 반환
- 케이스 3: 사용자 주석만 있으면 사용자 주석 반환 (AI 주석 경로가 None이어도 OK)
- 케이스 4: AI 주석 + 사용자 주석이 모두 있으면 병합 (ID 중복 제거)
- 케이스 5: 파일별 user_annotations_{source_index}.json이 없으면 공유 user_annotations.json으로 폴백
- 케이스 6: page_no 필터링이 0-based pageIndex와 올바르게 매칭되는지 확인
- 케이스 7: _resolve_annotations_json_path가 None을 반환하는 job에서도 에러 없이 동작
"""
import sys
import os
import json
from unittest.mock import patch, MagicMock

# [Flow: backend 패키지 루트를 sys.path에 추가 — backend.api.jobs 임포트용]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

from backend.api.jobs import _load_all_annotations, _resolve_annotations_json_path
from backend.db.models import Job


# ─── 테스트 유틸 ─────────────────────────────────────────────
PASS = 0
FAIL = 0


def check(label, actual, expected):
    """[Flow: Step 1 (실제 값과 기대 값 비교) -> Step 2 (일치하면 PASS, 아니면 FAIL)]"""
    global PASS, FAIL
    ok = actual == expected
    status = "PASS" if ok else "FAIL"
    if ok:
        PASS += 1
    else:
        FAIL += 1
    print(f"  [{status}] {label}")
    if not ok:
        print(f"         expected: {expected}")
        print(f"         actual:   {actual}")
    return ok


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ─── Mock Storage 팩토리 ─────────────────────────────────────
def make_mock_storage(files: dict[str, bytes]):
    """[Flow: Step 1 (파일 경로→바이트 맵 수신) -> Step 2 (download 시 해당 파일 반환 또는 예외)
          -> Step 3 (mock client 반환)]

    @param files Storage 경로를 키로, 바이트를 값으로 하는 dict. 없는 경로는 예외 발생.
    @returns supabase_client.get_service_client()를 대체할 MagicMock
    """

    class FakeBucket:
        def download(self, path: str) -> bytes:
            if path not in files:
                raise FileNotFoundError(f"Storage path not found: {path}")
            return files[path]

    class FakeStorage:
        def from_(self, bucket: str):
            return FakeBucket()

    mock_client = MagicMock()
    mock_client.storage = FakeStorage()
    return mock_client


def make_job(
    job_id: str = "test-job-001",
    annotated_pdf_files: list | None = None,
    original_filename: str = "test.pdf",
) -> Job:
    """[Flow: Step 1 (Job 모델 인스턴스 생성) -> Step 2 (필수 필드 설정) -> Step 3 (반환)]

    DB 세션 없이 테스트하기 위해 Job 인스턴스를 직접 생성한다.
    """
    job = Job()
    job.id = job_id
    job.annotated_pdf_files = annotated_pdf_files or []
    job.original_filename = original_filename
    return job


def _annot(annot_id: str, page_index: int, contents: str = "") -> dict:
    """[Flow: EmbedPDF AnnotationTransferItem 형식 주석 딕셔너리 생성]"""
    return {
        "annotation": {
            "id": annot_id,
            "type": 9,
            "pageIndex": page_index,
            "rect": {"origin": {"x": 10, "y": 20}, "size": {"width": 100, "height": 30}},
            "color": "#FFEB3B",
            "strokeColor": "#FFEB3B",
            "opacity": 0.5,
            "contents": contents,
        }
    }


def _annotations(result):
    """[Flow: _load_all_annotations의 dict 응답에서 annotations 배열 추출]"""
    if isinstance(result, dict) and "annotations" in result:
        return result["annotations"]
    return result


# ─── 테스트 1: AI 주석도 사용자 주석도 없으면 빈 annotations 배열 ───
def test_no_annotations_returns_empty():
    section("테스트 1: 주석이 전혀 없으면 빈 annotations 배열 반환 (404 아님)")

    job = make_job(annotated_pdf_files=[])
    mock_client = make_mock_storage({})

    with patch("backend.api.jobs.supabase_client.get_service_client", return_value=mock_client):
        result = _load_all_annotations(job, source_index=0)

    check("빈 annotations 배열 반환", _annotations(result), [])


# ─── 테스트 2: AI 주석만 있으면 AI 주석 반환 ───
def test_ai_annotations_only():
    section("테스트 2: AI 주석만 있으면 AI 주석 반환")

    ai_annots = [_annot("ai-1", 0, "AI 하이라이트"), _annot("ai-2", 1, "AI 하이라이트 2")]
    job = make_job(
        annotated_pdf_files=[
            {
                "index": 1,
                "status": "done",
                "storage_path": "test-job-001/annotated_1.pdf",
                "annotations_json_storage_path": "test-job-001/annotated_1.annotations.json",
                "filename": "test_annotation1.pdf",
            }
        ],
    )
    mock_client = make_mock_storage({
        "test-job-001/annotated_1.annotations.json": json.dumps(ai_annots).encode("utf-8"),
    })

    with patch("backend.api.jobs.supabase_client.get_service_client", return_value=mock_client):
        result = _load_all_annotations(job, source_index=0)

    check("AI 주석 2개 반환", len(_annotations(result)), 2)
    check("첫 번째 주석 ID", _annotations(result)[0]["annotation"]["id"], "ai-1")
    check("두 번째 주석 ID", _annotations(result)[1]["annotation"]["id"], "ai-2")


# ─── 테스트 3: 사용자 주석만 있으면 사용자 주석 반환 (AI 경로 None) ───
def test_user_annotations_only_no_ai_path():
    section("테스트 3: AI 주석 경로가 None이어도 사용자 주석 반환")

    user_annots = [_annot("user-1", 0, "사용자 하이라이트")]
    job = make_job(annotated_pdf_files=[])
    mock_client = make_mock_storage({
        "test-job-001/user_annotations_0.json": json.dumps(user_annots).encode("utf-8"),
    })

    with patch("backend.api.jobs.supabase_client.get_service_client", return_value=mock_client):
        result = _load_all_annotations(job, source_index=0)

    check("사용자 주석 1개 반환", len(_annotations(result)), 1)
    check("주석 ID", _annotations(result)[0]["annotation"]["id"], "user-1")


# ─── 테스트 4: AI 주석 + 사용자 주석 병합 (ID 중복 제거) ───
def test_merge_ai_and_user_with_dedup():
    section("테스트 4: AI 주석 + 사용자 주석 병합 (ID 중복 제거)")

    # AI 주석과 동일한 ID를 가진 사용자 주석은 중복 제거되어야 함
    ai_annots = [_annot("shared-id", 0, "AI 주석"), _annot("ai-only", 1, "AI 전용")]
    user_annots = [_annot("shared-id", 0, "사용자 덮어쓰기"), _annot("user-only", 2, "사용자 전용")]
    job = make_job(
        annotated_pdf_files=[
            {
                "index": 1,
                "status": "done",
                "storage_path": "test-job-001/annotated_1.pdf",
                "annotations_json_storage_path": "test-job-001/annotated_1.annotations.json",
                "filename": "test_annotation1.pdf",
            }
        ],
    )
    mock_client = make_mock_storage({
        "test-job-001/annotated_1.annotations.json": json.dumps(ai_annots).encode("utf-8"),
        "test-job-001/user_annotations_0.json": json.dumps(user_annots).encode("utf-8"),
    })

    with patch("backend.api.jobs.supabase_client.get_service_client", return_value=mock_client):
        result = _load_all_annotations(job, source_index=0)

    # shared-id는 AI 주석이 먼저 들어가고 사용자 주석은 중복 제거되어야 함
    ids = [a["annotation"]["id"] for a in _annotations(result)]
    check("병합 후 3개 (중복 제거)", len(_annotations(result)), 3)
    check("shared-id 1개만", ids.count("shared-id"), 1)
    check("ai-only 포함", "ai-only" in ids, True)
    check("user-only 포함", "user-only" in ids, True)
    # AI 주석이 먼저 로드되므로 shared-id의 contents는 AI 것
    shared = next(a for a in _annotations(result) if a["annotation"]["id"] == "shared-id")
    check("shared-id는 AI 주석 우선", shared["annotation"]["contents"], "AI 주석")


# ─── 테스트 5: 파일별 주석이 없으면 공유 user_annotations.json으로 폴백 ───
def test_fallback_to_shared_user_annotations():
    section("테스트 5: 파일별 주석이 없으면 공유 user_annotations.json으로 폴백")

    user_annots = [_annot("user-fallback", 0, "폴백 주석")]
    job = make_job(annotated_pdf_files=[])
    # user_annotations_0.json은 없고, user_annotations.json만 있음
    mock_client = make_mock_storage({
        "test-job-001/user_annotations.json": json.dumps(user_annots).encode("utf-8"),
    })

    with patch("backend.api.jobs.supabase_client.get_service_client", return_value=mock_client):
        result = _load_all_annotations(job, source_index=0)

    check("폴백 주석 1개 반환", len(_annotations(result)), 1)
    check("주석 ID", _annotations(result)[0]["annotation"]["id"], "user-fallback")


# ─── 테스트 6: page_no 필터링 (0-based pageIndex 매칭) ───
def test_page_no_filtering():
    section("테스트 6: page_no 필터링 (1-based page_no → 0-based pageIndex)")

    ai_annots = [
        _annot("ai-page1", 0, "1페이지"),
        _annot("ai-page2", 1, "2페이지"),
        _annot("ai-page3", 2, "3페이지"),
    ]
    job = make_job(
        annotated_pdf_files=[
            {
                "index": 1,
                "status": "done",
                "storage_path": "test-job-001/annotated_1.pdf",
                "annotations_json_storage_path": "test-job-001/annotated_1.annotations.json",
                "filename": "test_annotation1.pdf",
            }
        ],
    )
    mock_client = make_mock_storage({
        "test-job-001/annotated_1.annotations.json": json.dumps(ai_annots).encode("utf-8"),
    })

    with patch("backend.api.jobs.supabase_client.get_service_client", return_value=mock_client):
        # page_no=2 → pageIndex=1만 반환
        result_page2 = _load_all_annotations(job, source_index=0, page_no=2)
        # page_no=1 → pageIndex=0만 반환
        result_page1 = _load_all_annotations(job, source_index=0, page_no=1)

    check("page_no=2 → 1개", len(_annotations(result_page2)), 1)
    check("page_no=2 → pageIndex=1 주석", _annotations(result_page2)[0]["annotation"]["id"], "ai-page2")
    check("page_no=1 → 1개", len(_annotations(result_page1)), 1)
    check("page_no=1 → pageIndex=0 주석", _annotations(result_page1)[0]["annotation"]["id"], "ai-page1")


# ─── 테스트 7: _resolve_annotations_json_path가 None을 반환하는 job ───
def test_resolve_returns_none_no_error():
    section("테스트 7: _resolve_annotations_json_path가 None이어도 에러 없음")

    # annotated_pdf_files가 없으면 None 반환
    job = make_job(annotated_pdf_files=[])
    path = _resolve_annotations_json_path(job, source_index=0)
    check("_resolve_annotations_json_path → None", path, None)

    # _load_all_annotations도 에러 없이 빈 리스트 반환
    mock_client = make_mock_storage({})
    with patch("backend.api.jobs.supabase_client.get_service_client", return_value=mock_client):
        result = _load_all_annotations(job, source_index=0)
    check("None 경로 시 빈 annotations 배열", _annotations(result), [])


# ─── 테스트 8: source_index별 다른 파일 로드 ───
def test_source_index_isolation():
    section("테스트 8: source_index별 다른 사용자 주석 파일 로드")

    user_0 = [_annot("user-idx0", 0, "파일 0 주석")]
    user_1 = [_annot("user-idx1", 1, "파일 1 주석")]
    job = make_job(annotated_pdf_files=[])
    mock_client = make_mock_storage({
        "test-job-001/user_annotations_0.json": json.dumps(user_0).encode("utf-8"),
        "test-job-001/user_annotations_1.json": json.dumps(user_1).encode("utf-8"),
    })

    with patch("backend.api.jobs.supabase_client.get_service_client", return_value=mock_client):
        result_0 = _load_all_annotations(job, source_index=0)
        result_1 = _load_all_annotations(job, source_index=1)

    check("source_index=0 → idx0 주석", _annotations(result_0)[0]["annotation"]["id"], "user-idx0")
    check("source_index=1 → idx1 주석", _annotations(result_1)[0]["annotation"]["id"], "user-idx1")


# ─── 메인 ─────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  _load_all_annotations 헬퍼 테스트 시작")
    print("=" * 60)

    test_no_annotations_returns_empty()
    test_ai_annotations_only()
    test_user_annotations_only_no_ai_path()
    test_merge_ai_and_user_with_dedup()
    test_fallback_to_shared_user_annotations()
    test_page_no_filtering()
    test_resolve_returns_none_no_error()
    test_source_index_isolation()

    print(f"\n{'='*60}")
    print(f"  결과: {PASS} passed, {FAIL} failed")
    print(f"{'='*60}")

    sys.exit(0 if FAIL == 0 else 1)
