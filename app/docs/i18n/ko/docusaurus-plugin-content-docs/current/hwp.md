# HWP/HWPX 지원 (Phase 2)

## 개요

Chungu는 a1 백엔드에서 pyhwp 기반 전용 컨버터를 통해 한글 문서(`.hwp`)와 XML 기반 변형(`.hwpx`)을 지원합니다. 이는 Docling 전처리 파이프라인 Phase 2의 일부입니다.

- **마크다운 추출**: `pyhwp2md`가 텍스트, 단락, 제목, 목록, 표를 마크다운으로 변환합니다.
- **이미지 추출**: `pyhwp`가 `BinData` OLE 스토리지를 읽어 내장 이미지를 추출합니다.
- **페이지 수 추정**: `hwp_converter.get_page_count()`가 문서 요약 정보를 읽어 페이지 수를 추정합니다.

## 파이프라인 흐름

1. **업로드**: `jobs.py`가 `media_loader.HWP_TYPES`를 통해 `.hwp` / `.hwpx` 파일을 감지합니다.
2. **페이지 수**: 업로드된 파일에 대해 `hwp_converter.get_page_count()`를 호출합니다.
3. **워커 라우팅**: `tasks.py`가 단일 파일이나 압축 파일 내부 파일에 대해 `run_hwp()`를 호출합니다.
4. **처리**: `pipeline_docling.py`의 `run_hwp()`가:
   - `pyhwp2md`로 마크다운을 추출합니다.
   - `pyhwp`로 `BinData` 이미지를 추출합니다.
   - 동일한 Docling 설정을 사용해 선택적으로 LLM 레이아웃 정제를 수행합니다.
5. **결과**: 추출된 마크다운은 다른 Docling 지원 문서와 마찬가지로 CSV/MD/XLSX 출력에 병합됩니다.

## 파일 라우팅

- `media_loader.HWP_TYPES = {"hwp"}`
- 단일 파일: `tasks.py`의 `job.file_type in media_loader.HWP_TYPES` 분기.
- 다중 파일: 압축 해제 루프 내부의 `ftype in media_loader.HWP_TYPES` 분기.
- 추출된 파일은 PDF/Office 문서와 동일한 경로 로직으로 Supabase Storage에 업로드됩니다.

## 정제(Refinement)

- `use_docling_refinement` / `docling_refinement` 플래그가 HWP/HWPX 결과에도 동일하게 적용됩니다.
- 비용은 `settings_store`의 `cost_per_docling_refinement_page_krw` / `cost_per_docling_refinement_page_usd`로 설정합니다.

## API 및 프론트엔드

- `POST /api/jobs/upload`가 `docling_refinement` 폼 필드를 받습니다.
- `UploadPage.jsx`는 Docling 호환 문서(HWP/HWPX 포함)에 대해 "Docling 레이아웃 정제 사용" 체크박스를 표시합니다.
- 지원 파일 확장자에는 `.hwp`와 `.hwpx`가 포함됩니다.

## 주요 파일

- `app/backend/core/hwp_converter.py` — HWP/HWPX 텍스트, 이미지, 페이지 추출.
- `app/backend/core/pipeline_docling.py` — Docling과 동일한 정제 경로를 재사용하는 `run_hwp()` 함수.
- `app/backend/workers/tasks.py` — HWP/HWPX 파일을 `run_hwp()`로 라우팅.
- `app/backend/api/jobs.py` — HWP/HWPX 업로드의 페이지 수 계산 및 비용 계산.
- `app/backend/core/media_loader.py` — `HWP_TYPES` 및 파일 유형 감지.
