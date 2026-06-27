---
sidebar_position: 3
---

# 출력 형식

Chungu는 여러 형식으로 결과를 제공할 수 있습니다. 기본 출력은 항상 Markdown이며, 필요에 따라 다른 형식으로 변환됩니다.

## 사용 가능한 형식

| 형식 | 엔드포인트 매개변수 | 비고 |
|--------|-------------------|-------|
| Markdown | `type=md` | 기본 출력, 원본 구조화된 표 |
| CSV | `type=csv` | 쉼표로 구분된 값 |
| XLSX | `type=xlsx` | Excel 스프레드시트 (첫 변환 시 추가 포인트 소요) |
| DOCX | `type=docx` | Word 문서 (`/convert` 엔드포인트 사용) |
| PPTX | `type=pptx` | PowerPoint (`/convert` 엔드포인트 사용) |

## 다운로드 vs 변환

- **다운로드** (`GET /jobs/{id}/download?type=`) — 이미 생성된 결과의 서명된 URL 반환
- **변환** (`POST /jobs/{id}/convert`) — Markdown 결과에서 새 형식 생성

### 각각을 언제 사용하나요?

- `md`와 `csv`에는 **다운로드** 사용 (작업 완료 후 항상 사용 가능)
- `xlsx`에는 **다운로드** 사용 (첫 요청 시 자동 변환, 이후 캐시됨)
- `docx`와 `pptx`에는 **변환** 사용 (다운로드 엔드포인트에서 사용 불가)

## 예: XLSX 다운로드

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  "https://your-domain.com/api/v1/jobs/job-abc123/download?type=xlsx"
```

## 예: DOCX로 변환

```bash
curl -X POST https://your-domain.com/api/v1/jobs/job-abc123/convert \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{"format": "docx"}'
```

## 서명된 URL 만료

다운로드 URL은 **1시간** 동안 유효합니다. 만료된 경우 새 URL을 요청하세요.
