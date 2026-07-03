---
sidebar_position: 100
---

# 변경 이력

## 2026-07

- 결제 시스템을 KRW 포인트에서 **USD 크레딧 (milli-USD)**으로 전환
- Toss 결제 연동 제거 — **Paddle**이 유일한 결제 제공자
- 자유 금액 크레딧 구매 ($5–$500 USD) 및 자동 충전 지원 추가
- 업로드 엔드포인트에 `ocr_model` 파라미터 (`basic` / `premium`) 추가
- 업로드 엔드포인트에 `ocr_engine` 파라미터 (`tesseract` / `easyocr` / `rapidocr`) 추가
- XLSX 출력을 `xlsx_basic`과 `xlsx_advanced` 형식으로 분리
- 문서 파싱 재시도/환불을 위한 `POST /jobs/{id}/action` 엔드포인트 추가
- XLSX 고급 변환 재시도/환불을 위한 `POST /jobs/{id}/xlsx-advanced-action` 엔드포인트 추가
- 기본 모델: 하루 100페이지 무료
- 파일당 최대 페이지 수 10,000으로 증가
- 계정 엔드포인트가 API 키 외에 세션 토큰도 지원

## 2026-06-27

- PROOF API v1 문서 사이트 출시
- 오디오 및 비디오 파일 처리 지원 추가
- XLSX, DOCX, PPTX 변환 엔드포인트 추가
- API 키 로테이션 엔드포인트 추가

## 2026-01-15

- API v1 최초 릴리스
- 엔드포인트: account, keys, jobs (upload, confirm, status, download)
- 포인트 기반 결제 시스템
- Vision 및 하이브리드 파이프라인
