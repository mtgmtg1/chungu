#!/usr/bin/env python3
# [Flow: Step 1 (테스트 케이스 정의) -> Step 2 (pdf_preview_converter 함수별 동작 검증) -> Step 3 (Unoserver 연동/소스 버킷/PPTX 변환 경로 검증)]
"""pdf_preview_converter.py의 source_bucket, Unoserver 연동, PPTX/HWP 변환 경로를 테스트한다."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import fitz
import pytest

from backend.config import settings
from backend.core.pdf_preview_converter import (
    _convert_to_pdf,
    _convert_with_unoserver,
    _preview_pdf_path,
    _unoserver_ready,
    get_preview_pdf_url,
)


def _make_pdf_file(path: Path) -> Path:
    """테스트용 1페이지 PDF 파일을 생성한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    doc.new_page()
    doc.save(str(path))
    doc.close()
    return path


def _make_settings_mock(**overrides) -> settings.__class__:
    """unoserver 관련 설정을 오버라이드한 settings 복사본을 생성한다."""
    return settings.model_copy(
        update={
            "unoserver_enabled": False,
            "unoserver_host": "unoserver",
            "unoserver_port": 2003,
            "unoserver_timeout": 120,
            **overrides,
        }
    )


@pytest.fixture
def mock_supabase_module(monkeypatch):
    """pdf_preview_converter 모듈 내부의 supabase_client를 모킹한다."""
    mock = MagicMock()
    mock.get_service_client.return_value.storage.from_.return_value.download.return_value = b"fake-file-bytes"
    mock.get_signed_download_url.return_value = "https://signed.example.com/preview.pdf"
    monkeypatch.setattr("backend.core.pdf_preview_converter.supabase_client", mock)
    return mock


# ---------------------------------------------------------------------------
# get_preview_pdf_url: source_bucket 및 캐싱
# ---------------------------------------------------------------------------
class TestGetPreviewPdfUrl:
    """get_preview_pdf_url의 source_bucket 처리와 캐싱 동작을 검증한다."""

    def test_downloads_from_source_bucket_and_uploads_to_preview_bucket(
        self,
        tmp_path: Path,
        monkeypatch,
        mock_supabase_module: MagicMock,
    ):
        # [Flow: 원본이 jobs 버킷 -> 미리보기 PDF는 pdfs/preview_pdfs/에 업로드 -> 서명 URL 반환]
        monkeypatch.setattr("backend.core.pdf_preview_converter.settings", _make_settings_mock())
        monkeypatch.setattr(
            "backend.core.pdf_preview_converter._get_existing_preview_url",
            lambda path, expires: None,
        )

        def fake_convert(input_path: Path, output_dir: Path) -> Path:
            """Unoserver/LibreOffice 변환을 모방하여 PDF를 생성한다."""
            output = output_dir / "converted.pdf"
            _make_pdf_file(output)
            return output

        monkeypatch.setattr("backend.core.pdf_preview_converter._convert_to_pdf", fake_convert)

        result = get_preview_pdf_url(
            "jobs/agent_output/output.pptx",
            source_bucket="jobs",
            expires_in=3600,
        )

        assert result == "https://signed.example.com/preview.pdf"

        storage = mock_supabase_module.get_service_client.return_value.storage
        # 원본 다운로드는 source_bucket(jobs)에서 수행
        storage.from_.assert_any_call("jobs")
        storage.from_("jobs").download.assert_called_once_with("jobs/agent_output/output.pptx")

        # 미리보기 업로드는 pdfs 버킷의 preview_pdfs 프리픽스로 수행
        preview_path = _preview_pdf_path("jobs/agent_output/output.pptx")
        storage.from_.assert_any_call("pdfs")
        mock_supabase_module.get_signed_download_url.assert_called_once_with(
            preview_path,
            bucket="pdfs",
            expires_in=3600,
        )

    def test_returns_existing_preview_without_re_conversion(
        self,
        monkeypatch,
        mock_supabase_module: MagicMock,
    ):
        monkeypatch.setattr(
            "backend.core.pdf_preview_converter._get_existing_preview_url",
            lambda path, expires: "https://existing.example.com/preview.pdf",
        )

        result = get_preview_pdf_url("some/file.pptx", source_bucket="pdfs")

        assert result == "https://existing.example.com/preview.pdf"
        mock_supabase_module.get_service_client.assert_not_called()

    def test_returns_none_when_original_download_fails(
        self,
        monkeypatch,
        mock_supabase_module: MagicMock,
    ):
        mock_supabase_module.get_service_client.return_value.storage.from_.return_value.download.side_effect = Exception("storage error")
        monkeypatch.setattr("backend.core.pdf_preview_converter.settings", _make_settings_mock())
        monkeypatch.setattr(
            "backend.core.pdf_preview_converter._get_existing_preview_url",
            lambda path, expires: None,
        )

        result = get_preview_pdf_url("some/file.pptx", source_bucket="pdfs")

        assert result is None


# ---------------------------------------------------------------------------
# _convert_to_pdf: Unoserver 우선 / LibreOffice fallback / HWP ODT 경로
# ---------------------------------------------------------------------------
class TestConvertToPdf:
    """_convert_to_pdf의 변환 엔진 분기를 검증한다."""

    def test_pptx_prefers_unoserver_when_enabled_and_ready(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        # [Flow: unoserver_enabled=True + ready=True -> UnoClient로 PPTX->PDF 변환]
        monkeypatch.setattr("backend.core.pdf_preview_converter.settings", _make_settings_mock(unoserver_enabled=True))
        monkeypatch.setattr("backend.core.pdf_preview_converter._unoserver_ready", lambda h, p: True)

        with patch("backend.core.pdf_preview_converter._convert_with_unoserver", create=True) as mock_uno, \
             patch("backend.core.pdf_preview_converter._run_libreoffice") as mock_lo:
            expected_pdf = tmp_path / "converted.pdf"
            _make_pdf_file(expected_pdf)
            mock_uno.return_value = expected_pdf

            input_path = tmp_path / "input.pptx"
            input_path.write_bytes(b"fake-pptx")
            result = _convert_to_pdf(input_path, tmp_path / "out")

            assert result == expected_pdf
            mock_uno.assert_called_once()
            mock_lo.assert_not_called()

    def test_pptx_falls_back_to_libreoffice_when_unoserver_disabled(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        # [Flow: unoserver_enabled=False -> 직접 libreoffice --headless 변환]
        monkeypatch.setattr("backend.core.pdf_preview_converter.settings", _make_settings_mock())

        with patch("backend.core.pdf_preview_converter._convert_with_unoserver", create=True) as mock_uno, \
             patch("backend.core.pdf_preview_converter._run_libreoffice") as mock_lo:
            expected_pdf = tmp_path / "converted.pdf"
            _make_pdf_file(expected_pdf)
            mock_lo.return_value = expected_pdf

            input_path = tmp_path / "input.pptx"
            input_path.write_bytes(b"fake-pptx")
            result = _convert_to_pdf(input_path, tmp_path / "out")

            assert result == expected_pdf
            mock_uno.assert_not_called()
            mock_lo.assert_called_once()

    def test_pptx_falls_back_to_libreoffice_when_unoserver_unreachable(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        # [Flow: unoserver_enabled=True but not reachable -> _unoserver_ready False -> libreoffice]
        monkeypatch.setattr("backend.core.pdf_preview_converter.settings", _make_settings_mock(unoserver_enabled=True))
        monkeypatch.setattr("backend.core.pdf_preview_converter._unoserver_ready", lambda h, p: False)

        with patch("backend.core.pdf_preview_converter._convert_with_unoserver", create=True) as mock_uno, \
             patch("backend.core.pdf_preview_converter._run_libreoffice") as mock_lo:
            expected_pdf = tmp_path / "converted.pdf"
            _make_pdf_file(expected_pdf)
            mock_lo.return_value = expected_pdf

            input_path = tmp_path / "input.pptx"
            input_path.write_bytes(b"fake-pptx")
            result = _convert_to_pdf(input_path, tmp_path / "out")

            assert result == expected_pdf
            mock_uno.assert_not_called()
            mock_lo.assert_called_once()

    def test_hwp_converts_to_odt_first_then_unoserver(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        # [Flow: .hwp -> hwp5odt -> ODT -> Unoserver PDF]
        monkeypatch.setattr("backend.core.pdf_preview_converter.settings", _make_settings_mock(unoserver_enabled=True))
        monkeypatch.setattr("backend.core.pdf_preview_converter._unoserver_ready", lambda h, p: True)

        odt_path = tmp_path / "input.odt"
        odt_path.write_bytes(b"fake-odt")
        final_pdf = tmp_path / "final.pdf"
        _make_pdf_file(final_pdf)

        with patch("backend.core.pdf_preview_converter._run_hwp5odt") as mock_hwp5odt, \
             patch("backend.core.pdf_preview_converter._convert_with_unoserver", create=True) as mock_uno, \
             patch("backend.core.pdf_preview_converter._run_libreoffice") as mock_lo:
            mock_hwp5odt.return_value = odt_path
            mock_uno.return_value = final_pdf

            input_path = tmp_path / "input.hwp"
            input_path.write_bytes(b"fake-hwp")
            result = _convert_to_pdf(input_path, tmp_path / "out")

            assert result == final_pdf
            mock_hwp5odt.assert_called_once()
            # ODT가 Unoserver로 전달되는지 확인
            mock_uno.assert_called_once()
            call_args, _ = mock_uno.call_args
            assert Path(call_args[0]).suffix == ".odt"
            mock_lo.assert_not_called()

    def test_hwp_falls_back_to_libreoffice_when_hwp5odt_fails(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        monkeypatch.setattr("backend.core.pdf_preview_converter.settings", _make_settings_mock())

        with patch("backend.core.pdf_preview_converter._run_hwp5odt") as mock_hwp5odt, \
             patch("backend.core.pdf_preview_converter._run_libreoffice") as mock_lo:
            expected_pdf = tmp_path / "converted.pdf"
            _make_pdf_file(expected_pdf)
            mock_hwp5odt.return_value = None
            mock_lo.return_value = expected_pdf

            input_path = tmp_path / "input.hwp"
            input_path.write_bytes(b"fake-hwp")
            result = _convert_to_pdf(input_path, tmp_path / "out")

            assert result == expected_pdf
            mock_hwp5odt.assert_called_once()
            mock_lo.assert_called_once()


# ---------------------------------------------------------------------------
# _unoserver_ready: 소켓 연결 확인
# ---------------------------------------------------------------------------
class TestUnoserverReady:
    """_unoserver_ready가 지정된 호스트/포트의 TCP 연결 가능성을 올바르게 판단한다."""

    def test_returns_true_when_port_is_open(self, monkeypatch):
        monkeypatch.setattr(
            "backend.core.pdf_preview_converter.socket.create_connection",
            lambda addr, timeout: MagicMock(__enter__=lambda s: s, __exit__=lambda *args: None),
        )

        assert _unoserver_ready("unoserver", 2003) is True

    def test_returns_false_when_connection_refused(self, monkeypatch):
        def raise_refused(*args, **kwargs):
            raise ConnectionRefusedError("refused")

        monkeypatch.setattr(
            "backend.core.pdf_preview_converter.socket.create_connection",
            raise_refused,
        )

        assert _unoserver_ready("unoserver", 2003) is False


# ---------------------------------------------------------------------------
# _convert_with_unoserver: UnoClient 호출
# ---------------------------------------------------------------------------
class TestConvertWithUnoserver:
    """_convert_with_unoserver가 올바른 인자로 UnoClient.convert를 호출한다."""

    def test_calls_uno_client_with_remote_location(
        self,
        tmp_path: Path,
        monkeypatch,
    ):
        monkeypatch.setattr(
            "backend.core.pdf_preview_converter.settings",
            _make_settings_mock(unoserver_enabled=True),
        )

        input_path = tmp_path / "input.pptx"
        input_path.write_bytes(b"fake-pptx")
        output_dir = tmp_path / "out"
        output_dir.mkdir()

        expected_pdf = output_dir / "input.pdf"

        mock_client = MagicMock()

        def fake_convert(*args, **kwargs):
            out = Path(kwargs.get("outpath"))
            _make_pdf_file(out)

        mock_client.convert.side_effect = fake_convert

        with patch("backend.core.pdf_preview_converter.UnoClient", return_value=mock_client) as mock_uno_cls:
            result = _convert_with_unoserver(input_path, output_dir)

            assert result == expected_pdf
            mock_uno_cls.assert_called_once_with(
                server="unoserver",
                port="2003",
                host_location="remote",
            )
            mock_client.convert.assert_called_once()
            _, call_kwargs = mock_client.convert.call_args
            assert call_kwargs.get("convert_to") == "pdf"
            assert Path(call_kwargs.get("inpath")) == input_path
            assert Path(call_kwargs.get("outpath")) == expected_pdf
