# PROOF API v1 문서

PROOF API v1은 외부 개발자가 PDF/이미지/오디오/비디오/마크다운을 업로드하고 선불 크레딧 시스템을 사용해 구조화된 표(CSV/MD/XLSX)를 추출할 수 있게 합니다. 크레딧은 **milli-USD** 단위입니다 (1,000 milli-USD = $1.00 USD).

## 기본 URL

모든 API 엔드포인트는 `/api/v1` 접두사를 사용합니다.

```
https://your-domain.com/api/v1
```

## 인증

API 키를 `X-API-Key` 헤더(또는 `Authorization: Bearer <key>`)로 전달하여 인증합니다.

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" https://your-domain.com/api/v1/account
```

API 키는 로그인 후 `/developer`의 **개발자 포털**에서 생성할 수 있습니다.

## 속도 제한

- 기본값: API 키당 분당 60회 요청.
- 동시 작업: 계정당 최대 5개(관리자가 설정 가능).
- 일일 크레딧 할당: 키별로 선택 사항.

초과 시 API는 `Retry-After` 헤더와 함께 `429 Too Many Requests`를 반환합니다.

## 가격

입력 유형과 선택한 모델에 따라 크레딧이 차감됩니다. 모든 금액은 milli-USD 단위입니다.

| 입력 | Basic 모델 | Premium 모델 |
|-------|-------------|---------------|
| PDF 페이지 | 1 md ($0.001) | 5 md ($0.005) |
| Office/HWP 페이지 | 1 md ($0.001) | 5 md ($0.005) |
| 이미지 | 1 md ($0.001) | 5 md ($0.005) |
| 오디오 (초당) | — | 1 md ($0.001) |
| 비디오 (초당) | — | 5 md ($0.005) |
| 마크다운 (`.md`) | 무료 (0 md) | 무료 (0 md) |
| Docling 정제 (페이지당) | — | 3 md ($0.003) |

:::info
**Basic 모델**: 하루 100페이지 무료. 무료 할당량 초과 후 1 md/페이지가 청구됩니다.
**Premium 모델**: 무료 할당량 없음. 모든 페이지에 5 md/페이지가 청구됩니다.
:::

마크다운 파일은 비용 없이 처리됩니다 — 텍스트 콘텐츠가 결과로 그대로 사용됩니다.

현재 요율은 `GET /api/v1/account/pricing`에서 확인할 수 있습니다.

## 지원 입력 형식

- **PDF**: PDF
- **Office**: DOCX, DOC, PPTX, PPT, XLSX, XLS (Docling 전처리 파이프라인을 경유)
- **HWP**: HWP, HWPX (한글 워드프로세서, pyhwp로 변환)
- **이미지**: PNG, JPG, JPEG, GIF, BMP, WEBP, TIFF
- **오디오**: MP3, WAV, FLAC, AAC, OGG, M4A, WMA
- **비디오**: MP4, AVI, MOV, MKV, WEBM, FLV, WMV, M4V
- **마크다운**: MD (텍스트 콘텐츠가 결과로 직접 사용되며 OCR/LLM 처리 없음)
- **압축 파일**: ZIP, RAR, 7Z, TAR, GZ, TGZ, BZ2

PDF, Office, HWP/HWPX 파일은 Docling 전처리 파이프라인을 통해 처리됩니다. Office/HWP 페이지 수는 Docling/pyhwp로 추정되며 (추정 실패 시 기본 1페이지).

## 핵심 흐름

1. **파일 업로드** → `POST /jobs/upload`는 `job_id`와 비용 미리보기를 반환합니다.
2. **작업 확인** → `POST /jobs/{job_id}/confirm`은 크레딧을 차감하고 처리를 큐에 넣습니다.
3. **상태 폴링** → `GET /jobs/{job_id}`에서 `status`가 `done` 또는 `error`가 될 때까지 확인합니다.
4. **결과 다운로드** → `GET /jobs/{job_id}/download?type=csv_basic|md|xlsx_basic`는 서명된 URL을 반환합니다.

## 엔드포인트

### 계정

#### `GET /account`

계정 정보, 크레딧 잔액, 오늘 사용량, 현재 API 키 메타데이터를 반환합니다.

**응답:**
```json
{
  "user_id": "uuid",
  "email": "user@example.com",
  "points_balance": 10000,
  "api_key": { "id": "...", "name": "...", "scopes": ["jobs:read", "jobs:write"] },
  "today_usage": { "points_spent": 150, "requests": 12 }
}
```

#### `GET /account/pricing`

현재 크레딧 요율(milli-USD)과 충전 한도를 반환합니다.

#### `GET /account/transactions`

크레딧 충전/사용 내역을 반환합니다.

#### `GET /account/usage?days=30`

일별 집계 사용량을 반환합니다.

#### `GET /account/payments`

결제 내역을 반환합니다.

#### `GET /account/subscription`

현재 구독 상태, 플랜, 월간 한도, 사용량을 반환합니다.

**응답:**
```json
{
  "plan": "pro",
  "status": "active",
  "monthly_limit": 100000,
  "used": 5000
}
```

### API 키

#### `POST /keys`

새 API 키를 생성합니다.

**요청:**
```json
{ "name": "production", "scopes": ["jobs:read", "jobs:write"] }
```

**응답:**
```json
{
  "id": "key-id",
  "name": "production",
  "prefix": "chu_live",
  "key": "chu_live_...",
  "scopes": ["jobs:read", "jobs:write"],
  "rate_limit_rpm": 60
}
```

전체 `key`는 한 번만 반환됩니다.

#### `GET /keys`

API 키 목록을 조회합니다(전체 키 값은 제외).

#### `DELETE /keys/{id}`

API 키를 비활성화합니다.

#### `POST /keys/{id}/rotate`

API 키를 로테이션합니다 (새 키 값을 생성하고 기존 키를 무효화합니다).

#### `GET /keys/{id}/usage`

특정 API 키의 사용 통계를 반환합니다.

### 작업

#### `POST /jobs/upload`

파일을 업로드하고 비용 미리보기를 받습니다. 이 단계에서 크레딧은 차감되지 **않습니다**.

**폼 필드:**
- `files`: 하나 이상의 파일 (multipart/form-data)
- `pipeline`: `"vision"` (기본값) 또는 `"hybrid"`
- `columns`: 콤마로 구분된 컬럼 이름 또는 JSON 배열 (선택)
- `prompt`: 모델에 대한 추가 지시 (선택)
- `dpi`: PDF 렌더링 DPI, 기본값 **300**
- `ocr_model`: `"basic"` 또는 `"premium"` (기본값 `"premium"`)
- `ocr_engine`: `"tesseract"`, `"easyocr"` (기본값), 또는 `"rapidocr"` (premium 전용)
- `relative_paths`: 압축 파일 내 상대 경로 JSON 배열 (선택)
- `docling_refinement`: `true` 또는 `false` (기본값). PDF/Office/HWP 문서에 대해 LLM 레이아웃 정제를 활성화합니다 (3 md/페이지).

**응답:**
```json
{
  "job_id": "job-id",
  "status": "pending",
  "file_type": "pdf",
  "total_pages": 10,
  "total_files": 1,
  "media_duration_seconds": 0,
  "docling_refinement": false,
  "docling_refinement_pages": 0,
  "ocr_model": "premium",
  "ocr_engine": "easyocr",
  "has_media": false,
  "cost": { "pages": 10, "points": 50, "usd": "$0.05" },
  "balance": 10000
}
```

#### `POST /jobs/{job_id}/confirm`

작업을 확인하고, 크레딧을 차감하며, 처리를 시작합니다.

**응답:**
```json
{
  "job_id": "job-id",
  "status": "queued",
  "remaining_points": 9950
}
```

#### `GET /jobs/{job_id}`

작업 상태와 메타데이터를 조회합니다.

**응답:**
```json
{
  "job_id": "job-id",
  "status": "done",
  "pipeline": "vision",
  "file_type": "pdf",
  "filename": "document.pdf",
  "total_pages": 10,
  "done_pages": 10,
  "total_files": 1,
  "done_files": 1,
  "media_duration_seconds": 0,
  "ocr_model": "premium",
  "ocr_engine": "easyocr",
  "cost_points": 50,
  "error_log": null,
  "downloadable": true,
  "xlsx_converted": false,
  "xlsx_basic_converted": false,
  "xlsx_advanced_converted": false,
  "xlsx_advanced_status": null,
  "xlsx_advanced_job_id": null,
  "xlsx_advanced_refundable": false,
  "xlsx_advanced_recovery_notes": null,
  "refundable": false,
  "retry_count": 0,
  "created_at": "2026-07-23T00:00:00",
  "finished_at": "2026-07-23T00:01:00"
}
```

#### `GET /jobs`

작업 목록을 조회합니다. `limit` 쿼리 매개변수를 지원합니다 (기본값 100).

#### `PATCH /jobs/{job_id}/title`

작업의 표시 제목을 변경합니다. 모든 상태에서 사용 가능합니다.

**요청:**
```json
{ "title": "새 제목" }
```

**응답:** `GET /jobs/{job_id}`와 동일한 형태. `filename` 필드에 새 제목이 반영됩니다.

**오류:**

| 상태 | 의미 |
|--------|---------|
| 400 | 제목이 비어 있거나 200자를 초과함 |
| 404 | 작업을 찾을 수 없거나 소유자가 아님 |

#### `GET /jobs/{job_id}/download?type=xlsx_basic`

결과 파일에 대한 서명된 Supabase Storage URL을 반환합니다.

**지원 타입:** `csv_basic`, `md`, `xlsx_basic`, `xlsx_advanced`, `docx`, `pptx`.

**응답:**
```json
{ "download_url": "https://..." }
```

:::info
서명된 URL은 **1시간** 동안 유효합니다. `xlsx_basic`/`csv_basic`의 경우 첫 다운로드 시 자동 변환됩니다 (1 md/단위, 최초 1회만).
:::

#### `POST /jobs/{job_id}/convert`

완료된 작업의 마크다운 결과를 Office 형식으로 변환합니다.

**요청:**
```json
{ "format": "xlsx_basic" }
```

**지원 형식:** `xlsx_basic`, `csv_basic`, `xlsx_advanced`, `docx`, `pptx`.

| 형식 | 비용 |
|--------|------|
| `xlsx_basic` / `csv_basic` | 1 md/단위, 최초 1회만 |
| `xlsx_advanced` | 3 md/단위, 최초 1회만 |
| `docx` / `pptx` | 무료 |

#### `POST /jobs/{job_id}/action`

실패한 문서 파싱 작업을 재시도하거나 환불합니다. `status`가 `error`이고 `refundable`이 `true`일 때만 사용 가능합니다.

**요청:**
```json
{ "action": "retry" }
```

**액션:** `retry` (추가 비용 없이 재실행) 또는 `refund` (모든 크레딧 환불).

#### `POST /jobs/{job_id}/xlsx-advanced-action`

실패한 XLSX 고급 변환을 재시도하거나 환불합니다. `xlsx_advanced_status`가 `error`이고 `xlsx_advanced_refundable`이 `true`일 때만 사용 가능합니다.

**요청:**
```json
{ "action": "retry" }
```

## 오류 코드

| 상태 | 의미 |
|--------|---------|
| 400 | 잘못된 요청 (유효하지 않은 파일 유형, 누락된 필드) |
| 401 | 유효하지 않거나 누락된 API 키 |
| 402 | 크레딧 부족 |
| 403 | 금지 (누락된 scope) |
| 413 | 파일이 너무 크거나 페이지가 너무 많음 |
| 429 | 속도 제한 초과 |
| 502 | 하위 처리 오류 |

## 웹훅 (예정)

작업 완료 이벤트를 수신할 콜백 URL을 등록합니다.

```bash
curl -X POST /api/v1/webhooks \
  -H "X-API-Key: <key>" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://your-app.com/webhooks/proof","events":["job.done","job.error"]}'
```

## OpenAPI / Swagger

대화형 문서는 다음에서 확인할 수 있습니다.

```
/api/v1/docs
```
