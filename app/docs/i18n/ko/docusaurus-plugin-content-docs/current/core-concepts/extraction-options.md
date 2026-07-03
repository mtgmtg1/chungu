---
sidebar_position: 5
---

# 추출 옵션

PROOF가 파일에서 표를 추출하는 방법을 사용자 정의하세요.

## 모델 선택

기본 모델과 고급 모델 중 선택하세요:

| 모델 | 플래그 | 기본값 | 비고 |
|-------|------|---------|-------|
| 기본 | `ocr_model=basic` | — | $0.001/페이지, 하루 100페이지 무료, 오디오/비디오 미지원 |
| 고급 | `ocr_model=premium` | ✓ | $0.005/페이지, 모든 파일 유형 지원 |

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "ocr_model=basic"
```

## OCR 엔진

고급 모델의 경우 텍스트 추출에 사용할 OCR 엔진을 선택하세요:

| 엔진 | 플래그 | 기본값 | 비고 |
|--------|------|---------|-------|
| EasyOCR | `ocr_engine=easyocr` | ✓ | 속도와 정확도의 균형 |
| Tesseract | `ocr_engine=tesseract` | — | 빠르고 광범위하게 지원됨 |
| RapidOCR | `ocr_engine=rapidocr` | — | CJK 텍스트에 최적화 |

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "ocr_model=premium" \
  -F "ocr_engine=rapidocr"
```

## 컬럼

모델의 추출을 안내하기 위해 컬럼 이름을 지정합니다. 생략하면 기본 컬럼이 사용됩니다.

### 쉼표로 구분

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "columns=날짜,계정과목,적요,입금액,출금액,잔액"
```

### JSON 배열

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F 'columns=["date","account","description","debit","credit","balance"]'
```

## 프롬프트

모델의 추출 동작을 사용자 정의하는 추가 지시사항을 입력합니다.

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "prompt=금액이 1,000,000원 이상인 행만 추출하세요"
```

일반적인 프롬프트 예시:

- `"여러 줄 셀을 단일 셀로 병합"`
- `"헤더 행을 무시하고 데이터 행만 추출"`
- `"YYYY-MM-DD 날짜 형식 사용"`
- `"행 번호 컬럼 포함"`

## DPI

PDF 페이지의 렌더링 해상도를 제어합니다. DPI가 높을수록 작은 텍스트의 정확도가 향상되지만 처리 시간이 증가합니다.

| DPI | 사용 사례 |
|-----|----------|
| 150 | 기본값, 대부분의 문서에 적합 |
| 300 | 고해상도, 작은 글꼴 |
| 600 | 매우 작은 글씨, 영수증 |

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "dpi=300"
```

## 상대 경로 (압축 파일)

압축 파일을 업로드할 때 디렉토리 구조를 유지하기 위해 상대 경로를 지정할 수 있습니다:

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@archive.zip" \
  -F 'relative_paths=["folder/doc1.pdf","folder/doc2.pdf"]'
```
