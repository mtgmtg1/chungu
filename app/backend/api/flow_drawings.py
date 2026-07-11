#!/usr/bin/env python3
"""PROOF Flow Drawings API — React Flow 캔버스 드로잉/주석 저장 엔드포인트

[Flow: Step 1 (GET /api/jobs/{job_id}/flow-drawings — 조회) -> Step 2 (PUT /api/jobs/{job_id}/flow-drawings — upsert) -> Step 3 (DELETE — 삭제)]

사용자가 Flow Panel 에 그린 SVG path 드로잉과 텍스트 주석을 작업+사용자별로 저장/조회/삭제한다.
"""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.supabase_auth import CurrentUser, get_current_user
from ..db.models import FlowDrawing
from ..db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/jobs", tags=["flow-drawings"])


class FlowDrawingData(BaseModel):
    """드로잉/주석/노트/엣지 데이터 — paths + text_annotations + note_nodes + custom_edges."""
    paths: list[dict[str, Any]] = Field(default_factory=list)
    text_annotations: list[dict[str, Any]] = Field(default_factory=list)
    note_nodes: list[dict[str, Any]] = Field(default_factory=list)
    custom_edges: list[dict[str, Any]] = Field(default_factory=list)


@router.get("/{job_id}/flow-drawings", response_model=None)
async def get_flow_drawings(
    job_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict | None:
    """[Flow: Step 1 (job_id + user_id 로 조회) -> Step 2 (paths + text_annotations 반환, 없으면 null)]

    사용자의 Flow Panel 드로잉/주석을 조회한다.
    """
    stmt = select(FlowDrawing).where(
        FlowDrawing.job_id == job_id,
        FlowDrawing.user_id == user.user_id,
    )
    record = db.execute(stmt).scalar_one_or_none()
    if not record:
        return None
    return {
        "paths": record.paths or [],
        "text_annotations": record.text_annotations or [],
        "note_nodes": record.note_nodes or [],
        "custom_edges": record.custom_edges or [],
    }


@router.put("/{job_id}/flow-drawings", response_model=None)
async def save_flow_drawings(
    job_id: str,
    data: FlowDrawingData,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """[Flow: Step 1 (기존 레코드 조회) -> Step 2 (있으면 UPDATE, 없으면 INSERT) -> Step 3 (저장된 데이터 반환)]

    사용자의 Flow Panel 드로잉/주석을 upsert 한다 (작업+사용자별 1레코드).
    """
    stmt = select(FlowDrawing).where(
        FlowDrawing.job_id == job_id,
        FlowDrawing.user_id == user.user_id,
    )
    record = db.execute(stmt).scalar_one_or_none()

    if record:
        record.paths = data.paths
        record.text_annotations = data.text_annotations
        record.note_nodes = data.note_nodes
        record.custom_edges = data.custom_edges
        record.updated_at = datetime.utcnow()
    else:
        record = FlowDrawing(
            job_id=job_id,
            user_id=user.user_id,
            paths=data.paths,
            text_annotations=data.text_annotations,
            note_nodes=data.note_nodes,
            custom_edges=data.custom_edges,
        )
        db.add(record)

    db.commit()
    return {"status": "ok", "paths": record.paths, "text_annotations": record.text_annotations, "note_nodes": record.note_nodes, "custom_edges": record.custom_edges}


@router.delete("/{job_id}/flow-drawings", response_model=None)
async def delete_flow_drawings(
    job_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """[Flow: Step 1 (job_id + user_id 로 조회) -> Step 2 (레코드 삭제)]

    사용자의 Flow Panel 드로잉/주석을 삭제한다.
    """
    stmt = select(FlowDrawing).where(
        FlowDrawing.job_id == job_id,
        FlowDrawing.user_id == user.user_id,
    )
    record = db.execute(stmt).scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Flow drawings not found")

    db.delete(record)
    db.commit()
    return {"status": "ok"}
