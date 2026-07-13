#!/usr/bin/env python3
# [Flow: Step 1 (필요한 모듈 import) -> Step 2 (Mock User/SessionLocal 설정)
#       -> Step 3 (e-Discovery 파이프라인의 각 LLM 호출 지점에서 1 step 크레딧 차감 테스트)
#       -> Step 4 (병렬 호출 횟수만큼 정확히 차감되는지 검증)]
# e-Discovery 파이프라인 내부의 병렬 LLM 호출 지점마다 1 step = 1 credit(1000 milli-USD)가
# 정확히 차감되는지 검증한다. 메인 SQLAlchemy 세션과 분리된 별도 세션에서 차감이 이루어진다.
import os
import sys
from unittest.mock import MagicMock, patch
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

from backend.core.pipeline_ediscovery import (
    ChildChunk,
    EdiscoveryNode,
    _extract_fallback_nodes,
    _suggest_params,
    detect_anomalies_concurrent,
    extract_nodes_from_chunk,
    extract_nodes_concurrent,
)


def _make_user(user_id: uuid.UUID | None = None) -> MagicMock:
    """테스트용 사용자 MagicMock 객체를 생성한다."""
    user = MagicMock()
    user.id = user_id or uuid.uuid4()
    user.points_balance = 10000
    return user


def _make_session(user: MagicMock | None = None) -> MagicMock:
    """테스트용 DB 세션 MagicMock. get()으로 user를 반환한다."""
    session = MagicMock()
    session.get.return_value = user
    return session


def test_spend_agent_step_for_call_skips_without_user_id():
    """user_id가 None이면 _spend_agent_step_for_call이 DB 세션을 생성하지 않는다."""
    from backend.core.pipeline_ediscovery import _spend_agent_step_for_call

    with patch("backend.core.pipeline_ediscovery.SessionLocal") as mock_session_local:
        _spend_agent_step_for_call(None, "AI agent: test")
        mock_session_local.assert_not_called()


def test_suggest_params_spends_step_credit():
    """_suggest_params는 LLM 호출 직전에 1 step 크레딧을 차감한다."""
    user_id = uuid.uuid4()

    with patch("backend.core.pipeline_ediscovery._spend_agent_step_for_call") as mock_spend, patch(
        "backend.core.pipeline_ediscovery.call_text",
        return_value=("{}", None),
    ), patch(
        "backend.core.pipeline_ediscovery._parse_param_suggestion",
        return_value={"chunk_size": 512, "threshold": 0.5, "max_docs": 10, "reasoning": ""},
    ):
        _suggest_params({1: "page"}, "http://test", "model", "key", user_id=str(user_id))

    mock_spend.assert_called_once_with(str(user_id), "AI agent: e-Discovery parameter suggestion")


def test_extract_nodes_from_chunk_spends_step_credit():
    """extract_nodes_from_chunk는 LLM 호출 직전에 1 step 크레딧을 차감한다."""
    user_id = uuid.uuid4()
    chunk = ChildChunk(page_no=1, text="test text", index=0, source_file="a.pdf", original_page=1)

    with patch("backend.core.pipeline_ediscovery._spend_agent_step_for_call") as mock_spend, patch(
        "backend.core.pipeline_ediscovery.call_text",
        return_value=("[]", None),
    ):
        extract_nodes_from_chunk(chunk, "http://test", "model", "key", user_id=str(user_id))

    mock_spend.assert_called_once_with(str(user_id), "AI agent: e-Discovery node extraction")


def test_extract_nodes_concurrent_spends_per_chunk():
    """extract_nodes_concurrent는 청크 개수만큼 정확히 step 크레딧을 차감한다."""
    user_id = uuid.uuid4()
    chunks = [
        ChildChunk(page_no=1, text="a", index=0, source_file="a.pdf", original_page=1),
        ChildChunk(page_no=2, text="b", index=0, source_file="a.pdf", original_page=2),
        ChildChunk(page_no=3, text="c", index=0, source_file="a.pdf", original_page=3),
    ]

    with patch("backend.core.pipeline_ediscovery._spend_agent_step_for_call") as mock_spend, patch(
        "backend.core.pipeline_ediscovery.call_text",
        return_value=("[]", None),
    ):
        extract_nodes_concurrent(chunks, "http://test", "model", "key", user_id=str(user_id))

    assert mock_spend.call_count == 3
    for call in mock_spend.call_args_list:
        assert call[0] == (str(user_id), "AI agent: e-Discovery node extraction")


def test_detect_anomalies_concurrent_spends_per_batch():
    """detect_anomalies_concurrent는 배치 개수만큼 정확히 step 크레딧을 차감한다."""
    user_id = uuid.uuid4()
    # BATCH_SIZE=40 기준 90개 노드는 3개 배치
    nodes = [
        EdiscoveryNode(
            id=f"n{i}", type="evidence", label=f"evidence {i}", page=1, confidence=0.9
        )
        for i in range(90)
    ]

    with patch("backend.core.pipeline_ediscovery._spend_agent_step_for_call") as mock_spend, patch(
        "backend.core.pipeline_ediscovery.call_text",
        return_value=("[]", None),
    ):
        detect_anomalies_concurrent(nodes, "http://test", "model", "key", user_id=str(user_id))

    # 90개 / 40 = 3개 배치 (40, 40, 10)
    assert mock_spend.call_count == 3
    for call in mock_spend.call_args_list:
        assert call[0] == (str(user_id), "AI agent: e-Discovery anomaly detection")


def test_extract_fallback_nodes_spends_per_sample_chunk():
    """_extract_fallback_nodes는 샘플링된 청크 개수만큼 step 크레딧을 차감한다."""
    user_id = uuid.uuid4()
    chunks = [
        ChildChunk(page_no=i, text=f"text {i}", index=0, source_file="a.pdf", original_page=i)
        for i in range(1, 21)
    ]

    with patch("backend.core.pipeline_ediscovery._spend_agent_step_for_call") as mock_spend, patch(
        "backend.core.pipeline_ediscovery.call_text",
        return_value=("[]", None),
    ):
        _extract_fallback_nodes(chunks, "http://test", "model", "key", user_id=str(user_id))

    # max_sample=5 기준 5개 샘플 청크 -> 5회 차감
    assert mock_spend.call_count == 5
    for call in mock_spend.call_args_list:
        assert call[0] == (str(user_id), "AI agent: e-Discovery fallback node extraction")
