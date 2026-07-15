#!/usr/bin/env python3
"""[Flow: Step 1 (필요한 모듈 import) -> Step 2 (save_ediscovery_graph 엔드포인트 단위 테스트)
      -> Step 3 (Job/DB/User mock) -> Step 4 (그래프 저장/검증 실패 시나리오 검증)]

PUT /api/jobs/{job_id}/ediscovery/graph 엔드포인트의 비즈니스 로직을
DB와 FastAPI 의존성 없이 직접 호출하여 검증한다.
"""
import os
import sys
from unittest.mock import MagicMock

# [Flow: backend 패키지 루트를 sys.path에 추가]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

from backend.api.ediscovery import save_ediscovery_graph


def _make_user(user_id: str = "11111111-1111-1111-1111-111111111111"):
    """테스트용 CurrentUser mock 객체를 생성한다."""
    user = MagicMock()
    user.is_dev_bypass = False
    user.user_id = user_id
    return user


def _make_job(
    job_id: str = "job-123",
    user_id: str = "11111111-1111-1111-1111-111111111111",
    status: str = "done",
    existing_graph: dict | None = None,
):
    """테스트용 Job mock 객체를 생성한다."""
    job = MagicMock()
    job.id = job_id
    job.user_id = user_id
    job.status = status
    job.expires_at = None
    job.ediscovery_graphs = existing_graph or {"nodes": [], "edges": []}
    return job


def _make_db(job):
    """테스트용 DB 세션 mock 객체를 생성한다."""
    db = MagicMock()
    db.get.return_value = job
    return db


def test_save_ediscovery_graph_success():
    """정상적인 노드/엣지 페이로드를 받으면 job.ediscovery_graphs에 저장한다."""
    job = _make_job()
    db = _make_db(job)
    user = _make_user()

    payload = {
        "nodes": [
            {"id": "n1", "type": "event", "data": {"label": "사건 1", "date": "2026-06-05"}},
            {"id": "n2", "type": "event", "data": {"label": "사건 2", "date": "2026-06-06"}},
        ],
        "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
    }

    result = save_ediscovery_graph("job-123", payload, user, db)

    assert result["job_id"] == "job-123"
    assert result["ediscovery_graphs"]["nodes"] == payload["nodes"]
    assert result["ediscovery_graphs"]["edges"] == payload["edges"]
    db.commit.assert_called_once()


def test_save_ediscovery_graph_rejects_non_object_payload():
    """payload가 객체가 아니면 400 예외를 발생시킨다."""
    job = _make_job()
    db = _make_db(job)
    user = _make_user()

    try:
        save_ediscovery_graph("job-123", [], user, db)
    except Exception as exc:
        assert exc.status_code == 400
        assert "Invalid payload" in exc.detail
        return
    raise AssertionError("HTTPException이 발생하지 않음")


def test_save_ediscovery_graph_rejects_invalid_nodes_or_edges():
    """nodes/edges가 리스트가 아니면 400 예외를 발생시킨다."""
    job = _make_job()
    db = _make_db(job)
    user = _make_user()

    try:
        save_ediscovery_graph("job-123", {"nodes": "bad", "edges": []}, user, db)
    except Exception as exc:
        assert exc.status_code == 400
        assert "nodes and edges must be lists" in exc.detail
        return
    raise AssertionError("HTTPException이 발생하지 않음")


def test_save_ediscovery_graph_rejects_missing_node_id():
    """노드에 id가 없으면 400 예외를 발생시킨다."""
    job = _make_job()
    db = _make_db(job)
    user = _make_user()

    payload = {
        "nodes": [{"type": "event", "data": {}}],
        "edges": [],
    }
    try:
        save_ediscovery_graph("job-123", payload, user, db)
    except Exception as exc:
        assert exc.status_code == 400
        assert "All nodes must be objects with an id" in exc.detail
        return
    raise AssertionError("HTTPException이 발생하지 않음")


def test_save_ediscovery_graph_rejects_duplicate_node_id():
    """중복된 노드 id가 있으면 400 예외를 발생시킨다."""
    job = _make_job()
    db = _make_db(job)
    user = _make_user()

    payload = {
        "nodes": [
            {"id": "n1", "type": "event", "data": {}},
            {"id": "n1", "type": "event", "data": {}},
        ],
        "edges": [],
    }
    try:
        save_ediscovery_graph("job-123", payload, user, db)
    except Exception as exc:
        assert exc.status_code == 400
        assert "Duplicate node id" in exc.detail
        return
    raise AssertionError("HTTPException이 발생하지 않음")


def test_save_ediscovery_graph_rejects_dangling_edge():
    """엣지가 존재하지 않는 노드를 참조하면 400 예외를 발생시킨다."""
    job = _make_job()
    db = _make_db(job)
    user = _make_user()

    payload = {
        "nodes": [{"id": "n1", "type": "event", "data": {}}],
        "edges": [{"id": "e1", "source": "n1", "target": "n2"}],
    }
    try:
        save_ediscovery_graph("job-123", payload, user, db)
    except Exception as exc:
        assert exc.status_code == 400
        assert "Edge 0 references missing node" in exc.detail
        return
    raise AssertionError("HTTPException이 발생하지 않음")
