# Chungu API v1 문서

Chungu API v1은 외부 개발자가 PDF/이미지/오디오/비디오를 업로드하고 선불 포인트 시스템을 사용해 구조화된 표(CSV/MD/XLSX)를 추출할 수 있게 합니다.

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
- 일일 포인트 할당: 키별로 선택 사항.

초과 시 API는 `Retry-After` 헤더와 함께 `429 Too Many Requests`를 반환합니다.

## 가격

입력 유형에 따라 포인트가 차감됩니다.

| 입력 | 비용 |
|-------|------|
| PDF 페이지 | 3P |
| 이미지 | 3P |
| 오디오 1초 | 1P |
| 비디오 1초 | 3P |
| Docling 정제 페이지 | 3P |

Docling 정제는 Docling 전처리 문서(PDF, Office, HTML, HWP)에 대해 선택적 LLM 후처리를 적용하여 레이아웃 정확도를 높입니다.

현재 가격과 패키지는 `GET /api/v1/account/pricing`에서 확인할 수 있습니다.

## 지원 입력 형식

- **문서**: PDF, DOCX, DOC, PPTX, PPT, XLSX, XLS, HTML, HWP, HWPX
- **이미지**: PNG, JPG, JPEG, GIF, WEBP, BMP, TIFF
- **오디오**: MP3, WAV, FLAC, AAC, OGG, M4A, WMA
- **비디오**: MP4, AVI, MOV, MKV, WEBM, FLV, WMV, M4V
- **압축 파일**: ZIP, RAR, 7Z, TAR, GZ, TGZ, BZ2

PDF, Office, HTML, HWP/HWPX 파일은 Docling 전처리 파이프라인을 통해 처리됩니다.

## 핵심 흐름

1. **파일 업로드** → `POST /jobs/upload`는 `job_id`와 비용 미리보기를 반환합니다.
2. **작업 확인** → `POST /jobs/{job_id}/confirm`은 포인트를 차감하고 처리를 큐에 넣습니다.
3. **상태 폴링** → `GET /jobs/{job_id}`에서 `status`가 `done` 또는 `error`가 될 때까지 확인합니다.
4. **결과 다운로드** → `GET /jobs/{job_id}/download?type=csv|md|xlsx`는 서명된 URL을 반환합니다.

## 엔드포인트

### 계정

#### `GET /account`

계정 정보, 포인트 잔액, 오늘 사용량, 현재 API 키 메타데이터를 반환합니다.

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

포인트 패키지와 단위당 요율을 반환합니다.

#### `GET /account/transactions`

포인트 충전/사용 내역을 반환합니다.

#### `GET /account/usage?days=30`

일별 집계 사용량을 반환합니다.

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

### 작업

#### `POST /jobs/upload`

파일을 업로드하고 비용 미리보기를 받습니다.

**폼 필드:**
- `files`: 하나 이상의 파일 (multipart/form-data)
- `pipeline`: `"vision"` (기본값) 또는 `"hybrid"`
- `columns`: 콤마로 구분된 컬럼 이름 또는 JSON 배열 (선택)
- `prompt`: 모델에 대한 추가 지시 (선택)
- `dpi`: PDF 렌더링 DPI, 기본값 150
- `docling_refinement`: `true` 또는 `false` (기본값). Docling 호환 문서에 대해 LLM 레이아웃 정제를 활성화합니다.

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
  "cost": { "pages": 10, "points": 30, "krw": 30, "usd": "0.02" },
  "balance": 9970
}
```

#### `POST /jobs/{job_id}/confirm`

작업을 확인하고, 포인트를 차감하며, 처리를 시작합니다.

**응답:**
```json
{
  "job_id": "job-id",
  "status": "queued",
  "remaining_points": 9940
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
  "cost_points": 30,
  "downloadable": true,
  "created_at": "2026-06-26T00:00:00",
  "finished_at": "2026-06-26T00:01:00"
}
```

#### `GET /jobs`

작업 목록을 조회합니다. `limit` 쿼리 매개변수를 지원합니다.

#### `GET /jobs/{job_id}/download?type=xlsx`

결과 파일에 대한 서명된 Supabase Storage URL을 반환합니다.

**지원 타입:** `csv`, `md`, `xlsx`.

**응답:**
```json
{ "download_url": "https://..." }
```

## 오류 코드

| 상태 | 의미 |
|--------|---------|
| 400 | 잘못된 요청 (유효하지 않은 파일 유형, 누락된 필드) |
| 401 | 유효하지 않거나 누락된 API 키 |
| 402 | 포인트 부족 |
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
  -d '{"url":"https://your-app.com/webhooks/chungu","events":["job.done","job.error"]}'
```

## OpenAPI / Swagger

대화형 문서는 다음에서 확인할 수 있습니다.

```
/api/v1/docs
```
