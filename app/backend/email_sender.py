#!/usr/bin/env python3
# [Flow: Step 1 (DB에서 SMTP 설정 로드) -> Step 2 (메시지 작성) -> Step 3 (SMTP 발송)]
import smtplib
from email.message import EmailMessage

from sqlalchemy.orm import Session

from . import settings_store
from .config import settings


def _smtp_config(db: Session) -> dict:
    return {
        "host": settings_store.get_setting(db, "smtp_host"),
        "port": int(settings_store.get_setting(db, "smtp_port") or "587"),
        "user": settings_store.get_setting(db, "smtp_user"),
        "password": settings_store.get_setting(db, "smtp_password"),
        "from": settings_store.get_setting(db, "smtp_from") or settings_store.get_setting(db, "smtp_user"),
        "use_tls": settings_store.get_setting(db, "smtp_use_tls") == "1",
    }


def send_email(db: Session, to: str, subject: str, body_html: str) -> None:
    """DB의 SMTP 설정으로 HTML 메일을 보낸다. 미설정 시 예외."""
    cfg = _smtp_config(db)
    if not cfg["host"]:
        raise RuntimeError("SMTP 설정이 비어 있습니다 (관리자 페이지에서 입력하세요)")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["from"]
    msg["To"] = to
    msg.set_content("HTML 메일입니다. HTML 지원 클라이언트로 확인하세요.")
    msg.add_alternative(body_html, subtype="html")

    with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as server:
        if cfg["use_tls"]:
            server.starttls()
        if cfg["user"]:
            server.login(cfg["user"], cfg["password"])
        server.send_message(msg)


def send_test_email(db: Session, to: str) -> None:
    send_email(db, to, "[Chungu] SMTP 테스트 메일", "<p>SMTP 설정이 정상 작동합니다.</p>")


def build_done_email(job_id: str, filename: str, expires_days: int) -> tuple[str, str]:
    """완료 메일 제목/본문 생성 (다운로드 링크 포함)."""
    base = settings.public_base_url.rstrip("/")
    csv_url = f"{base}/api/download/{job_id}?type=csv"
    md_url = f"{base}/api/download/{job_id}?type=md"
    subject = f"[Chungu] 변환 완료: {filename}"
    html = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:auto">
      <h2>PDF 변환이 완료되었습니다</h2>
      <p>파일: <b>{filename}</b></p>
      <p>아래 링크에서 결과를 내려받으세요. (링크는 {expires_days}일 후 만료됩니다)</p>
      <p>
        <a href="{csv_url}" style="display:inline-block;padding:10px 18px;background:#2563eb;color:#fff;text-decoration:none;border-radius:6px;margin-right:8px">CSV 다운로드</a>
        <a href="{md_url}" style="display:inline-block;padding:10px 18px;background:#16a34a;color:#fff;text-decoration:none;border-radius:6px">Markdown 다운로드</a>
      </p>
      <p style="color:#888;font-size:12px">작업 ID: {job_id}</p>
    </div>
    """
    return subject, html


def build_error_email(job_id: str, filename: str, error: str) -> tuple[str, str]:
    subject = f"[Chungu] 변환 실패: {filename}"
    html = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:auto">
      <h2 style="color:#dc2626">PDF 변환에 실패했습니다</h2>
      <p>파일: <b>{filename}</b></p>
      <pre style="background:#f3f4f6;padding:12px;border-radius:6px;white-space:pre-wrap">{error}</pre>
      <p style="color:#888;font-size:12px">작업 ID: {job_id}</p>
    </div>
    """
    return subject, html
