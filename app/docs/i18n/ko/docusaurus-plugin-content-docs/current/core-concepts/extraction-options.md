---
sidebar_position: 5
---

# 추출 옵션

Chungu가 파일에서 표를 추출하는 방법을 사용자 정의하세요.

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
