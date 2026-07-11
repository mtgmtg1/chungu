#!/usr/bin/env python3
# [Flow: Step 1 (Base 상속) -> Step 2 (Job/AdminUser/AppSetting 정의)]
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .session import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class User(Base):
    """Supabase auth.users와 1:1 연결되는 앱 사용자 프로필."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    points_balance: Mapped[int] = mapped_column(Integer, default=0)  # milli-USD (1/1000 달러)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_developer: Mapped[bool] = mapped_column(Boolean, default=True)
    language: Mapped[str] = mapped_column(String(10), default="en")
    # AI 에이전트 도구 승인 모드 ('ask' = 승인 버튼 표시, 'always' = 항상 자동 승인)
    ai_tool_approval_mode: Mapped[str] = mapped_column(String(10), default="ask")
    # 자동 충전 설정
    auto_recharge_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_recharge_threshold: Mapped[int] = mapped_column(Integer, default=2000)  # milli-USD ($2.00)
    auto_recharge_amount: Mapped[int] = mapped_column(Integer, default=10)  # 달러 ($10)
    paddle_customer_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    auto_recharge_retries: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # 구독 요금제 (Free / Pro / Max)
    subscription_plan: Mapped[str] = mapped_column(String(20), default="free")
    subscription_status: Mapped[str] = mapped_column(String(20), default="inactive")
    subscription_period_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    subscription_period_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    subscription_price_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    paddle_subscription_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    jobs: Mapped[list["Job"]] = relationship("Job", back_populates="user", lazy="selectin")
    payments: Mapped[list["Payment"]] = relationship("Payment", back_populates="user", lazy="selectin")
    point_transactions: Mapped[list["PointTransaction"]] = relationship("PointTransaction", back_populates="user", lazy="selectin")
    api_keys: Mapped[list["ApiKey"]] = relationship("ApiKey", back_populates="user", lazy="selectin")
    api_usage: Mapped[list["ApiUsage"]] = relationship("ApiUsage", back_populates="user", lazy="selectin")
    on_premise_inquiries: Mapped[list["OnPremiseInquiry"]] = relationship("OnPremiseInquiry", back_populates="user", lazy="selectin")
    subscription_usages: Mapped[list["SubscriptionUsage"]] = relationship("SubscriptionUsage", back_populates="user", lazy="selectin")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    # queued / rendering / ocr / merging / done / error

    pipeline: Mapped[str] = mapped_column(String(10), default="vision")
    endpoint: Mapped[str] = mapped_column(String(255), default="")
    model: Mapped[str] = mapped_column(String(255), default="")
    columns: Mapped[list] = mapped_column(JSON, default=list)
    prompt: Mapped[str] = mapped_column(Text, default="")
    dpi: Mapped[int] = mapped_column(Integer, default=150)
    use_docling_refinement: Mapped[bool] = mapped_column(Boolean, default=False)
    ocr_model: Mapped[str] = mapped_column(String(10), default="premium")  # basic | premium
    ocr_engine: Mapped[str] = mapped_column(String(10), default="easyocr")  # tesseract | easyocr | rapidocr

    original_filename: Mapped[str] = mapped_column(String(512), default="")
    file_type: Mapped[str] = mapped_column(String(20), default="pdf")
    total_pages: Mapped[int] = mapped_column(Integer, default=0)
    done_pages: Mapped[int] = mapped_column(Integer, default=0)
    total_files: Mapped[int] = mapped_column(Integer, default=0)
    done_files: Mapped[int] = mapped_column(Integer, default=0)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    media_duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    total_work_units: Mapped[int] = mapped_column(Integer, default=0)
    extracted_files: Mapped[list] = mapped_column(JSON, default=list)
    error_log: Mapped[str] = mapped_column(Text, default="")
    cost_points: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    # 구독 사용량 예약 기록 (예약/환불 멱등성 및 정확한 기간 추적용)
    reserved_basic_pages: Mapped[int] = mapped_column(Integer, default=0)
    reserved_premium_pages: Mapped[int] = mapped_column(Integer, default=0)
    reserved_media_seconds: Mapped[int] = mapped_column(Integer, default=0)
    reserved_period_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Excel 고급 변환 구독 사용량 예약 기록 (환불용)
    xlsx_advanced_reserved_pages: Mapped[int] = mapped_column(Integer, default=0)
    xlsx_advanced_reserved_period_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # PDF 하이라이트/여백 주석 (원본 스캔 PDF에 형광펜 + 여백 코멘트 생성)
    annotate_instruction: Mapped[str] = mapped_column(Text, default="")
    annotate_mode: Mapped[str] = mapped_column(String(20), default="highlight")  # highlight | margin_note | both
    annotate_comment_mode: Mapped[str] = mapped_column(String(20), default="user_text")  # user_text | llm_summary
    annotate_advanced: Mapped[bool] = mapped_column(Boolean, default=False)  # True=Vision LLM 고급주석
    annotate_status: Mapped[str] = mapped_column(String(20), default="")  # "" | processing | done | error
    annotate_job_id: Mapped[str] = mapped_column(String(32), default="")
    annotate_recovery_notes: Mapped[list] = mapped_column(JSON, default=list)
    annotate_refundable: Mapped[bool] = mapped_column(Boolean, default=False)
    annotate_reserved_pages: Mapped[int] = mapped_column(Integer, default=0)
    annotate_reserved_period_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    result_ocr_layout_storage_path: Mapped[str] = mapped_column(String(1024), default="")
    result_annotated_pdf_storage_path: Mapped[str] = mapped_column(String(1024), default="")
    searchable_pdf_storage_path: Mapped[str] = mapped_column(String(1024), default="")
    annotated_pdf_files: Mapped[list] = mapped_column(JSON, default=list)
    annotated_pdf_next_index: Mapped[int] = mapped_column(Integer, default=0)

    # Supabase Storage 경로 (로컬 경로 대체)
    pdf_storage_path: Mapped[str] = mapped_column(String(1024), default="")
    result_csv_storage_path: Mapped[str] = mapped_column(String(1024), default="")
    result_md_storage_path: Mapped[str] = mapped_column(String(1024), default="")
    result_xlsx_storage_path: Mapped[str] = mapped_column(String(1024), default="")
    result_docx_storage_path: Mapped[str] = mapped_column(String(1024), default="")
    result_pptx_storage_path: Mapped[str] = mapped_column(String(1024), default="")
    result_edited_md_storage_path: Mapped[str] = mapped_column(String(1024), default="")
    result_edited_xlsx_storage_path: Mapped[str] = mapped_column(String(1024), default="")

    # 엑셀 기본/고급 변환 결과 (기존 xlsx는 기본 변환으로 통합)
    result_xlsx_basic_storage_path: Mapped[str] = mapped_column(String(1024), default="")
    result_xlsx_advanced_storage_path: Mapped[str] = mapped_column(String(1024), default="")
    result_xlsx_advanced_job_id: Mapped[str] = mapped_column(String(64), default="")
    xlsx_basic_converted: Mapped[bool] = mapped_column(Boolean, default=False)
    xlsx_advanced_converted: Mapped[bool] = mapped_column(Boolean, default=False)
    xlsx_advanced_status: Mapped[str] = mapped_column(String(20), default="")
    xlsx_advanced_recovery_notes: Mapped[list] = mapped_column(JSON, default=list)
    xlsx_advanced_refundable: Mapped[bool] = mapped_column(Boolean, default=False)

    # 문서 파싱 최종 실패 시 사용자 재시도/환불 가능 여부
    refundable: Mapped[bool] = mapped_column(Boolean, default=False)

    # 하위 호환: 로컬 파일 경로
    result_csv_path: Mapped[str] = mapped_column(String(1024), default="")
    result_md_path: Mapped[str] = mapped_column(String(1024), default="")
    result_xlsx_path: Mapped[str] = mapped_column(String(1024), default="")
    result_docx_path: Mapped[str] = mapped_column(String(1024), default="")
    result_pptx_path: Mapped[str] = mapped_column(String(1024), default="")
    result_edited_md_path: Mapped[str] = mapped_column(String(1024), default="")
    download_token: Mapped[str] = mapped_column(String(64), default="", index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="jobs")


class Payment(Base):
    """Paddle 결제 내역."""

    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(20), default="paddle")
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    points_added: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, paid, failed, cancelled
    external_id: Mapped[str] = mapped_column(String(255), default="", index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="payments")


class PointTransaction(Base):
    """포인트 충전/차감 내역."""

    __tablename__ = "point_transactions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(20), default="")  # charge, spend, refund
    amount: Mapped[int] = mapped_column(Integer, default=0)
    balance_after: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="point_transactions")


class AdminUser(Base):
    __tablename__ = "admin_users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=datetime.utcnow)


class AppSetting(Base):
    """key-value 런타임 설정. 민감값(value_encrypted=True)은 암호화 저장."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    encrypted: Mapped[int] = mapped_column(Integer, default=0)  # 0/1
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=datetime.utcnow)


class ApiKey(Base):
    """개발자 API key. 평문은 저장하지 않고 hash만 보관."""

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(100), default="")
    key_hash: Mapped[str] = mapped_column(String(255), index=True)
    prefix: Mapped[str] = mapped_column(String(16), index=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    rate_limit_rpm: Mapped[int] = mapped_column(Integer, default=60)
    daily_quota: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="api_keys")
    api_usage: Mapped[list["ApiUsage"]] = relationship("ApiUsage", back_populates="api_key", lazy="selectin")


class ApiUsage(Base):
    """API key별 사용 내역."""

    __tablename__ = "api_usage"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    api_key_id: Mapped[str] = mapped_column(String(32), ForeignKey("api_keys.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    endpoint: Mapped[str] = mapped_column(String(255), default="")
    job_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    points_spent: Mapped[int] = mapped_column(Integer, default=0)
    http_status: Mapped[int] = mapped_column(Integer, default=0)
    client_ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    api_key: Mapped["ApiKey"] = relationship("ApiKey", back_populates="api_usage")
    user: Mapped["User"] = relationship("User", back_populates="api_usage")


class DailyUsage(Base):
    """사용자별 일일 기본모델 무료 한도 추적."""

    __tablename__ = "daily_usage"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    date: Mapped[datetime] = mapped_column(Date, index=True)
    pages_used: Mapped[int] = mapped_column(Integer, default=0)


class OnPremiseInquiry(Base):
    """온프레미스 로컬 서버 견적 문의."""

    __tablename__ = "on_premise_inquiries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pages_per_hour: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_price: Mapped[int] = mapped_column(Integer, nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    agreed_terms: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User | None"] = relationship("User", back_populates="on_premise_inquiries")


class SubscriptionUsage(Base):
    """사용자별 구독 기간 사용량 (월간 기준)."""

    __tablename__ = "subscription_usages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    period_start: Mapped[datetime] = mapped_column(DateTime, index=True)
    basic_pages: Mapped[int] = mapped_column(Integer, default=0)
    premium_pages: Mapped[int] = mapped_column(Integer, default=0)
    media_seconds: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship("User", back_populates="subscription_usages")


class AgentRun(Base):
    """LangGraph 기반 에이전트 실행 기록.

    PDF AI 주석과 마크다운 에디터 AI의 멀티스텝 실행 상태를 추적하고,
    interrupt가 발생한 경우 사용자 승인/거절을 재개할 수 있도록 thread_id를 저장한다.
    """

    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    job_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("jobs.id"), nullable=True, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    graph_name: Mapped[str] = mapped_column(String(32), default="")  # "annotator" | "editor"
    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | interrupted | done | error | cancelled
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    pending_interrupt: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    job: Mapped["Job | None"] = relationship("Job", lazy="selectin")
    user: Mapped["User | None"] = relationship("User", lazy="selectin")


class Sandbox(Base):
    """Kata Containers 기반 에이전트 샌드박스 실행 기록.

    각 sandbox 는 1개의 Kata VM 에 대응하며,
    workspace (/data/jobs/{job_id}) 를 virtio-fs 로 VM 내부 /workspace 에 마운트한다.
    """

    __tablename__ = "sandboxes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    job_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("jobs.id"), nullable=True, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    container_name: Mapped[str] = mapped_column(String(128), default="")
    container_id: Mapped[str] = mapped_column(String(64), default="")
    runtime: Mapped[str] = mapped_column(String(32), default="io.containerd.kata-clh.v2")
    status: Mapped[str] = mapped_column(String(20), default="creating", index=True)
    # creating | running | stopped | error | destroyed
    workspace_path: Mapped[str] = mapped_column(Text, default="")
    resource_limits: Mapped[dict] = mapped_column(JSON, default=lambda: {"cpu": 1, "memory_mb": 2048})
    dense_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
    destroyed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    job: Mapped["Job | None"] = relationship("Job", lazy="selectin")
    user: Mapped["User | None"] = relationship("User", lazy="selectin")


class FlowDrawing(Base):
    """Flow Panel 드로잉/주석 저장 — 작업+사용자별 1레코드.

    사용자가 React Flow 캔버스에 그린 SVG path 드로잉과 텍스트 주석을 저장.
    paths: DrawingPath[] (d, stroke, strokeWidth, type, shapeType)
    text_annotations: TextAnnotation[] (id, x, y, text, fontSize, color)
    """

    __tablename__ = "flow_drawings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[str] = mapped_column(String(255), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    paths: Mapped[list] = mapped_column(JSON, default=list)
    text_annotations: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    job: Mapped["Job"] = relationship("Job", lazy="selectin")
    user: Mapped["User"] = relationship("User", lazy="selectin")
