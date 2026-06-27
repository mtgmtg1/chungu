---
sidebar_position: 1
---

# 소개

Chungu는 PDF 및 미디어 파일을 구조화된 표로 변환하는 서비스입니다. PDF, 이미지, 오디오, 비디오를 업로드하면 CSV, Markdown, XLSX 형식의 구조화된 표를 반환합니다.

## Chungu API로 무엇을 할 수 있나요?

- PDF 문서, 스캔 이미지, 스크린샷에서 **표 추출**
- 오디오 녹음 및 비디오 파일을 **전사 및 구조화**
- 결과를 CSV, Markdown, XLSX, DOCX, PPTX로 **변환**
- AI 기반 파이프라인으로 문서 처리 **자동화**

## 작동 방식

```mermaid
flowchart LR
    A[파일 업로드] --> B[비용 미리보기]
    B --> C[작업 확인]
    C --> D[처리 중]
    D --> E[상태 폴링]
    E --> F[결과 다운로드]
```

1. **업로드** — `POST /api/v1/jobs/upload`로 파일을 업로드하고 비용 미리보기를 받습니다 (포인트 차감 없음)
2. **확인** — `POST /api/v1/jobs/{job_id}/confirm`로 작업을 확인합니다. 포인트가 차감되고 처리가 시작됩니다
3. **폴링** — `GET /api/v1/jobs/{job_id}`로 `status`가 `done` 또는 `error`가 될 때까지 확인합니다
4. **다운로드** — `GET /api/v1/jobs/{job_id}/download?type=csv|md|xlsx`로 결과를 다운로드합니다

## 시작하기

- Chungu가 처음이신가요? [퀵 스타트](./quickstart) 가이드를 읽어보세요
- API 키가 필요하신가요? [개발자 포털](../../developer)을 방문하세요
- AI가 자동으로 API를 호출하게 하고 싶으신가요? [AI 프롬프트](./ai-prompts/full-pipeline-prompt)를 확인하세요
