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
        raise RuntimeError("SMTP settings are empty (configure via admin page)")

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
    send_email(db, to, "[PROOF] SMTP 테스트 메일", "<p>SMTP 설정이 정상 작동합니다.</p>")


def send_on_premise_inquiry_email(db: Session, inquiry) -> None:
    """온프레미스 로컬 서버 문의 접수 메일을 admin에게 발송한다."""
    subject = f"[PROOF 온프레미스 문의] {inquiry.company or '개인/미기업'} - {inquiry.pages_per_hour:,}장/시간"
    html = f"""
    <div style="font-family:sans-serif;max-width:600px;margin:auto;padding:24px">
      <h2 style="color:#1f2937;margin-bottom:16px">PROOF 온프레미스 로컬 서버 문의</h2>
      <table style="width:100%;border-collapse:collapse;font-size:14px;color:#374151">
        <tr><td style="border:1px solid #e5e7eb;padding:10px;width:140px"><b>문의 ID</b></td><td style="border:1px solid #e5e7eb;padding:10px">{inquiry.id}</td></tr>
        <tr><td style="border:1px solid #e5e7eb;padding:10px"><b>담당자 이메일</b></td><td style="border:1px solid #e5e7eb;padding:10px">{inquiry.email}</td></tr>
        <tr><td style="border:1px solid #e5e7eb;padding:10px"><b>회사명</b></td><td style="border:1px solid #e5e7eb;padding:10px">{inquiry.company or '-'}</td></tr>
        <tr><td style="border:1px solid #e5e7eb;padding:10px"><b>담당자명</b></td><td style="border:1px solid #e5e7eb;padding:10px">{inquiry.contact_name or '-'}</td></tr>
        <tr><td style="border:1px solid #e5e7eb;padding:10px"><b>국가/지역</b></td><td style="border:1px solid #e5e7eb;padding:10px">{inquiry.country or '-'}</td></tr>
        <tr><td style="border:1px solid #e5e7eb;padding:10px"><b>희망 처리량</b></td><td style="border:1px solid #e5e7eb;padding:10px">{inquiry.pages_per_hour:,}장/시간</td></tr>
        <tr><td style="border:1px solid #e5e7eb;padding:10px"><b>예상 가격</b></td><td style="border:1px solid #e5e7eb;padding:10px">${inquiry.estimated_price:,}</td></tr>
        <tr><td style="border:1px solid #e5e7eb;padding:10px"><b>약관 동의</b></td><td style="border:1px solid #e5e7eb;padding:10px">{'동의' if inquiry.agreed_terms else '미동의'}</td></tr>
      </table>
      <h3 style="margin-top:24px;margin-bottom:8px;font-size:16px;color:#1f2937">추가 문의사항</h3>
      <div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:16px;white-space:pre-wrap">
        {inquiry.message or '없음'}
      </div>
      <p style="margin-top:24px;color:#6b7280;font-size:13px">
        PROOF Admin Dashboard에서 상태를 변경할 수 있습니다.
      </p>
    </div>
    """
    send_email(db, "admin@proof.teamcat.app", subject, html)


# [Flow: Step 1 (언어별 문자열 선택) -> Step 2 (다운로드/결과 URL 생성) -> Step 3 (HTML 본문 조립)]
_DONE_T = {
    "ko": {"subject": "변환 완료: {}", "title": "변환이 완료되었습니다", "file_label": "파일", "download_guide": "결과 페이지에서 다양한 형식의 파일을 내려받을 수 있습니다. (링크는 {}일 후 만료됩니다)", "result_guide": "엑셀 다운로드 및 고급변환도 결과 페이지에서 이용할 수 있습니다.", "result_btn": "결과 페이지 열기 →", "footer": "작업 ID: {} · PROOF — PDF/미디어 → 표 변환 서비스"},
    "en": {"subject": "Conversion Complete: {}", "title": "Conversion Complete", "file_label": "File", "download_guide": "You can download files in various formats from the result page. (Link expires in {} days)", "result_guide": "Excel download and advanced conversion are also available on the result page.", "result_btn": "Open Result Page →", "footer": "Job ID: {} · PROOF — PDF/Media → Table Conversion Service"},
    "ja": {"subject": "変換完了: {}", "title": "変換が完了しました", "file_label": "ファイル", "download_guide": "結果ページで様々な形式のファイルをダウンロードできます。（リンクは{}日後に期限切れになります）", "result_guide": "Excelダウンロードおよび高度な変換も結果ページで利用できます。", "result_btn": "結果ページを開く →", "footer": "ジョブID: {} · PROOF — PDF/メディア → テーブル変換サービス"},
}


def build_done_email(job_id: str, filename: str, expires_days: int, lang: str = "en") -> tuple[str, str]:
    """완료 메일 제목/본문 생성 (결과 페이지 링크 포함, 다국어 지원)."""
    t = _DONE_T.get(lang, _DONE_T["en"])
    base = settings.public_base_url.rstrip("/")
    result_url = f"{base}/jobs/{job_id}"
    subject = f"[PROOF] {t['subject'].format(filename)}"
    html = f"""
    <div style="font-family:sans-serif;max-width:560px;margin:auto;padding:24px">
      <div style="text-align:center;margin-bottom:24px">
        <h1 style="color:#2563eb;font-size:24px;margin:0">PROOF</h1>
        <p style="color:#6b7280;font-size:13px;margin:4px 0 0">Precision Data Conversion</p>
      </div>
      <h2 style="font-size:20px;color:#1f2937;margin-bottom:12px">{t['title']}</h2>
      <p style="color:#374151;font-size:15px;margin-bottom:16px">{t['file_label']}: <b>{filename}</b></p>
      <p style="color:#6b7280;font-size:14px;margin-bottom:20px">{t['download_guide'].format(expires_days)}</p>
      <div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:16px;margin-bottom:20px">
        <p style="color:#374151;font-size:14px;margin:0 0 8px">{t['result_guide']}</p>
        <a href="{result_url}" style="display:inline-block;padding:10px 20px;background:#6366f1;color:#fff;text-decoration:none;border-radius:6px;font-weight:600;font-size:14px">{t['result_btn']}</a>
      </div>
      <p style="color:#9ca3af;font-size:12px;border-top:1px solid #e5e7eb;padding-top:16px;margin-top:24px">{t['footer'].format(job_id)}</p>
    </div>
    """
    return subject, html


_ERROR_T = {
    "ko": {"subject": "변환 실패: {}", "title": "PDF 변환에 실패했습니다", "file_label": "파일", "job_id_label": "작업 ID"},
    "en": {"subject": "Conversion Failed: {}", "title": "PDF Conversion Failed", "file_label": "File", "job_id_label": "Job ID"},
    "ja": {"subject": "変換失敗: {}", "title": "PDF変換に失敗しました", "file_label": "ファイル", "job_id_label": "ジョブID"},
}


def build_error_email(job_id: str, filename: str, error: str, lang: str = "en") -> tuple[str, str]:
    t = _ERROR_T.get(lang, _ERROR_T["en"])
    subject = f"[PROOF] {t['subject'].format(filename)}"
    html = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:auto">
      <h2 style="color:#dc2626">{t['title']}</h2>
      <p>{t['file_label']}: <b>{filename}</b></p>
      <pre style="background:#f3f4f6;padding:12px;border-radius:6px;white-space:pre-wrap">{error}</pre>
      <p style="color:#888;font-size:12px">{t['job_id_label']}: {job_id}</p>
    </div>
    """
    return subject, html
