#!/usr/bin/env python3
"""[Flow: Step 1 (필요한 모듈 import) -> Step 2 (analyze_legal_profile 엔드포인트 단위 테스트)
      -> Step 3 (Job/DB/User mock) -> Step 4 (분석 성공/실패/빈 텍스트 시나리오 검증)]

POST /api/jobs/{job_id}/legal-profile/analyze 엔드포인트의 비즈니스 로직을
DB와 FastAPI 의존성 없이 직접 호출하여 검증한다.
"""
import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# [Flow: backend 패키지 루트를 sys.path에 추가]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

from backend.api.ediscovery import analyze_legal_profile


def _make_user(user_id: str = "11111111-1111-1111-1111-111111111111"):
    """테스트용 CurrentUser mock 객체를 생성한다.

    매개변수:
        user_id: 사용자 UUID 문자열
    반환값: MagicMock CurrentUser 객체
    """
    user = MagicMock()
    user.is_dev_bypass = False
    user.user_id = user_id
    return user


def _make_user_model(user_id: str = "11111111-1111-1111-1111-111111111111"):
    """테스트용 User 모델 mock 객체를 생성한다."""
    user = MagicMock()
    user.user_id = user_id
    user.language = "ko"
    return user


def _make_job(job_id: str = "job-123", user_id: str = "11111111-1111-1111-1111-111111111111", status: str = "done"):
    """테스트용 Job mock 객체를 생성한다.

    매개변수:
        job_id: Job.id 값
        user_id: Job.user_id 값
        status: Job.status 값
    반환값: MagicMock Job 객체
    """
    job = MagicMock()
    job.id = job_id
    job.user_id = user_id
    job.status = status
    job.expires_at = None
    job.created_at = datetime.now(timezone.utc)
    job.original_filename = "test.pdf"
    job.endpoint = "http://test"
    job.model = "model"
    job.total_pages = 3
    return job


def _make_db(job, user=None):
    """테스트용 DB 세션 mock 객체를 생성한다.

    매개변수:
        job: db.get(Job, id) 호출 시 반환할 Job 객체
        user: db.get(User, id) 호출 시 반환할 User 객체
    반환값: MagicMock Session 객체
    """
    user = user or _make_user_model()
    db = MagicMock()

    def _get_side_effect(model, key):
        if model.__name__ == "Job":
            return job
        if model.__name__ == "User":
            return user
        return None

    db.get.side_effect = _get_side_effect
    return db


def test_analyze_legal_profile_success():
    """정상적인 문서와 힌트가 주어지면 법률 프로필을 반환한다."""
    job = _make_job()
    db = _make_db(job)
    user = _make_user()

    expected_profile = {
        "legal_domain": "민사",
        "claim_type": "손해배상",
        "claim_summary": "원고가 피고에게 손해배상을 청구함",
        "issues": ["과실 여부"],
        "legal_elements": [],
        "confidence": 0.9,
    }

    with patch("backend.api.ediscovery.pipeline_ediscovery.extract_page_texts") as mock_extract, \
         patch("backend.api.ediscovery.legal_case_profile.extract_legal_profile") as mock_profile:
        mock_extract.return_value = ({1: "페이지 1", 2: "페이지 2", 3: "페이지 3"}, {})
        mock_profile.return_value = expected_profile

        result = analyze_legal_profile(
            "job-123",
            {"claim_type_hint": "손해배상", "additional_context": "교통사고"},
            user,
            db,
        )

    assert result["job_id"] == "job-123"
    assert result["legal_profile"] == expected_profile
    mock_extract.assert_called_once_with(job)
    mock_profile.assert_called_once()
    call_kwargs = mock_profile.call_args.kwargs
    assert call_kwargs["claim_type_hint"] == "손해배상"
    assert call_kwargs["additional_context"] == "교통사고"


def test_analyze_legal_profile_no_text():
    """문서에서 텍스트를 추출할 수 없으면 400 예외를 발생시킨다."""
    job = _make_job()
    db = _make_db(job)
    user = _make_user()

    with patch("backend.api.ediscovery.pipeline_ediscovery.extract_page_texts") as mock_extract:
        mock_extract.return_value = ({}, {})
        try:
            analyze_legal_profile("job-123", {}, user, db)
        except Exception as exc:
            assert exc.status_code == 400
            assert "텍스트" in exc.detail
            return
    raise AssertionError("HTTPException이 발생하지 않음")


def test_analyze_legal_profile_with_agent_collected_context():
    """에이전트가 수집한 e-Discovery 그래프 요약을 additional_context로 전달하면
    프롬프트에 반영되고 더 구체적인 법률 프로필이 나온다."""
    job = _make_job()
    db = _make_db(job)
    user = _make_user()

    expected_profile = {
        "legal_domain": "민사",
        "claim_type": "대여금반환",
        "claim_summary": "원고가 피고에게 대여금 반환을 청구함",
        "issues": ["변제기 도래", "피고의 변제 항변"],
        "legal_elements": [
            {"id": "element_1", "name": "금전 대여", "description": "원고가 피고에게 금전을 대여했음"},
            {"id": "element_2", "name": "변제기 도래", "description": "반환할 기한이 도래했음"},
        ],
        "confidence": 0.92,
    }

    graph_summary = "e-Discovery 그래프: 원고 A가 피고 B에게 1천만 원 대여, 피고 B는 변제 완료 주장"

    with patch("backend.api.ediscovery.pipeline_ediscovery.extract_page_texts") as mock_extract, \
         patch("backend.api.ediscovery.legal_case_profile.extract_legal_profile") as mock_profile:
        mock_extract.return_value = ({1: "대여계약서", 2: "변제 독촉 내용", 3: "소장"}, {})
        mock_profile.return_value = expected_profile

        result = analyze_legal_profile(
            "job-123",
            {
                "claim_type_hint": "대여금반환",
                "additional_context": graph_summary,
            },
            user,
            db,
        )

    assert result["legal_profile"] == expected_profile
    call_kwargs = mock_profile.call_args.kwargs
    assert call_kwargs["claim_type_hint"] == "대여금반환"
    assert call_kwargs["additional_context"] == graph_summary


def test_analyze_legal_profile_rejects_generic_result():
    """LLM이 기타/정보부족 같은 fallback을 반환하면 502 예외를 발생시킨다."""
    job = _make_job()
    db = _make_db(job)
    user = _make_user()

    with patch("backend.api.ediscovery.pipeline_ediscovery.extract_page_texts") as mock_extract, \
         patch("backend.api.ediscovery.legal_case_profile.extract_legal_profile") as mock_profile:
        mock_extract.return_value = ({1: "페이지 1"}, {})
        mock_profile.return_value = {}

        try:
            analyze_legal_profile("job-123", {}, user, db)
        except Exception as exc:
            assert exc.status_code == 502
            assert "실패" in exc.detail
            return
    raise AssertionError("HTTPException이 발생하지 않음")
