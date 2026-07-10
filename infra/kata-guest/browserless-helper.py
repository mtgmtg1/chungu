#!/usr/bin/env python3
"""PROOF 에이전트 — browserless 원격 브라우저 헬퍼 (Python)

[Flow: Step 1 (browserless 서버 연결) -> Step 2 (새 페이지 생성) -> Step 3 (작업 수행) -> Step 4 (결과 저장)]

이 모듈은 a1 에 구동 중인 browserless 서버(http://192.168.1.50:20047)에 원격으로 연결하여
웹 브라우징 작업을 수행한다. VM 내부에 Chrome 을 설치하지 않아 메모리를 절약한다.

사용법:
    from browserless_helper import BrowserlessSession

    with BrowserlessSession() as session:
        screenshot = session.screenshot("https://example.com")
        session.save_to_workspace(screenshot, "/workspace/screenshot.png")

        pdf = session.print_to_pdf("https://example.com")
        session.save_to_workspace(pdf, "/workspace/page.pdf")
"""

import os
import asyncio
from typing import Optional

# browserless 서버 URL (a1, 기존 구동 중)
BROWSERLESS_URL = os.environ.get("BROWSERLESS_URL", "http://192.168.1.50:20047")

# browserless WebSocket 엔드포인트 (CDP 프로토콜)
BROWSERLESS_WS_URL = BROWSERLESS_URL.replace("http://", "ws://").replace("https://", "wss://")


class BrowserlessSession:
    """browserless 서버에 연결하여 웹 브라우징 작업을 수행하는 세션 클래스.

    매개변수:
        token: browserless API 토큰 (인증이 활성화된 경우)

    사용 예:
        with BrowserlessSession(token="xxx") as session:
            png = session.screenshot("https://example.com")
    """

    def __init__(self, token: Optional[str] = None):
        self.token = token
        self.browser = None

    async def _connect(self):
        """browserless 서버에 CDP WebSocket 으로 연결한다."""
        from pyppeteer import connect

        ws_endpoint = BROWSERLESS_WS_URL
        if self.token:
            ws_endpoint = f"{ws_endpoint}?token={self.token}"

        self.browser = await connect(browserWSEndpoint=ws_endpoint)
        return self.browser

    async def _screenshot_async(self, url: str, full_page: bool = True) -> bytes:
        """URL 의 스크린샷을 캡처하여 PNG 바이트를 반환한다.

        매개변수:
            url: 캡처할 웹페이지 URL
            full_page: 전체 페이지 캡처 여부

        반환값:
            PNG 이미지 바이트
        """
        if not self.browser:
            await self._connect()

        page = await self.browser.newPage()
        try:
            await page.goto(url, {"waitUntil": "networkidle0", "timeout": 30000})
            screenshot = await page.screenshot({"fullPage": full_page})
            return screenshot
        finally:
            await page.close()

    async def _print_to_pdf_async(self, url: str) -> bytes:
        """URL 의 페이지를 PDF 로 변환하여 바이트를 반환한다.

        매개변수:
            url: PDF 로 변환할 웹페이지 URL

        반환값:
            PDF 바이트
        """
        if not self.browser:
            await self._connect()

        page = await self.browser.newPage()
        try:
            await page.goto(url, {"waitUntil": "networkidle0", "timeout": 30000})
            pdf = await page.pdf({"format": "A4", "printBackground": True})
            return pdf
        finally:
            await page.close()

    async def _extract_text_async(self, url: str) -> str:
        """URL 의 페이지 텍스트를 추출하여 반환한다.

        매개변수:
            url: 텍스트를 추출할 웹페이지 URL

        반환값:
            페이지 텍스트
        """
        if not self.browser:
            await self._connect()

        page = await self.browser.newPage()
        try:
            await page.goto(url, {"waitUntil": "networkidle0", "timeout": 30000})
            text = await page.evaluate("() => document.body.innerText")
            return text
        finally:
            await page.close()

    async def _close_async(self):
        """browserless 연결을 종료한다."""
        if self.browser:
            await self.browser.close()
            self.browser = None

    # --- 동기 래퍼 메서드 ---

    def screenshot(self, url: str, full_page: bool = True) -> bytes:
        """URL 의 스크린샷을 캡처한다. (동기 래퍼)"""
        return asyncio.get_event_loop().run_until_complete(
            self._screenshot_async(url, full_page)
        )

    def print_to_pdf(self, url: str) -> bytes:
        """URL 의 페이지를 PDF 로 변환한다. (동기 래퍼)"""
        return asyncio.get_event_loop().run_until_complete(
            self._print_to_pdf_async(url)
        )

    def extract_text(self, url: str) -> str:
        """URL 의 페이지 텍스트를 추출한다. (동기 래퍼)"""
        return asyncio.get_event_loop().run_until_complete(
            self._extract_text_async(url)
        )

    def save_to_workspace(self, data: bytes, path: str):
        """바이트 데이터를 workspace 경로에 저장한다.

        매개변수:
            data: 저장할 바이트 데이터
            path: 저장 경로 (/workspace/ 하위)
        """
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        asyncio.get_event_loop().run_until_complete(self._close_async())


# --- CLI 진입점 (단독 실행 시) ---
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("사용법: python3 browserless-helper.py <command> <url> [output_path]")
        print("  command: screenshot | pdf | text")
        print("  예: python3 browserless-helper.py screenshot https://example.com /workspace/shot.png")
        sys.exit(1)

    command = sys.argv[1]
    url = sys.argv[2]
    output = sys.argv[3] if len(sys.argv) > 3 else None

    with BrowserlessSession() as session:
        if command == "screenshot":
            data = session.screenshot(url)
            if output:
                session.save_to_workspace(data, output)
                print(f"스크린샷 저장: {output}")
            else:
                sys.stdout.buffer.write(data)

        elif command == "pdf":
            data = session.print_to_pdf(url)
            if output:
                session.save_to_workspace(data, output)
                print(f"PDF 저장: {output}")
            else:
                sys.stdout.buffer.write(data)

        elif command == "text":
            text = session.extract_text(url)
            if output:
                with open(output, "w") as f:
                    f.write(text)
                print(f"텍스트 저장: {output}")
            else:
                print(text)

        else:
            print(f"알 수 없는 명령: {command}")
            sys.exit(1)
