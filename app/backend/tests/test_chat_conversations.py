#!/usr/bin/env python3
"""[Flow: Step 1 (in-memory SQLite DB 생성) -> Step 2 (ChatConversation 테이블 생성)
      -> Step 3 (CRUD API 함수 직접 호출) -> Step 4 (결과 검증)]

chat_conversations API가 의도대로 동작하는지 검증한다.
- 케이스 1: 목록 조회 — messages 제외, updated_at DESC 정렬
- 케이스 2: 단일 조회 — messages 포함 전체 데이터 반환
- 케이스 3: 단일 조회 — 존재하지 않는 대화는 None 반환
- 케이스 4: upsert 신규 — INSERT (클라이언트 생성 ID)
- 케이스 5: upsert 갱신 — 기존 레코드 title/messages UPDATE
- 케이스 6: 삭제 — 존재하는 레코드 삭제
- 케이스 7: 삭제 — 존재하지 않는 레코드 404
- 케이스 8: 다른 사용자 접근 차단 — user_id 필터링으로 타인 대화 조회 불가
- 케이스 9: 도구 결과 요약 저장 — 큰 output이 요약되어 저장되는지 확인
"""
import asyncio
import sys
import os
import uuid
from datetime import datetime, timedelta

# [Flow: backend 패키지 루트를 sys.path에 추가]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

from sqlalchemy import create_engine, String
from sqlalchemy.types import UUID as SQLUUID
from sqlalchemy.orm import Session

from backend.db.models import ChatConversation, Base, User, Job
from backend.api.chat_conversations import (
    ChatConversationData,
    list_chat_conversations,
    get_chat_conversation,
    save_chat_conversation,
    delete_chat_conversation,
)


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


def check_true(label, cond):
    """[Flow: 조건이 True인지 검증]"""
    global PASS, FAIL
    ok = bool(cond)
    status = "PASS" if ok else "FAIL"
    if ok:
        PASS += 1
    else:
        FAIL += 1
    print(f"  [{status}] {label}")
    if not ok:
        print(f"         expected: True")
        print(f"         actual:   {cond}")
    return ok


def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


# ─── Mock CurrentUser ────────────────────────────────────────
class MockUser:
    """[Flow: 테스트용 CurrentUser — user_id 속성만 제공]

    실제 CurrentUser의 user_id는 문자열이다. SQLite 테스트에서는 UUID 컬럼을
    String(36)으로 교체하므로 문자열 그대로 사용한다.
    """

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.email = f"test-{user_id}@example.com"


# ─── 테스트 DB 설정 ──────────────────────────────────────────
def setup_test_db() -> Session:
    """[Flow: Step 1 (in-memory SQLite 엔진 생성) -> Step 2 (UUID 컬럼을 String으로 교체)
          -> Step 3 (Base 테이블 전체 생성) -> Step 4 (Session 반환)]

    SQLite는 UUID 타입을 네이티브로 지원하지 않으므로, Base.metadata의 모든 UUID
    컬럼을 String(36)으로 교체하여 SQLite에서 문자열 기반으로 동작하도록 한다.
    """
    engine = create_engine("sqlite:///:memory:", echo=False)
    # [Flow: SQLite 호환성 — 모든 UUID 컬럼을 String(36)으로 교체]
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, SQLUUID):
                column.type = String(36)
    Base.metadata.create_all(bind=engine)
    return Session(engine)


def insert_conversation(db, id, job_id, user_id, title, messages, minutes_ago=0):
    """[Flow: 테스트용 대화 레코드 직접 삽입 — updated_at을 minutes_ago 전으로 설정]

    user_id는 문자열을 받아 String(36) 컬럼에 그대로 저장한다.
    """
    record = ChatConversation(
        id=id,
        job_id=job_id,
        user_id=user_id,
        title=title,
        messages=messages,
        created_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
        updated_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
    )
    db.add(record)
    db.commit()
    return record


# ─── 테스트 1: 목록 조회 — messages 제외, updated_at DESC 정렬 ───
def test_list_excludes_messages_and_sorts_by_updated_desc():
    section("테스트 1: 목록 조회 — messages 제외, updated_at DESC 정렬")

    db = setup_test_db()
    user = MockUser("11111111-1111-1111-1111-111111111111")
    job_id = "job-001"

    # [Flow: 3개 대화 삽입 — updated_at이 서로 다름 (30분 전, 10분 전, 60분 전)]
    insert_conversation(db, "conv-old", job_id, user.user_id, "오래된 대화", [{"role": "user", "parts": []}], minutes_ago=60)
    insert_conversation(db, "conv-mid", job_id, user.user_id, "중간 대화", [{"role": "user", "parts": []}], minutes_ago=30)
    insert_conversation(db, "conv-new", job_id, user.user_id, "최신 대화", [{"role": "user", "parts": []}], minutes_ago=10)

    result = asyncio.run(list_chat_conversations(job_id, user, db))

    check("목록 길이 3", len(result), 3)
    # [Flow: updated_at DESC 정렬 — 최신이 첫 번째]
    check("첫 번째 = 최신 대화", result[0]["id"], "conv-new")
    check("두 번째 = 중간 대화", result[1]["id"], "conv-mid")
    check("세 번째 = 오래된 대화", result[2]["id"], "conv-old")
    # [Flow: messages 필드 제외 확인]
    check_true("첫 번째 항목에 messages 없음", "messages" not in result[0])
    check_true("모든 항목에 messages 없음", all("messages" not in r for r in result))
    # [Flow: 메타데이터 필드 존재 확인]
    check_true("id 필드 있음", "id" in result[0])
    check_true("title 필드 있음", "title" in result[0])
    check_true("createdAt 필드 있음", "createdAt" in result[0])
    check_true("updatedAt 필드 있음", "updatedAt" in result[0])

    db.close()


# ─── 테스트 2: 단일 조회 — messages 포함 ───
def test_get_single_includes_messages():
    section("테스트 2: 단일 조회 — messages 포함 전체 데이터")

    db = setup_test_db()
    user = MockUser("22222222-2222-2222-2222-222222222222")
    job_id = "job-002"

    messages = [
        {"role": "user", "parts": [{"type": "text", "text": "안녕하세요"}]},
        {"role": "assistant", "parts": [{"type": "text", "text": "안녕하세요! 무엇을 도와드릴까요?"}]},
    ]
    insert_conversation(db, "conv-detail", job_id, user.user_id, "인사 대화", messages, minutes_ago=5)

    result = asyncio.run(get_chat_conversation(job_id, "conv-detail", user, db))

    check_true("결과 반환됨", result is not None)
    check("ID 일치", result["id"], "conv-detail")
    check("제목 일치", result["title"], "인사 대화")
    check("messages 길이 2", len(result["messages"]), 2)
    check("첫 메시지 role=user", result["messages"][0]["role"], "user")
    check("두 메시지 role=assistant", result["messages"][1]["role"], "assistant")
    check("사용자 텍스트", result["messages"][0]["parts"][0]["text"], "안녕하세요")

    db.close()


# ─── 테스트 3: 단일 조회 — 존재하지 않는 대화는 None ───
def test_get_nonexistent_returns_none():
    section("테스트 3: 존재하지 않는 대화 조회 — None 반환")

    db = setup_test_db()
    user = MockUser("33333333-3333-3333-3333-333333333333")

    result = asyncio.run(get_chat_conversation("job-003", "nonexistent-id", user, db))

    check("None 반환", result, None)

    db.close()


# ─── 테스트 4: upsert 신규 — INSERT ───
def test_upsert_inserts_new_conversation():
    section("테스트 4: upsert 신규 — INSERT (클라이언트 생성 ID)")

    db = setup_test_db()
    user = MockUser("44444444-4444-4444-4444-444444444444")
    job_id = "job-004"
    conv_id = "client-generated-001"

    data = ChatConversationData(
        title="새 대화 제목",
        messages=[
            {"role": "user", "parts": [{"type": "text", "text": "첫 메시지"}]},
        ],
    )

    result = asyncio.run(save_chat_conversation(job_id, conv_id, data, user, db))

    check("status=ok", result["status"], "ok")
    check("반환된 ID = 클라이언트 ID", result["id"], conv_id)
    check("반환된 title", result["title"], "새 대화 제목")
    check("반환된 messages 길이 1", len(result["messages"]), 1)

    # [Flow: DB에 실제로 저장되었는지 확인]
    db_record = db.query(ChatConversation).filter(ChatConversation.id == conv_id).one_or_none()
    check_true("DB에 레코드 존재", db_record is not None)
    check("DB title", db_record.title, "새 대화 제목")
    check("DB job_id", db_record.job_id, job_id)
    check("DB user_id", str(db_record.user_id), user.user_id)

    db.close()


# ─── 테스트 5: upsert 갱신 — 기존 레코드 UPDATE ───
def test_upsert_updates_existing_conversation():
    section("테스트 5: upsert 갱신 — 기존 레코드 title/messages UPDATE")

    db = setup_test_db()
    user = MockUser("55555555-5555-5555-5555-555555555555")
    job_id = "job-005"
    conv_id = "conv-update-test"

    # [Flow: 기존 레코드 삽입]
    insert_conversation(db, conv_id, job_id, user.user_id, "원래 제목", [{"role": "user", "parts": []}], minutes_ago=20)

    # [Flow: 새 데이터로 upsert]
    data = ChatConversationData(
        title="수정된 제목",
        messages=[
            {"role": "user", "parts": [{"type": "text", "text": "수정된 메시지"}]},
            {"role": "assistant", "parts": [{"type": "text", "text": "응답"}]},
        ],
    )

    result = asyncio.run(save_chat_conversation(job_id, conv_id, data, user, db))

    check("status=ok", result["status"], "ok")
    check("수정된 title", result["title"], "수정된 제목")
    check("수정된 messages 길이 2", len(result["messages"]), 2)

    # [Flow: DB에서 갱신 확인 — 레코드가 새로 생성되지 않고 업데이트되었는지]
    records = db.query(ChatConversation).filter(ChatConversation.id == conv_id).all()
    check("레코드 1개 (중복 생성 아님)", len(records), 1)
    check("DB title 갱신됨", records[0].title, "수정된 제목")
    check("DB messages 길이 2", len(records[0].messages), 2)

    db.close()


# ─── 테스트 6: 삭제 — 존재하는 레코드 ───
def test_delete_existing_conversation():
    section("테스트 6: 삭제 — 존재하는 레코드 삭제")

    db = setup_test_db()
    user = MockUser("66666666-6666-6666-6666-666666666666")
    job_id = "job-006"
    conv_id = "conv-delete-me"

    insert_conversation(db, conv_id, job_id, user.user_id, "삭제할 대화", [{"role": "user", "parts": []}])

    result = asyncio.run(delete_chat_conversation(job_id, conv_id, user, db))

    check("status=ok", result["status"], "ok")
    # [Flow: DB에서 실제로 삭제되었는지 확인]
    db_record = db.query(ChatConversation).filter(ChatConversation.id == conv_id).one_or_none()
    check_true("DB에서 레코드 삭제됨", db_record is None)

    db.close()


# ─── 테스트 7: 삭제 — 존재하지 않는 레코드 404 ───
def test_delete_nonexistent_raises_404():
    section("테스트 7: 삭제 — 존재하지 않는 레코드 404")

    db = setup_test_db()
    user = MockUser("77777777-7777-7777-7777-777777777777")

    from fastapi import HTTPException

    try:
        asyncio.run(delete_chat_conversation("job-007", "nonexistent", user, db))
        check_true("HTTPException 발생", False)
    except HTTPException as e:
        check("404 상태 코드", e.status_code, 404)
        check_true("detail에 'not found' 포함", "not found" in e.detail.lower())

    db.close()


# ─── 테스트 8: 다른 사용자 접근 차단 — user_id 필터링 ───
def test_other_user_cannot_access():
    section("테스트 8: 다른 사용자 접근 차단 — user_id 필터링")

    db = setup_test_db()
    user_a = MockUser("88888888-8888-8888-8888-888888888888")
    user_b = MockUser("99999999-9999-9999-9999-999999999999")
    job_id = "job-008"

    # [Flow: user_a가 대화 생성]
    insert_conversation(db, "conv-private", job_id, user_a.user_id, "user_a 비공개 대화", [{"role": "user", "parts": [{"type": "text", "text": "비밀"}]}])

    # [Flow: user_b가 같은 job의 대화 목록 조회 — user_a 대화가 보이면 안 됨]
    result_b = asyncio.run(list_chat_conversations(job_id, user_b, db))
    check("user_b 목록 길이 0", len(result_b), 0)

    # [Flow: user_b가 user_a의 대화를 직접 조회 — None 반환]
    result_direct = asyncio.run(get_chat_conversation(job_id, "conv-private", user_b, db))
    check("user_b 직접 조회 → None", result_direct, None)

    # [Flow: user_b가 user_a의 대화를 삭제 시도 — 404]
    from fastapi import HTTPException
    try:
        asyncio.run(delete_chat_conversation(job_id, "conv-private", user_b, db))
        check_true("user_b 삭제 시 HTTPException", False)
    except HTTPException as e:
        check("user_b 삭제 → 404", e.status_code, 404)

    # [Flow: user_a는 자신의 대화를 정상 조회 가능]
    result_a = asyncio.run(get_chat_conversation(job_id, "conv-private", user_a, db))
    check_true("user_a 정상 조회 가능", result_a is not None)
    check("user_a 대화 내용", result_a["messages"][0]["parts"][0]["text"], "비밀")

    db.close()


# ─── 테스트 9: 도구 결과 요약 저장 — 큰 output이 요약되어 저장 ───
def test_large_tool_output_stored_as_compacted():
    section("테스트 9: 도구 결과 요약 저장 — 큰 output이 요약되어 DB에 저장")

    db = setup_test_db()
    user = MockUser("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    job_id = "job-009"
    conv_id = "conv-tool-summary"

    # [Flow: 도구 결과가 요약된 messages — 프론트엔드 compactMessagesForStorage 출력 시뮬레이션]
    # 원본 output이 500자 초과였다고 가정 → 핵심 필드 + _summary 메타데이터로 요약됨
    compacted_messages = [
        {"role": "user", "parts": [{"type": "text", "text": "PDF에서 텍스트를 추출해줘"}]},
        {
            "role": "assistant",
            "parts": [
                {
                    "type": "dynamic-tool",
                    "toolName": "get_elements",
                    "state": "output-available",
                    "input": {"page_no": 1},
                    # [Flow: 요약된 output — 원본 수천 자 대신 핵심 필드 + _summary]
                    "output": {
                        "ok": True,
                        "count": 42,
                        "page": 1,
                        "_summary": {"originalChars": 8500, "truncated": True},
                    },
                },
                {"type": "text", "text": "페이지 1에서 42개의 텍스트 요소를 추출했습니다."},
            ],
        },
    ]

    data = ChatConversationData(title="PDF 추출 대화", messages=compacted_messages)
    result = asyncio.run(save_chat_conversation(job_id, conv_id, data, user, db))

    check("status=ok", result["status"], "ok")
    check("messages 길이 2", len(result["messages"]), 2)

    # [Flow: DB에서 저장된 내용 확인 — 요약된 output이 그대로 저장됨]
    db_record = db.query(ChatConversation).filter(ChatConversation.id == conv_id).one_or_none()
    check_true("DB에 레코드 존재", db_record is not None)
    assistant_parts = db_record.messages[1]["parts"]
    tool_part = next(p for p in assistant_parts if p.get("type") == "dynamic-tool")
    check("도구 이름 보존", tool_part["toolName"], "get_elements")
    check("도구 상태 보존", tool_part["state"], "output-available")
    check("input 보존", tool_part["input"], {"page_no": 1})
    # [Flow: 요약된 output — 핵심 필드 + _summary만 저장됨]
    check("output.ok 보존", tool_part["output"]["ok"], True)
    check("output.count 보존", tool_part["output"]["count"], 42)
    check_true("output._summary 보존", "_summary" in tool_part["output"])
    check("output._summary.truncated", tool_part["output"]["_summary"]["truncated"], True)
    check("output._summary.originalChars", tool_part["output"]["_summary"]["originalChars"], 8500)
    # [Flow: 원본 대용량 데이터는 저장되지 않음 — _summary 외의 큰 필드 없음]
    output_keys = [k for k in tool_part["output"].keys() if k != "_summary"]
    check_true("output에 핵심 필드만 (ok, count, page)", set(output_keys) == {"ok", "count", "page"})

    db.close()


# ─── 메인 ─────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  chat_conversations API 테스트 시작")
    print("=" * 60)

    test_list_excludes_messages_and_sorts_by_updated_desc()
    test_get_single_includes_messages()
    test_get_nonexistent_returns_none()
    test_upsert_inserts_new_conversation()
    test_upsert_updates_existing_conversation()
    test_delete_existing_conversation()
    test_delete_nonexistent_raises_404()
    test_other_user_cannot_access()
    test_large_tool_output_stored_as_compacted()

    print(f"\n{'='*60}")
    print(f"  결과: {PASS} passed, {FAIL} failed")
    print(f"{'='*60}")
