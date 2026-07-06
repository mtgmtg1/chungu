# Searchable PDF 텍스트 레이어 통합 계획

## 목표

업로드 시점에 OCR 결과로부터 searchable PDF(텍스트 레이어가 포함된 PDF)를 생성하고, 이를 원본 파일의 미리보기로 사용한다. 이를 통해:

- PDF/이미지 뷰어에서 텍스트 검색/선택 가능
- AI 주석 생성 시 OCR bbox 변환 대신 텍스트 레이어에서 직접 bbox 검색 → 좌표 어긋남 해결
- AI 주석 PDF 또한 텍스트 레이어 기반으로 더 정확하게 생성

## 선택 요약

- **Searchable PDF 노출 방식**: 원본 파일의 `preview_url`을 searchable PDF로 대체. 다운로드용 `url`은 원본 유지.
- **적용 범위**: PaddleOCR 기반 PDF 경로 + 이미지 파일 업로드 먼저. Docling/HWP 경로는 추후 확장.
- **메타데이터 저장**: 단일 파일 업로드는 `Job` 테이블 컬럼(`searchable_pdf_storage_path`) 사용. 멀티파일 업로드는 `extracted_files` JSONB에 `searchable_pdf_storage_path` 필드를 추가하는 하이브리드 방식.

## Phase 1: DB 마이그레이션 + 모델 수정

- [x] `Job` SQLAlchemy 모델에 `searchable_pdf_storage_path` 컬럼 추가 (`app/backend/db/models.py`)
- [x] 마이그레이션 SQL 스크립트 생성 (`scripts/migrations/add_job_searchable_pdf_storage_path.sql`)
- [ ] Alembic 마이그레이션 스크립트 생성 및 실행 (프로젝트에 Alembic 설정 시)
- [ ] `Job` 스키마/직렬화에 새 필드 반영 (필요한 경우)

## Phase 2: PaddleOCR PDF 경로 (`run_vision`) 개선

- [x] `app/backend/core/pipeline_vision.py`의 `run_vision()`이 `layout_by_page`도 반환하도록 수정
  - `paddleocr_client.convert_image()` → `convert_image_with_layout()` 사용
  - 페이지별 `overall_ocr_res`에서 `rec_texts`/`rec_boxes` 추출
  - 반환 타입: `(list[tuple[int, str]], dict[int, dict])`

## Phase 3: tasks.py에서 searchable PDF 생성 및 업로드 (단일 PDF)

- [x] `app/backend/workers/tasks.py`에서 `run_vision()` 결과에서 `layout_by_page`를 받아 searchable PDF 생성
  - 원본 PDF 바이트를 `job.pdf_storage_path` 또는 `input_path`에서 로드
  - `pdf_text_layer.add_text_layer_from_ocr()` 호출
  - `supabase_client.upload_input()`으로 업로드
  - `job.searchable_pdf_storage_path`에 저장
- [x] 원본 PDF에 이미 텍스트 레이어가 있어도 PaddleOCR 기반 레이어로 새로 생성 (더 정확한 한글 지원)

## Phase 4: `source_files` 미리보기 대체

- [x] `app/backend/api/jobs.py`의 `_source_files()` 수정
  - 원본 PDF 항목의 `preview_url`을 `job.searchable_pdf_storage_path`로 설정
  - `url`은 원본 clean PDF로 유지 (다운로드용)
  - searchable PDF가 없을 경우 기존 원본 `preview_url` fallback
- [x] `_build_source_file_item()`에서 이미지 항목의 `preview_url`을 `extracted_files[i].searchable_pdf_storage_path`로 대체

## Phase 5: AI 주석 생성 최적화

- [x] `app/backend/core/pdf_annotate_converter.py`에서 `job.searchable_pdf_storage_path`가 있으면 이를 다운로드
- [x] `_get_page_image_paths()` 대신 searchable PDF에서 이미지 렌더링
- [x] `_collect_page_elements_from_searchable_pdf()`로 OCR 생략, 텍스트 레이어에서 직접 `elements` 추출
- [x] `TextLayerSearcher`로 searchable PDF 텍스트 레이어에서 bbox 검색

## Phase 6: 이미지 파일 업로드 처리

- [x] `app/backend/workers/tasks.py`에 `_image_to_searchable_pdf()` 헬퍼 추가
- [x] 멀티미디어 처리 시 이미지 파일마다 `paddleocr_client.convert_image_with_layout()`로 layout 확보 후 searchable PDF 생성
- [x] `extracted_files`의 이미지 항목에 `searchable_pdf_storage_path` 추가
- [x] `_build_source_file_item()`에서 이미지 항목의 `preview_url`을 searchable PDF로 대체

## Phase 7: 테스트 및 검증

- [x] 문법 검사 (`python -m py_compile`) 통과
- [x] import 테스트 통과
- [x] `_image_to_searchable_pdf()` 단위 테스트: 이미지 → searchable PDF → 텍스트 검색 성공
- [x] `_collect_page_elements_from_searchable_pdf()` 단위 테스트: searchable PDF에서 elements/corrected_images 추출 성공
- [ ] 단일 PDF 업로드 end-to-end: searchable PDF 생성 및 `preview_url` 적용 확인 (PaddleOCR 서비스 필요)
- [ ] 단일 이미지 업로드 end-to-end: searchable PDF 생성 및 `preview_url` 적용 확인 (PaddleOCR 서비스 필요)
- [ ] AI 주석 생성 end-to-end: searchable PDF 기반으로 bbox 정확히 맞는지 확인
- [ ] 멀티파일 업로드 end-to-end: 각 파일별 searchable PDF 생성 및 탭 표시 확인
- [ ] 기존 job 하위 호환: searchable PDF가 없을 때 원본 파일 그대로 표시
- [ ] Frontend: `preview_url`이 searchable PDF로 전달되면 embedpdf에서 텍스트 선택 가능

## 변경 파일 목록

| 파일 | 변경 내용 |
|------|-----------|
| `app/backend/db/models.py` | `Job` 모델에 `searchable_pdf_storage_path` 추가 |
| `scripts/migrations/add_job_searchable_pdf_storage_path.sql` | 컬럼 추가 SQL |
| `app/backend/core/pipeline_vision.py` | `run_vision`이 `layout_by_page` 반환 |
| `app/backend/workers/tasks.py` | PDF/이미지 처리 후 searchable PDF 생성 및 업로드, `fitz` import 추가 |
| `app/backend/api/jobs.py` | `_source_files`와 `_build_source_file_item`에서 `preview_url` 대체 |
| `app/backend/core/pdf_annotate_converter.py` | searchable PDF 있을 때 OCR 생략, 텍스트 레이어에서 elements 추출 |
| `app/backend/core/pdf_text_layer.py` | `extract_page_ocr_results_from_layout` 이미 존재, searchable PDF 생성용 헬퍼 재사용 |

## 참고

- 현재 AI 주석 파이프라인에는 이미 `pdf_text_layer.py`와 `TextLayerSearcher`가 적용되어 있다.
- 이 계획은 그 개념을 업로드 시점으로 확장하여 원본 파일 뷰어 전체에 searchable PDF를 적용하는 것이다.
- Phase 2와 Phase 4를 먼저 구현하면 end-to-end 동작하는 최소 기능을 빠르게 확인할 수 있다.
- PaddleOCR 서비스가 없는 로컬 환경에서는 end-to-end 테스트가 불가능하므로, 단위 테스트와 import/문법 검사로 검증했다.
