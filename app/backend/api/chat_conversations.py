#!/usr/bin/env python3
"""PROOF Chat Conversations API — 에이전트 채팅 대화 이력 CRUD 엔드포인트

[Flow: Step 1 (GET /api/jobs/{job_id}/chat-conversations — 목록 조회, messages 제외)
      -> Step 2 (GET /api/jobs/{job_id}/chat-conversations/{conversation_id} — 단일 전체 조회)
      -> Step 3 (PUT /api/jobs/{job_id}/chat-conversations/{conversation_id} — upsert)
      -> Step 4 (DELETE — 단일 대화 삭제)]

사용자가 Job(프로젝트)별로 나눈 에이전트 채팅 대화 세션과 UIMessage[] 전체를 저장/조회/삭제한다.
기존 localStorage 기반 대화 이력을 DB로 이전하여 단일 진실 공급원을 구축한다.
"""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth.api_key_auth import get_current_user_or_api_key
from ..auth.supabase_auth import CurrentUser
from ..db.models import ChatConversation
from ..db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/jobs", tags=["chat-conversations"])


def _require_chat_user(
    auth: tuple[CurrentUser, Any] = Depends(get_current_user_or_api_key),
) -> CurrentUser:
    """[Flow: Step 1 (API key 또는 세션 인증) -> Step 2 (CurrentUser만 반환)]

    jobs.py와 동일한 패턴으로 웹 세션과 API key를 모두 허용한다.
    """
    return auth[0]


class ChatConversationData(BaseModel):
    """대화 저장용 데이터 — title + messages (UIMessage[])."""

    title: str = Field(default="")
    messages: list[dict[str, Any]] = Field(default_factory=list)


@router.get("/{job_id}/chat-conversations", response_model=None)
async def list_chat_conversations(
    job_id: str,
    user: CurrentUser = Depends(_require_chat_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    """[Flow: Step 1 (job_id + user_id 로 조회) -> Step 2 (updated_at DESC 정렬)
          -> Step 3 (messages 제외한 메타데이터만 반환 — 목록 로딩 경량화)]

    사용자의 해당 Job 대화 목록을 반환한다. messages는 제외하여 경량화.
    프론트엔드에서 대화 선택 시 get_chat_conversation로 messages를 별도 로드한다.
    """
    stmt = (
        select(ChatConversation)
        .where(
            ChatConversation.job_id == job_id,
            ChatConversation.user_id == user.user_id,
        )
        .order_by(ChatConversation.updated_at.desc())
    )
    records = db.execute(stmt).scalars().all()
    return [
        {
            "id": record.id,
            "title": record.title or "",
            "createdAt": int(record.created_at.timestamp() * 1000) if record.created_at else 0,
            "updatedAt": int(record.updated_at.timestamp() * 1000) if record.updated_at else 0,
        }
        for record in records
    ]


@router.get("/{job_id}/chat-conversations/{conversation_id}", response_model=None)
async def get_chat_conversation(
    job_id: str,
    conversation_id: str,
    user: CurrentUser = Depends(_require_chat_user),
    db: Session = Depends(get_db),
) -> dict | None:
    """[Flow: Step 1 (job_id + user_id + conversation_id 로 조회) -> Step 2 (messages 포함 전체 데이터 반환)]

    단일 대화의 messages 포함 전체 데이터를 반환한다.
    프론트엔드에서 대화 선택 시 호출하여 이전 메시지를 복원한다.
    """
    stmt = select(ChatConversation).where(
        ChatConversation.id == conversation_id,
        ChatConversation.job_id == job_id,
        ChatConversation.user_id == user.user_id,
    )
    record = db.execute(stmt).scalar_one_or_none()
    if not record:
        return None
    return {
        "id": record.id,
        "title": record.title or "",
        "messages": record.messages or [],
        "createdAt": int(record.created_at.timestamp() * 1000) if record.created_at else 0,
        "updatedAt": int(record.updated_at.timestamp() * 1000) if record.updated_at else 0,
    }


@router.put("/{job_id}/chat-conversations/{conversation_id}", response_model=None)
async def save_chat_conversation(
    job_id: str,
    conversation_id: str,
    data: ChatConversationData,
    user: CurrentUser = Depends(_require_chat_user),
    db: Session = Depends(get_db),
) -> dict:
    """[Flow: Step 1 (기존 레코드 조회) -> Step 2 (있으면 UPDATE, 없으면 INSERT) -> Step 3 (저장된 데이터 반환)]

    사용자의 대화를 upsert 한다 (대화ID 단위 1레코드).
    클라이언트가 생성한 conversation_id를 PK로 그대로 사용한다.
    """
    stmt = select(ChatConversation).where(
        ChatConversation.id == conversation_id,
        ChatConversation.job_id == job_id,
        ChatConversation.user_id == user.user_id,
    )
    record = db.execute(stmt).scalar_one_or_none()

    if record:
        record.title = data.title
        record.messages = data.messages
        record.updated_at = datetime.utcnow()
    else:
        record = ChatConversation(
            id=conversation_id,
            job_id=job_id,
            user_id=user.user_id,
            title=data.title,
            messages=data.messages,
        )
        db.add(record)

    db.commit()
    return {
        "status": "ok",
        "id": record.id,
        "title": record.title,
        "messages": record.messages,
        "updatedAt": int(record.updated_at.timestamp() * 1000) if record.updated_at else 0,
    }


@router.delete("/{job_id}/chat-conversations/{conversation_id}", response_model=None)
async def delete_chat_conversation(
    job_id: str,
    conversation_id: str,
    user: CurrentUser = Depends(_require_chat_user),
    db: Session = Depends(get_db),
) -> dict:
    """[Flow: Step 1 (job_id + user_id + conversation_id 로 조회) -> Step 2 (레코드 삭제)]

    사용자의 단일 대화를 삭제한다.
    """
    stmt = select(ChatConversation).where(
        ChatConversation.id == conversation_id,
        ChatConversation.job_id == job_id,
        ChatConversation.user_id == user.user_id,
    )
    record = db.execute(stmt).scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Chat conversation not found")

    db.delete(record)
    db.commit()
    return {"status": "ok"}
