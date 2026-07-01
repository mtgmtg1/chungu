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
    points_balance: Mapped[int] = mapped_column(Integer, default=0)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_developer: Mapped[bool] = mapped_column(Boolean, default=True)
    language: Mapped[str] = mapped_column(String(10), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    jobs: Mapped[list["Job"]] = relationship("Job", back_populates="user", lazy="selectin")
    payments: Mapped[list["Payment"]] = relationship("Payment", back_populates="user", lazy="selectin")
    point_transactions: Mapped[list["PointTransaction"]] = relationship("PointTransaction", back_populates="user", lazy="selectin")
    api_keys: Mapped[list["ApiKey"]] = relationship("ApiKey", back_populates="user", lazy="selectin")
    api_usage: Mapped[list["ApiUsage"]] = relationship("ApiUsage", back_populates="user", lazy="selectin")


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
    media_duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    extracted_files: Mapped[list] = mapped_column(JSON, default=list)
    error_log: Mapped[str] = mapped_column(Text, default="")
    cost_points: Mapped[int] = mapped_column(Integer, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    # Supabase Storage 경로 (로컬 경로 대체)
    pdf_storage_path: Mapped[str] = mapped_column(String(1024), default="")
    result_csv_storage_path: Mapped[str] = mapped_column(String(1024), default="")
    result_md_storage_path: Mapped[str] = mapped_column(String(1024), default="")
    result_xlsx_storage_path: Mapped[str] = mapped_column(String(1024), default="")
    result_docx_storage_path: Mapped[str] = mapped_column(String(1024), default="")
    result_pptx_storage_path: Mapped[str] = mapped_column(String(1024), default="")
    result_edited_md_storage_path: Mapped[str] = mapped_column(String(1024), default="")

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
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="jobs")


class Payment(Base):
    """Toss / Paddle 결제 내역."""

    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(20), default="")  # toss, paddle
    currency: Mapped[str] = mapped_column(String(3), default="KRW")  # KRW, USD
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
