# AGENTS.md — PROOF Project Guide

## Project Overview

PROOF is a PDF/media → structured table (CSV/MD/XLSX) conversion service. It exposes core functionality both as a web application and as a monetized API (`/api/v1/*`) for external developers.

## Recent Changes

최근 주요 변경사항입니다. 상세한 코드 이력은 `git log`를 참조하세요.

### Supabase Storage PDF 업로드 Content-Type 명시 및 뷰어 바로 다운로드 증상 해결 — 2026-07-22

- **원인 분석**:
  - `app/backend/core/supabase_client.py`의 `upload_input` 함수가 PDF 파일을 Supabase Storage(`pdfs` 버킷)에 업로드할 때 Content-Type을 `"application/octet-stream"`으로 하드코딩하고 있었음.
  - 이로 인해 프론트엔드 PDF 뷰어(`PdfViewer.jsx`)가 서명된 Signed URL을 통해 PDF를 불러올 때, 응답 헤더가 `Content-Type: application/octet-stream`으로 내려와 브라우저가 PDF 문서로 파싱하지 못하고 바로 파일을 다운로드받거나 뷰어 파싱 에러(`"데이터를 불러오지 못했습니다"`)를 일으키던 증상이 유발됨.
- **수정 내용**:
  - `app/backend/core/supabase_client.py`: `_get_content_type` 함수를 확장하여 `.pdf`일 때 `"application/pdf"`, `.json`일 때 `"application/json"` 등 동적 Content-Type을 반환하도록 수정하고 `upload_input`에서 이를 적용함.
- **검증**: `cd app/backend && venv/bin/python -m pytest tests/ -q` → 241 passed.

### AI 주석 y좌표 근본 원인 해결 (PyMuPDF search_for Top-Left 좌표 정규화) — 2026-07-22

- **근본 원인 발견**:
  - PyMuPDF의 `fitz.Page.search_for(text)`가 반환하는 `Rect(x0, y0, x1, y1)`는 표준 PDF User-Space(원점 좌하단, y=0 하단)가 아니라 **이미 Top-Left(Device-Space, y=0 상단)** 좌표계였음.
  - 백엔드의 `pdf_annotate_converter.py` 및 AI 백엔드 도구가 이 `search_for` 결과를 "PDF User-Space"라고 착각하여 `_rect_to_embedpdf_rect` 또는 `save_user_annotations(input_space="pdf_user")`를 거쳐 `y_device = page_height - y` (y-flip)를 한 번 더 적용했음.
  - 그로 인해 상단(예: y=100) 텍스트에 칠해져야 할 주석이 하단(y=742) 거울 반전 위치로 튕겨서 찍히던 증상의 100% 근본 원인이었음.
- **수정 내용**:
  - `app/backend/core/pdf_annotate_converter.py`: `_collect_targets_for_search_phrase` 및 `_collect_targets_with_vision_llm`에서 PyMuPDF `search_for()` 결과를 `AnnotationTarget`에 담을 때 `(x0, page_height - y1, x1, page_height - y0)`로 PDF User-Space 좌표계로 정확하게 정규화하여 `build_embedpdf_annotations`에 전달.
  - `app/ai-backend/src/tools/annotations.ts`: `apply_annotations` 도구가 백엔드로 `saveAnnotations` 호출 시 `input_space='device'`로 전달하도록 정돈.
- **검증**: PyMuPDF `search_for` 반환 좌표 수식적 검증 완료, `cd app/backend && venv/bin/python -m pytest tests/ -q` → 241 passed, `cd app/ai-backend && npm run build` → 성공.

### AI 주석 y좌표 반전 원인 해결 및 뷰어 device-space 좌표계 보장 — 2026-07-22

- **원인 분석**:
  - `get_job_result_json(kind="annotations")` 및 `get_job_annotations` API가 Storage에 저장된 device-space(y=0 상단) 주석 JSON을 프론트엔드/뷰어로 반환할 때, `pdf_user_annotator._convert_annotations_to_pdf_user`를 불필요하게 실행하여 PDF user-space(y=0 하단) 좌표계로 다시 반전시켜 보내고 있던 문제가 원인이었음.
  - 프론트엔드 뷰어(`PdfViewer.jsx`)는 device-space(y=0 상단) 좌표를 기대하므로, 이 반환값(`origin.y = 800`)을 그대로 렌더링하면서 주석이 최하단(상하 거울 반전 위치)에 찍히던 증상이 발생했음.
  - `pdf_annotator.py` 및 `pdf_user_annotator.py`의 `fitz.Rect` 생성 시 `page_x0 + page_height` 오타로 인해 비정방형 페이지에서 좌표 왜곡이 유발되던 2차 버그도 함께 수정.
- **수정 내용**:
  - `app/backend/api/jobs.py`: `get_job_result_json`에서 `_convert_annotations_to_pdf_user` 호출 제거하여 뷰어용 device-space 주석을 있는 그대로 반환. `/jobs/{job_id}/annotations` API에 `space` 파라미터(기본값 `"device"`)를 추가하여 `space="pdf_user"` 일 때만 PDF user-space로 변환.
  - `app/backend/core/pdf_annotator.py` 및 `app/backend/core/pdf_user_annotator.py`: `fitz.Rect(page_x0, page_y0, page_x0 + page_height, page_y0 + page_height)` 오타를 `page_x0 + page_width`로 정정 및 `page_width` 선택적 수신 지원.
  - `app/ai-backend/src/lib/proof-api.ts`: Node.js AI 에이전트 도구가 기존 주석을 조회할 때 `space=pdf_user`를 요청하도록 업데이트.
- **검증**: `cd app/backend && venv/bin/python -m pytest tests/ -q` → 241 passed, `cd app/ai-backend && npm run build` → 성공, `cd app/frontend && npm run build` → 성공.
- **핵심 파일**: `app/backend/api/jobs.py`, `app/backend/core/pdf_annotator.py`, `app/backend/core/pdf_user_annotator.py`, `app/ai-backend/src/lib/proof-api.ts`, `app/backend/tests/test_pdf_text_layer_baseline.py`, `app/backend/tests/test_jobs_result_json_annotations.py`.

### AI 주석 y좌표 반전 재발 수정 — canonical 좌표계 도입 시점(c9e3c9c)으로 복구 — 2026-07-22

- **원인**: 2026-07-21에 canonical 좌표계를 further 발전시킨 일련의 커밋들(4086288, 414107a, 9369ace, deb1689, 78cf1bd, 588cbb9, d4364c3, 9733b5d, 625c115, e7e2bf3, 1455164, 0ba16d9, 2f994ea, 5dca4b1, f5634f2, d883dea, bdf7126, 7564820, af5deba/602676a)이 device-space ↔ pdf_user-space 직접 변환을 canonical 경유 변환으로 교체하면서 y-flip이 재발. job 46557a21a74547518da300dc6de96b75(2026-07-20 19:13 생성) 시점에는 정상 작동했으나, 이후 변경으로 AI 에이전트가 추가한 주석의 y좌표가 다시 반전되어 표시됨.
- **수정**: canonical 좌표 도입 직후 안정 시점인 `c9e3c9c`(2026-07-20 13:14)로 7개 핵심 파일을 checkout.
  - `app/backend/core/pdf_annotator.py`: `_rect_to_canonical_rect`/`_device_annotation_to_canonical` 대신 `_rect_to_embedpdf_rect`(device-space 직접 변환) 사용.
  - `app/backend/core/pdf_user_annotator.py`: `_convert_annotations_to_canonical`/`_convert_annotation_item` 등 canonical 경유 변환 함수 제거, `_convert_annotation_to_pdf_user`/`_convert_annotation_to_device_space` 직접 변환 복원.
  - `app/backend/core/pdf_annotate_converter.py`: `_build_canonical_annotations_document`/`_extract_annotations_from_document`/`_page_dimensions` 제거, flat list 저장 복원.
  - `app/backend/api/jobs.py`: `save_user_annotations`/`_merge_annotation_jsons`/`_load_all_annotations`/`get_job_annotations`/`get_job_result_json`/`update_job_annotation`/`_initialize_user_annotations_json`/`preview_job`를 c9e3c9c 버전으로 복원. canonical document 처리 제거, device-space ↔ pdf_user-space 직접 변환 사용.
  - `app/frontend/src/components/SourcePanel.jsx`: `canonicalToDeviceAnnotation`/`canonicalToDeviceRect`/`canonicalToDevicePoint`/`normalizeAnnotationsJson`(canonical 분기) 제거, flat list 그대로 렌더링 복원.
  - `app/frontend/src/components/PdfViewer.jsx`: c9e3c9c 버전으로 복원.
  - `app/ai-backend/src/tools/annotations.ts`: c9e3c9c 버전으로 복원. 배치 주석, sticky note, line highlight 도구 제거, 단일 주석 도구 복원.
- **손실 기능**: c9e3c9c 이후 추가된 기능(배치 주석 배열 입력, per-file searchable PDF, merged_annotations.json 자동 재생성, sticky note/line highlight 도구, callout→sticky note 변경, 다중 매개변수 목록 지원)은 모두 제거됨. 필요한 경우 별도 재개발 필요.
- **검증**: `cd app/backend && venv/bin/python -m pytest tests/ -q` → 240 passed. `cd app/ai-backend && npm run build` → 성공. `cd app/frontend && npm run build` → 성공.
- **핵심 파일**: `app/backend/core/pdf_annotator.py`, `app/backend/core/pdf_user_annotator.py`, `app/backend/core/pdf_annotate_converter.py`, `app/backend/api/jobs.py`, `app/frontend/src/components/SourcePanel.jsx`, `app/frontend/src/components/PdfViewer.jsx`, `app/ai-backend/src/tools/annotations.ts`.
- **주의**: 기존 job의 `merged_annotations.json`/`user_annotations_*.json`이 canonical document 형식(dict with coordinate_system/page_dimensions)으로 저장되어 있는 경우, c9e3c9c 코드는 이를 list로 간주하지 않으므로 주석이 표시되지 않을 수 있음. 해당 job은 주석을 다시 추가하거나 JSON을 flat list로 변환해야 함.

### 프로 요금제 크레딧 혜택 상향 및 충전 크레딧 일치화 — 2026-07-21

- **프로 요금제 월간 혜택 크레딧 인상**:
  - `app/backend/core/subscription_service.py` 및 `app/frontend/src/pages/PricePage.jsx`에서 프로 요금제의 제공 크레딧을 기존 20,000pt에서 30,000pt(1.5배)로 인상.
  - `app/backend/tests/test_subscription_credits.py` 테스트 코드를 30,000pt에 맞도록 수정 및 검증 완료.
- **프로 요금제 사용 가이드 추가 및 UI 단위 통일**:
  - `app/frontend/src/components/PlanCard.jsx` 카드 하단에 30,000 크레딧에 대한 대략적 예상 사용 가이드(예: 일반 분석 최대 30,000페이지, 고급 비전 분석 최대 6,000페이지)를 다국어로 노출.
  - 기존에 하드코딩 노출되던 `pt` 단위 접미사를 다국어 리소스 `t("common:points.point")`를 사용하여 `크레딧`(Ko), `credits`(En), `クレジット`(Ja)으로 일괄 대응 및 통일.
- **충전 금액 및 크레딧 비율 일치**:
  - `app/frontend/src/pages/PaymentPage.jsx`의 충전 입력창 및 예상 획득 크레딧 정보를 1달러 = 1,000크레딧(1milli-USD = 1크레딧)과 일치하게 수정하여 "20,000 크레딧 충전하기" 와 같이 표시되도록 변경.
- **핵심 파일**: `app/backend/core/subscription_service.py`, `app/backend/tests/test_subscription_credits.py`, `app/frontend/src/pages/PricePage.jsx`, `app/frontend/src/components/PlanCard.jsx`, `app/frontend/src/pages/PaymentPage.jsx`, `app/frontend/src/locales/{ko,en,ja}/page.json`.

### Develop branch fixes — 2026-07-20

- **검색 가능 PDF 텍스트 레이어 y축 반전 수정** (`app/backend/core/pdf_text_layer.py`):
  - `add_text_layer_from_ocr()`이 OCR bbox를 PDF user-space로 변환할 때 points/pixel top-left 좌표계를 지원하지 않아 발생하던 y축 반전 버그를 수정.
  - `_convert_bbox_to_pdf_user()`를 추가해 `normalized`/`points`/`pixel`/`pdf_user_space` 좌표계를 자동 감지하고, `layout`의 `width`/`height` 또는 `dpi`를 이용해 PDF user-space로 변환.
  - `app/backend/tests/test_pdf_text_layer_baseline.py`에 points top-left 회귀 테스트를 추가.
- **사용자 주석 저장 fallback 보강** (`app/backend/api/jobs.py`):
  - `save_user_annotations()`에서 `annotated_pdf_files` entry가 없어도 404를 반환하지 않고 `user_annotations_{source_index}.json` 경로로 fallback, AI/사용자 주석 병합 조건도 entry 존재 여부로 판단.
- **개발 환경 TUS 업로드/프록시 수정** (`app/frontend/src/tusUpload.js`, `app/frontend/vite.config.js`):
  - `tusUpload.js`에서 Supabase 세션 대신 `getToken()`을 사용해 개발 환경 dev bypass 토큰을 우선 사용.
  - `vite.config.js`에서 `/supabase` 프록시 대상을 `VITE_DEV_SUPABASE_URL` 환경변수 기반으로 설정, `VITE_DEV_SUPABASE_URL`이 없으면 백엔드 서버로 fallback.
- **검증**:
  - `cd app/backend && .venv/bin/python -m pytest tests/ -q` → 232 passed.
  - `cd app/frontend && npm run build` → 성공.
- **배포 시 주의**: 백엔드 Docker 컨테이너 재배포 필요. 기존 `searchable.pdf`는 반전된 채 남아 있을 수 있으므로 필요시 재생성.

### AI Annotation Agent Tool Audit — text-only workflow 및 좌표 redaction

- **목표**: AI 채팅 에이전트가 여전히 `get_elements`/`search_text`의 `bbox_pdf`나 `add_highlight`/`save_annotations` 같은 구식 tool로 rect를 조립하려는 문제를 완전히 차단. LLM은 "강조할 텍스트 내용"만 식별하고, 모든 bbox/segmentRects 결정은 백엔드가 검색해서 수행.
- **Phase 1: AI tool 출력에서 좌표 제거** (`app/ai-backend/src/tools/annotations.ts`):
  - `search_text`, `get_elements`, `compare_elements`는 `page_no`, `text`, `kind`만 반환. `bbox_pdf` 및 위치 정보를 모델에 노출하지 않음.
  - `get_annotations`, `read_job_json(kind="annotations")`는 `rect`, `segmentRects`, `calloutLine`, `bbox_pdf`를 REDACTION하여 반환. `id`, `type`, `pageIndex`, `color`, `contents`만 남김.
  - `view_page`는 텍스트 분석만 반환하며 좌표/위치가 포함되지 않음을 명시.
- **Phase 2: text-only annotation tool 교체** (`app/ai-backend/src/tools/annotations.ts`):
  - `add_highlight`/`add_callout` 제거, `add_text_highlight`/`add_text_callout` 추가.
  - 입력은 `text`, `page_no`(선택), `comment`, `color`, `opacity`(선택)뿐. 내부에서 `searchText`로 텍스트 레이어를 검색해 `bbox`를 자동 결정.
  - `add_text_highlight`는 동일 텍스트의 모든 발생 위치를 `segmentRects`로 highlight. `add_text_callout`은 첫 매치를 가리킴.
  - `save_annotations` tool 제거. `apply_annotations`가 pending을 저장.
- **Phase 3: 시스템 프롬프트 강화** (`app/ai-backend/src/chat/route.ts`):
  - tool 목록에서 `add_highlight`/`add_callout`/`save_annotations` 제거.
  - "OLD TOOLS REMOVED" 문구 추가: `add_highlight`, `add_callout`, `save_annotations`는 더 이상 존재하지 않으며, `rect/bbox`를 수동으로 계산/전달하면 안 된다고 강조.
  - `search_text`/`get_elements`/`compare_elements`/`view_page`는 좌표 없이 텍스트/분석만 제공함을 명시.
- **검증**: `cd app/ai-backend && npm run build` → tsc 성공. a1 서버 배포 완료 및 `ai-backend` 컨테이너 `Up` 확인.
- **배포 시 주의**: `ai-backend` 재배포 필요. 프론트엔드/DB 변경 없음.
- **핵심 파일**: `app/ai-backend/src/tools/annotations.ts`, `app/ai-backend/src/chat/route.ts`.


### AI Annotation Text-Only + Searchable PDF Guarantee — 모든 PDF를 PaddleOCR로 searchable 변환 및 LLM 위치값 제거

- **목표**: 텍스트 레이어가 없는 스캔 PDF를 포함한 **모든 PDF**가 PaddleOCR을 거쳐 searchable PDF가 되도록 보장하고, AI 주석 생성 시 LLM이 위치/좌표/`element_index`/bbox를 전혀 고려하지 않고 "강조할 텍스트 내용"만 반환하도록 한다. 백엔드가 `TextLayerSearcher`로 해당 텍스트를 검색해 모든 발생 위치를 `segmentRects`로 highlight.
- **Phase 1: 프롬프트 정리** (`app/backend/core/prompts.py`):
  - `build_element_highlight_prompt`, `build_row_highlight_prompt` 삭제.
  - `build_vision_bbox_highlight_prompt`를 `build_vision_text_highlight_prompt`로 변경: 이미지를 보고 `text`만 반환.
  - `build_text_search_highlight_prompt`를 범용 text-only prompt로 유지/강화.
- **Phase 2: `pdf_annotate_converter.py` 통합**:
  - `_ensure_searchable_pdf()` 추가: `job.searchable_pdf_storage_path`가 없으면 `_collect_page_elements()`로 PaddleOCR 수행 → corrected images → `add_text_layer_from_ocr()` → searchable PDF 업로드.
  - `run()`의 `advanced` 여부와 상관없이 searchable PDF를 먼저 확보하고, `advanced=True`는 Vision LLM이 `text`만 반환, `advanced=False`는 페이지 텍스트에서 `text`를 반환.
  - `_collect_targets_with_vision_llm()` 수정: Vision LLM이 `text`만 반환하면 `TextLayerSearcher.search()`로 해당 페이지에서 bbox 검색.
  - `_select_elements_with_llm`, `_matches_to_targets`, `_narrow_bbox_by_scope` 등 위치 기반 선택 로직 제거.
- **Phase 3: `pipeline_vision.py` PaddleOCR 강제**:
  - `fallback_controller` 의존 제거, LLM vision fallback 제거.
  - 10페이지 이하 PDF는 `convert_pdf_with_layout` 직접, 11페이지 이상은 렌더링 후 `convert_images_batch_with_layout` 또는 `convert_image_with_layout` per-page.
- **Phase 4: `workers/tasks.py` searchable PDF 복구 강화**:
  - `_build_and_upload_searchable_pdf()`에서 `layout_by_page`가 비어 있을 경우 `paddleocr_client.convert_pdf_with_layout()`로 직접 layout을 복구하는 방어 로직 추가.
- **Phase 5: `paddleocr_client.py` 중복 함수 정리**:
  - `convert_pdf_with_layout`이 두 번 정의되어 있던 문제 수정 (shadowing 제거). 모든 호출자가 per-page `(markdown, layout, angle_code)` tuple list를 반환하는 단일 함수를 사용하도록 정리.
- **Phase 6: 테스트 및 디버그 스크립트**:
  - `app/backend/tests/test_pdf_annotate_converter_run.py`:
    - `TestAnnotationPromptsAreTextOnly`: 모든 annotation prompt가 text 기반이고 위치값을 요구하지 않음을 검증.
    - `TestScannedPdfTextSearchPipeline`: searchable PDF가 없는 스캔 PDF에서 LLM이 `text`만 반환하면 backend가 검색해 highlight.
    - `test_run_advanced_vision_returns_text_only`: `advanced=True` Vision LLM이 `text`만 반환하면 backend가 검색.
  - `app/backend/test_annotate_compare.py`: text-only prompt와 OCR bbox 검색 방식으로 갱신.
- **Phase 7: searchable PDF 텍스트 레이어 y축 반전 버그 수정** (`app/backend/core/pdf_text_layer.py`):
  - `add_text_layer_from_ocr()`에서 OCR bbox 좌표계를 PDF user-space로 변환할 때 normalized 외 points/pixel top-left 좌표계를 지원하지 않아, 텍스트 레이어가 페이지 상하로 반전되어 삽입되던 문제 수정.
  - `_convert_bbox_to_pdf_user()` 헬퍼 추가: `_coordinate_system` 메타데이터와 `layout`의 `width`/`height`를 이용해 normalized, points, pixel, pdf_user_space 좌표계를 자동 감지/변환. `dpi` 파라미터도 `_insert_text_layer_into_doc()`에 전달.
  - `app/backend/tests/test_pdf_text_layer_baseline.py`에 points top-left 회귀 테스트 추가.
- **검증**: `cd app/backend && .venv/bin/python -m pytest tests/ -q` → 232 passed.
- **배포 시 주의**: 백엔드 Docker 재배포 필요. 이전 코드로 생성된 `searchable.pdf`는 여전히 상하 반전된 채 남아 있으므로, 새로 생성하거나 `searchable_pdf_storage_path`를 삭제 후 재생성해야 화면에서 바르게 보임. 프론트엔드/DB 변경 없음. `advanced` 모드는 여전히 Vision LLM을 호출하지만 위치값 대신 텍스트 내용만 반환. PaddleOCR 장애 시 `run_vision` 및 searchable PDF 생성이 실패할 수 있음.
- **핵심 파일**: `app/backend/core/prompts.py`, `app/backend/core/pdf_annotate_converter.py`, `app/backend/core/pdf_text_layer.py`, `app/backend/core/pipeline_vision.py`, `app/backend/core/paddleocr_client.py`, `app/backend/workers/tasks.py`, `app/backend/tests/test_pdf_annotate_converter_run.py`, `app/backend/test_annotate_compare.py`, `app/backend/tests/test_pdf_text_layer_baseline.py`.

### IRAC Argument Map — 쟁점/주장/근거 3단계 행렬 + 원문 스크롤 연동 뷰 모드

- **목표**: `JobResultPage`에 신규 "IRAC 공방 맵" 뷰 모드를 추가. Issue-Claim Tree API(`/legal-issue-tree`, `/legal-issue-tree/mappings`) 데이터를 좌우 분할 행렬(쟁점 ↔ 주장 ↔ 근거)로 시각화하고, 증거 클릭 시 `SourcePanel.scrollToPage`로 원본 PDF 해당 페이지로 스크롤 연동.
- **Phase 1: 신규 컴포넌트** (`app/frontend/src/components/irac/IracArgumentMap.jsx`):
  - `getIssueTreeMappings`로 저장된 트리 로드 → 없으면 청구 원인 입력 후 `getLegalIssueTree`로 추출.
  - 쟁점(Issue) → 주장(Claim) → 근거(Evidence) 3열 행렬 렌더링. 원고/피고 주장을 `party` 키워드로 분류.
  - 증거/주장/쟁점 클릭 시 우측 슬라이드인 상세 패널 + "원본 PDF 보기" 버튼 → `onNodeClick` 콜백으로 `SourcePanel` 해당 파일/페이지 스크롤.
  - Proven/Contested/Weak 상태 뱃지는 `mapped_evidence` 개수 기반 휴리스틱 표시.
- **Phase 2: JobResultPage 통합** (`app/frontend/src/pages/JobResultPage.jsx`):
  - `previewMode`에 `"irac"` 추가. 뷰 모드 드롭다운에 IRAC 메뉴(`Scale` 아이콘) 추가.
  - `renderRightContent`에 `irac` 분기 추가 — `onNodeClick`에서 `node.data.original_page`/`source_file`로 `sourcePanelApiRef.current.scrollToPage({ fileIndex, pageNum })` 호출.
- **Phase 3: i18n** (`app/frontend/src/locales/{ko,en,ja}/page.json`): `irac`, `iracTitle`, `iracExtract`, `iracPlaintiff`, `iracDefendant`, `iracContention`, `iracEvidence`, `iracStatusProven`, `iracStatusContested`, `iracStatusWeak`, `iracDetailTitle` 등 23개 키 추가.
- **검증**: 프론트엔드 `npm run build` 성공, `npm run test` 14 passed.
- **배포 시 주의**: 백엔드 변경 없이 기존 `/legal-issue-tree` API 재사용. DB 마이그레이션 불필요.
- **핵심 파일**: `app/frontend/src/components/irac/IracArgumentMap.jsx`, `app/frontend/src/pages/JobResultPage.jsx`, `app/frontend/src/locales/{ko,en,ja}/page.json`.

### e-Discovery Timeline 단일화 — React Chrono 3.x alternating + 상세 카드 통합

- **목표**: 기존 "상단 재분석 버튼 + 중앙 양측 주장/증거 카드 + 하단 수평 타임라인 스트립" 3단 구조를 단일 React Chrono 3.x 수직 alternating 타임라인으로 단순화. 코드 중복 제거 및 인지 과부하 감소.
- **의존성 업그레이드**: `app/frontend/package.json` — `react-chrono` 2.6.1 → `^3.3.0`.
- **Phase 1: 삭제 컴포넌트** (`app/frontend/src/components/timeline/`):
  - `CourtroomColumn.jsx`/`.test.jsx`, `EdiscoveryTimelineStrip.jsx`/`.test.jsx`, `ResizableCourtroomCards.jsx`/`.test.jsx` 제거 — 양측 카드/수평 스트립/리사이즈 래퍼 기능이 Chrono 기본 UI로 흡수.
  - `app/frontend/src/utils/ediscoveryTimelineUtils.js`(`classifyNodesBySide`), `app/frontend/src/utils/ediscoveryToTimeline.js` 제거 — 변환 로직이 `EdiscoveryTimelinePanel` 내부로 인라인.
- **Phase 2: EdiscoveryTimelinePanel 재작성** (`app/frontend/src/components/timeline/EdiscoveryTimelinePanel.jsx`):
  - `<Chrono mode="VERTICAL_ALTERNATING">`로 전체 영역 렌더링. `media` prop으로 썸네일/이미지 표시.
  - 카드/타이틀/포인트 클릭 시 상위 `onItemClick(node)` 콜백 → 미리보기 패널 + SourcePanel 연동.
  - `applyIssueDimmingToNodes`/`sortByDateOrPage` 헬퍼 제거, `getNodePage`/`findSourceFile` 헬퍼 추가.
  - 폴링 로직(재분석)은 `EDiscoveryViewer`로 이동.
- **Phase 3: 신규 컴포넌트** (`app/frontend/src/components/timeline/`):
  - `EdiscoveryDetailCard.jsx` — 선택 노드 + 미리보기 메타데이터 + 원문 텍스트를 좌우 분할 카드로 표시. 드래그 핸들로 좌우 비율 조절. `marked`로 원문 렌더링, 페이지 마커 제거.
  - `TimelinePreviewCard.jsx` — 노드 미리보기 썸네일 카드.
- **Phase 4: EDiscoveryViewer 고도화** (`app/frontend/src/components/EDiscoveryViewer.jsx`):
  - 헤더 재분석 버튼 + 컨텍스트 입력 팝업 + 폴링(`POLL_TIMEOUT_MS=600000`, `POLL_INTERVAL_MS=2000`) 추가.
  - `preview API`로 `source_files` 로드하여 자식 컴포넌트에 전달.
  - `previewNode` 상태로 상세 카드 표시, 원문 `result_markdown` 렌더링.
  - `onJobRefresh` prop 추가 — 재분석 완료 시 상위 `loadJob` 호출.
- **Phase 5: DevEdiscoveryTimelinePage 단순화** (`app/frontend/src/pages/DevEdiscoveryTimelinePage.jsx`):
  - `EdiscoveryTimelineStrip` 직접 렌더링 제거 → `EdiscoveryTimelinePanel`에 `SAMPLE_JOB` 전달.
- **Phase 6: DevEdiscoveryPage** (`app/frontend/src/pages/DevEdiscoveryPage.jsx`): `onJobRefresh={() => Promise.resolve()}` prop 추가.
- **Phase 7: index.css 정리** (`app/frontend/src/index.css`): `ediscovery-chrono` 관련 커스텀 CSS(가로 스크롤, 카드 높이 제한, React Chrono 기본 여백 오버라이드) 제거.
- **검증**: 프론트엔드 `npm run build` 성공, `npm run test` 14 passed.
- **배포 시 주의**: 프론트엔드 전용 변경. 백엔드/DB 변경 없음.
- **핵심 파일**: `app/frontend/src/components/timeline/EdiscoveryTimelinePanel.jsx`, `app/frontend/src/components/timeline/EdiscoveryDetailCard.jsx`, `app/frontend/src/components/timeline/TimelinePreviewCard.jsx`, `app/frontend/src/components/EDiscoveryViewer.jsx`, `app/frontend/src/pages/DevEdiscoveryTimelinePage.jsx`, `app/frontend/src/pages/DevEdiscoveryPage.jsx`, `app/frontend/src/index.css`, `app/frontend/package.json`.

### SimpleEditor 고도화 — 노션 스타일 토글 헤딩 + TOC 미니맵 사이드바

- **목표**: TipTap 에디터에 노션 스타일 "제목 토글로 아래 본문 숨기기/보이기" 기능과 우측 TOC(목차) 미니맵 사이드바를 추가. 긴 문서 작성 시 탐색성 개선.
- **의존성 추가** (`app/frontend/package.json`):
  - `@tiptap/extension-heading@^3.27.1` — 커스텀 헤딩 확장 베이스.
  - `@tiptap/extension-table-of-contents@^3.27.1` — TOC anchor 수집.
  - `@tiptap/extension-unique-id@^3.27.1` — 헤딩에 고유 id 부여(TOC 스크롤 대상).
- **Phase 1: CollapsibleHeading 확장** (`app/frontend/src/components/editor/CollapsibleHeading.jsx` 신규):
  - `heading` 노드에 `collapsed` boolean attribute 추가. `ReactNodeViewRenderer`로 토글 버튼 + 본문 렌더링.
  - ProseMirror plugin으로 `view.update` 후 같거나 상위 레벨의 다음 헤딩이 나올 때까지 형제 블록 DOM을 숨김.
  - doc 구조는 변경하지 않고 view 레이어에서만 숨김 → `marked`/`turndown` 마크다운 라운드트립에 영향 없음.
- **Phase 2: TocSidebar 컴포넌트** (`app/frontend/src/components/editor/TocSidebar.jsx` 신규):
  - `TableOfContents` 확장의 `onUpdate`에서 anchors 배열 수신.
  - heading depth별 들여쓰기 + 활성 heading 하이라이트. 클릭 시 해당 heading id로 `scrollIntoView`.
  - 펼침/접힘 토글 버튼.
- **Phase 3: SimpleEditor 통합** (`app/frontend/src/components/SimpleEditor.jsx`):
  - `StarterKit.configure({ heading: false })` 후 `CollapsibleHeading.configure({ levels: [1,2,3,4] })` + `UniqueID` + `TableOfContents` 확장 추가.
  - `expandAllHeadings`/`collapseAllHeadings` 헬퍼 — doc 내 모든 heading 노드 순회하며 `collapsed` 일괄 트랜잭션.
  - 툴바에 `ChevronsDownUp`/`ChevronsUpDown` 버튼 추가.
  - 레이아웃을 `flex`로 변경 — 좌측 에디터 콘텐츠 + 우측 `TocSidebar`.
- **Phase 4: index.css 스타일** (`app/frontend/src/index.css`):
  - `.collapsible-heading-wrapper`/`.collapsible-heading-toggle` — 토글 버튼 절대 위치 + 회전 애니메이션.
  - `.toc-sidebar`/`.toc-sidebar-collapsed` — 사이드바 레이아웃.
- **Phase 5: 테스트** (`app/frontend/src/components/editor/__tests__/collapsibleHeading.test.jsx`): `getHeadingLevel` 헬퍼 단위 테스트.
- **Phase 6: 신규 에셋** (`app/frontend/public/assets/`): `audio-thumbnail.svg`, `pdf-thumbnail.svg` — 미디어 타입 썸네일.
- **검증**: 프론트엔드 `npm run build` 성공, `npm run test` 14 passed.
- **배포 시 주의**: 프론트엔드 전용 변경. 백엔드/DB 변경 없음.
- **핵심 파일**: `app/frontend/src/components/editor/CollapsibleHeading.jsx`, `app/frontend/src/components/editor/TocSidebar.jsx`, `app/frontend/src/components/SimpleEditor.jsx`, `app/frontend/src/index.css`, `app/frontend/package.json`, `app/frontend/public/assets/audio-thumbnail.svg`, `app/frontend/public/assets/pdf-thumbnail.svg`.

### 통합 크레딧(포인트) 시스템 마이그레이션 — 페이지/오디오/비디오/에이전트 스텝 통합 과금

- **목표**: 기존 개별 사용량 제한(기본/프리미엄 페이지, 오디오/비디오 초)을 하나의 `points_balance` 크레딧 잔액으로 통합. 페이지/오디오/비디오/AI 에이전트 스텝 모두 포인트에서 차감되며, 월간 구독으로 크레딧을 지급한다.
- **크레딧 비율**: 기본 모델 페이지 1pt, 프리미엄 모델 페이지 5pt, 오디오 1pt/초, 비디오 10pt/초, Docling 후처리 페이지 3pt, AI 에이전트 스텝 1pt/스텝.
- **월간 구독 크레딧**: Free 1,000pt, Pro 30,000pt, Max 100,000pt.
- **Phase 1: DB 마이그레이션 & 백엔드 코어** (`app/backend/db/migrations/036_credit_system_subscription.sql` 신규):
  - `users` 테이블에 `subscription_credits_granted_at` 컬럼 추가 (중복 지급 방지).
  - `jobs` 테이블에 `cost_points`, `xlsx_advanced_cost_points`, `annotate_cost_points`, `ediscovery_cost_points` 컬럼 추가.
  - `app_settings`에 `cost_premium_video_sec_krw=10`, `cost_agent_step_krw=1` 반영.
  - `app/backend/core/points_service.py`: 비디오 10pt, 에이전트 스텝 1pt, Docling 후처리 3pt 비용 계산. 일일 무료 기본 페이지 로직 제거.
  - `app/backend/core/subscription_service.py`: `points_balance` 기반 `check_enough`, `reserve_usage`, `release_usage`, 월간 크레딧 지급, 구독 상태 조회.
  - `app/backend/workers/tasks.py` + `celery_app.py`: `grant_monthly_subscription_credits` Celery beat 태스크 추가.
- **Phase 2: API/Job 통합**:
  - `app/backend/api/v1/agent.py` (신규): `POST /api/v1/agent/steps` — AI 백엔드가 총 스텝 수를 보고하면 `X-AI-Backend-Secret` 검증 후 포인트 차감.
  - `app/backend/api/jobs.py`: `reserve_usage`/`release_usage`를 포인트 기반으로 변경, `GET /api/jobs/{job_id}` 응답에 `cost_basic`/`cost_premium`/`cost` 및 `subscription` 잔액/예상 비용 포함.
  - `app/backend/api/v1/jobs.py`: API 업로드/확인/환불 시 포인트 기반으로 변경, `calculate_cost`에서 `user_id` 인자 제거.
  - `app/backend/api/auth.py`: 사용하지 않는 `POST /api/auth/agent/spend-step` 제거.
- **Phase 3: AI 백엔드** (`app/ai-backend/src/lib/proof-api.ts`, `app/ai-backend/src/chat/route.ts`):
  - `spendAgentSteps(userId, steps, description)` 메서드 추가. `AI_BACKEND_SECRET` 환경변수로 `POST /api/v1/agent/steps` 호출.
  - `chat/route.ts`에서 `onStepFinish`당 1pt씩 차감하던 로직을 제거하고, `streamText` `onFinish`에서 `steps.length`로 총 스텝을 집계해 비동기 차감.
- **Phase 4: 프론트엔드 UI/UX**:
  - `PricePage.jsx` + `PlanCard.jsx`: 요금제 카드를 월간 크레딧 기준으로 표시.
  - `JobConfirmPage.jsx`: 잔여 포인트, 예상 비용, 차감 후 잔액 표시. 기존 페이지/미디어 잔여량 UI 제거.
  - `DashboardPage.jsx` + `SettingsPage.jsx`: 포인트 잔액 표시.
  - `ko/en/ja/page.json` 및 `common.json`: 포인트 단위 `$` → `pt` 변경 후 최종 크레딧(credits/クレジット)으로 통일.
- **검증**: `pytest tests/` 134 passed, AI 백엔드 `npm run build` 성공, 프론트엔드 `npm run test` + `npm run build` 성공. `test_points_service.py`, `test_subscription_credits.py`, `test_agent_steps.py` 추가.
- **배포 시 주의**: DB 마이그레이션 `036_credit_system_subscription.sql`을 `supabase-chungu-db` 컨테이너에 수동 적용. AI 백엔드(`.env`)에 `AI_BACKEND_SECRET` 추가, 백엔드 `config`에 동일값 설정. `deploy_a1.sh`로 a1 서버 배포.
- **핵심 파일**: `app/backend/db/migrations/036_credit_system_subscription.sql`, `app/backend/core/points_service.py`, `app/backend/core/subscription_service.py`, `app/backend/api/v1/agent.py`, `app/backend/api/jobs.py`, `app/backend/api/v1/jobs.py`, `app/ai-backend/src/chat/route.ts`, `app/ai-backend/src/lib/proof-api.ts`, `app/frontend/src/pages/JobConfirmPage.jsx`, `app/frontend/src/pages/PricePage.jsx`, `app/frontend/src/components/PlanCard.jsx`.

### Evidence-to-Element Mapper — 요건 사실 기반 증거 퍼즐 매퍼 (DnD + 입증 달성도 시각화)

- **목표**: 변호사가 사건 기획을 직관적으로 할 수 있도록 돕는 '요건 사실 기반 증거 퍼즐 매퍼' 추가. 청구 원인(예: 사기죄)에 따른 법적 요건 빈 슬롯을 제공하고, e-Discovery 그래프에서 추출된 증거(evidence) 노드를 @dnd-kit 드래그 앤 드롭으로 슬롯에 채우면 입증 달성도(%)를 시각화. 기존 EDiscoveryViewer 내 'Graph'/'Mapper' 탭 전환으로 통합.
- **의존성 추가**: `app/frontend/package.json`에 `@dnd-kit/core@^6.1.0`, `@dnd-kit/utilities@^3.2.2` 추가 — DnD 인프라 (deprecated된 react-beautiful-dnd 대체).
- **Phase 1: DB 마이그레이션 & 모델** (`app/backend/db/migrations/032_add_element_mappings.sql` 신규):
  - `jobs` 테이블에 `element_mappings JSONB NOT NULL DEFAULT '{}'::jsonb` 컬럼 추가.
  - `app/backend/db/models.py`: `Job` 클래스에 `element_mappings: Mapped[dict] = mapped_column(JSON, default=dict)` 추가 (ediscovery_* 필드 그룹 뒤).
- **Phase 2: 요건사실 추출 모듈** (`app/backend/core/legal_elements.py` 신규):
  - `extract_legal_elements(claim_type, endpoint, model, api_key)`: vLLM `call_text`로 청구명 → 법적 요건사실 3~5개 JSON 추출. `_build_legal_elements_prompt` — 한국 법률 체계 기준, 데이터 계약 스키마 준수. `_parse_legal_elements` — JSON 펜스 제거 + 스키마 검증 + 빈 슬롯 `mapped_evidence:[]` 주입.
  - `compute_overall_progress(mappings)`: 1개 이상 증거가 매핑된 요건의 비율(%) 계산.
- **Phase 3: FastAPI 엔드포인트** (`app/backend/api/ediscovery.py`에 추가, 기존 라우터 재사용):
  - `GET /api/jobs/{job_id}/legal-elements?claim_type={범죄명}`: vLLM으로 요건사실 추출. 같은 claim_type 재요청 시 캐시(저장된 element_mappings) 반환.
  - `PUT /api/jobs/{job_id}/legal-elements/mappings`: 퍼즐 상태를 `element_mappings` JSONB에 영속화. `overall_progress_percent` 서버 재계산.
  - `GET /api/jobs/{job_id}/legal-elements/mappings`: 저장된 매핑 조회 (페이지 새로고침 후 복원용).
  - `_resolve_llm_settings`: job.endpoint → settings_store → settings 기본값 순서로 LLM 설정 해석 (pipeline_ediscovery.run 패턴 준수).
- **Phase 4: 프론트엔드 DnD 인프라** (`app/frontend/src/components/mapper/` 신규 디렉토리):
  - `EvidenceMapperPanel.jsx`: 최상단 `<DndContext collisionDetection={closestCenter}>` 래퍼. 좌측 증거 카드 리스트(e-Discovery graph의 evidence 노드) + 우측 ElementDroppableSlots + 상단 ProgressBadge. claim_type 자유 텍스트 입력 + '요건사실 추출' 버튼. 드롭 시 요건 슬롯에 증거 append + `overall_progress_percent` 재계산 + PUT /mappings 자동 영속화. 페이지 로드 시 저장된 매핑 복원.
  - `EvidenceDraggableCard.jsx`: `useDraggable` 훅으로 증거 카드 감싸기. drag 시 `CSS.Transform.toString(transform)` 적용, 투명도/스케일 피드백. 이미 매핑된 증거는 disabled.
  - `ElementDroppableSlots.jsx`: 각 요건별 `useDroppable` 슬롯. 점선 테두리(`border-dashed border-2 border-gray-300 rounded-lg p-4`). 드래그 오버 시 `border-blue-500 bg-blue-50` 하이라이트. 매핑된 증거 카드 + 제거 버튼.
  - `ProgressBadge.jsx`: 상단 프로그레스 바(`bg-blue-600 transition-all duration-500`) + 도넛 차트 뱃지(SVG circle stroke-dasharray). shadcn/ui 없이 Tailwind + SVG로만 구현.
- **Phase 5: EDiscoveryViewer 통합** (`app/frontend/src/components/EDiscoveryViewer.jsx`):
  - 헤더에 'Graph'/'Mapper' 탭 전환 UI 추가 (`activeTab` state). Network/Puzzle 아이콘.
  - Mapper 탭에 `<EvidenceMapperPanel jobId job />` 렌더링. job.ediscovery_graphs에서 evidence 노드 추출해 mapper로 전달.
- **Phase 6: 프론트엔드 API 클라이언트** (`app/frontend/src/api.js`):
  - `getLegalElements(jobId, claimType)`, `saveElementMappings(jobId, data)`, `getElementMappings(jobId)` 메서드 추가.
- **Phase 7: AI 백엔드 도구** (`app/ai-backend/src/tools/mapper.ts` 신규):
  - `buildMapperTools(context)`: `get_legal_elements`(요건사실 추출), `save_element_mappings`(퍼즐 상태 저장), `get_element_mappings`(저장된 매핑 조회). ediscovery.ts 패턴 준수.
  - `app/ai-backend/src/lib/proof-api.ts`: `ElementMappings`/`LegalElement`/`MappedEvidence` 타입 정의 + `getLegalElements`/`saveElementMappings`/`getElementMappings` 클라이언트 메서드 추가.
  - `app/ai-backend/src/chat/route.ts`: `buildMapperTools` import + toolContext 등록 + 시스템 프롬프트 "9. Evidence-to-Element Mapper" 카테고리 추가.
- **Phase 8: i18n**: `app/frontend/src/locales/{ko,en,ja}/page.json`에 매퍼 키 14개 추가 (`mapperTabGraph` ~ `mapperRemoveEvidence`).
- **검증**: 백엔드 Job.element_mappings 필드 import 성공, legal_elements 모듈 import 성공, FastAPI 라우터 3개 등록 확인, compute_overall_progress 단위 테스트(50% 계산) 통과, 프론트엔드 Vite 빌드 성공 (2327 모듈 변환), AI 백엔드 TypeScript 빌드 성공 (에러 0).
- **배포 시 주의**: DB 마이그레이션 `032_add_element_mappings.sql`을 서버 `supabase-chungu-db` 컨테이너에 수동 적용 필요 (AGENTS.md "Deployment" 섹션 참조).
- **핵심 파일**: `app/backend/db/migrations/032_add_element_mappings.sql`, `app/backend/db/models.py`, `app/backend/core/legal_elements.py`, `app/backend/api/ediscovery.py`, `app/frontend/src/components/mapper/EvidenceMapperPanel.jsx`, `app/frontend/src/components/mapper/EvidenceDraggableCard.jsx`, `app/frontend/src/components/mapper/ElementDroppableSlots.jsx`, `app/frontend/src/components/mapper/ProgressBadge.jsx`, `app/frontend/src/components/EDiscoveryViewer.jsx`, `app/frontend/src/api.js`, `app/ai-backend/src/tools/mapper.ts`, `app/ai-backend/src/lib/proof-api.ts`, `app/ai-backend/src/chat/route.ts`, `app/frontend/src/locales/{ko,en,ja}/page.json`.

### e-Discovery 타임라인 시각화 고도화 — 스윔레인 + 모순점(Anomaly) 탐지 + 점진적 탐색 패널

- **목표**: 기존 평면 노드 그래프를 법률 전문가용 'e-Discovery 타임라인 시각화 뷰'로 고도화. 주체별 스윔레인 배치, 진술-증거 모순 자동 탐지(2차 LLM 패스), 점진적 탐색 오버레이, 쟁점 필터 디밍을 구현. 인지 과부하 최소화 및 모순점 직관적 파악이 핵심.
- **데이터 계약 변경**: `ediscovery_graphs` JSONB에 신규 스키마 도입 — `type: "swimlane"` 최상위 노드(원고/피고/제3자/쟁점 4레인), 자식 노드의 `parentId` 매핑, `type: "anomaly"` 엣지 + `data.conflict_reason`. 기존 평면 스키마 job은 그대로 유지되며 EDiscoveryViewer가 두 스키마를 모두 렌더링(폴백 포함).
- **Phase 1: 백엔드 추출 프롬프트/파싱 확장** (`app/backend/core/pipeline_ediscovery.py`):
  - `EdiscoveryNode` 데이터클래스에 `entity`, `date_text`, `date_iso`, `summary`, `parent_id` 필드 추가.
  - `_build_extraction_prompt` 확장 — entity(행위 주체), date(시간 표현), summary(1~2문 요약) 필드 추가 추출.
  - `_normalize_date(text)` 헬퍼 — 한국식(년/월/일)/일본식(年/月/日)/서양식(. - /) 날짜를 ISO YYYY-MM-DD로 정규화. 시간순 정렬용.
  - `_classify_entity(node_type, item_entity)` 헬퍼 — LLM 명시 entity 우선, 누락 시 node_type에서 추론.
  - `_parse_nodes` 확장 — 새 필드 파싱 + 날짜 정규화 + entity 분류.
- **Phase 2: 2차 LLM 모순(Anomaly) 탐지** (`pipeline_ediscovery.py`):
  - `AnomalyPair` 데이터클래스 — source_id, target_id, conflict_reason.
  - `_build_anomaly_prompt(nodes_batch)` — 추출된 노드 목록에서 진술(plaintiff/defendant) vs 객관적 증거(evidence) 충돌 쌍 탐지 프롬프트.
  - `_parse_anomalies(content, valid_ids)` — 응답 파싱 + 존재하지 않는 id 필터링.
  - `detect_anomalies_concurrent(nodes, endpoint, model, api_key)` — MAX_ANOMALY_NODES(200) 상한 적용 → 배치(40개) 분할 → ThreadPoolExecutor 병렬 2차 LLM 호출 → 중복 제거.
- **Phase 3: 스윔레인 구성 + 그래프 조립 재작성** (`pipeline_ediscovery.py`):
  - `SWIMLANE_IDS`/`SWIMLANE_LABELS` 상수 — 4개 swimlane 고정 ID + 표시 라벨.
  - `_build_swimlanes(nodes)` — 등장한 entity별 swimlane 노드 생성 + 각 노드에 parentId 주입. 미등장 주체는 swimlane 미생성.
  - `assemble_graph(nodes, anomalies)` 재작성 — 중복 제거 → 노드 수 상한 → swimlane 생성 → 시간순 정렬(date_iso → page → id) → 같은 swimlane 내 인접 노드 간 smoothstep 엣지 + 모순 쌍 간 anomaly 엣지 조립. 데이터 계약 스키마 준수.
- **Phase 4: run 오케스트레이션 갱신** (`pipeline_ediscovery.py`):
  - `run`에 2차 LLM 패스 삽입 — 노드 추출 → 임계값 필터 → `detect_anomalies_concurrent` → `assemble_graph(filtered, anomalies)`.
  - metrics에 `anomalies_detected` 키 추가.
- **Phase 5: ELK 스윔레인 레이아웃** (`app/frontend/src/utils/elkLayout.js`):
  - `calculateElkSwimlaneLayout(nodes, edges)` 신규 — `elk.algorithm: 'layered'` + `elk.partitioning.activate: 'true'`. 부모(swimlane) 내부에 자식을 중첩한 ELK JSON 구성. React Flow v12 규칙에 따라 `node.measured?.width` 우선 참조, 폴백 `node.data?.width`. 부모가 없으면 `calculateElkLayout` 평면 레이아웃으로 폴백. 기존 `calculateElkLayout`은 FlowViewer 호환성을 위해 유지.
- **Phase 6: AnomalyEdge 컴포넌트** (`app/frontend/src/components/flow/AnomalyEdge.jsx` 신규):
  - `BaseEdge` + `getBezierPath`로 빨간 점선 패스 렌더링. `animate-dash` 클래스로 stroke-dashoffset 흐름 애니메이션.
  - `EdgeLabelRenderer` 포털로 중앙에 "모순 발생" 경고 뱛지(빨간 배경 + AlertTriangle 아이콘). 호버 시 `data.conflict_reason` 툴팁 표시.
- **Phase 7: index.css 애니메이션** (`app/frontend/src/index.css`):
  - `@keyframes dash` + `.animate-dash` 클래스 추가 — stroke-dasharray: 6 4, 1s linear infinite.
- **Phase 8: EDiscoveryViewer 고도화** (`app/frontend/src/components/EDiscoveryViewer.jsx`):
  - `SwimlaneNode` 컴포넌트 — entity별 색상 코딩(원고=파랑/피고=주황/제3자=보라/쟁점=빨강) + 점선 테두리.
  - `dimClass(data)` 헬퍼 — `data.dimmed` 시 `opacity-20 grayscale transition-opacity duration-300` 적용. 모든 노드 컴포넌트에 디밍 적용.
  - `nodeTypes`에 `eDiscovery-swimlane` 등록, `edgeTypes`에 `anomaly: AnomalyEdge` 등록.
  - `buildGraph` 신/구 스키마 분기 — `parentId` 보유 노드가 있으면 `calculateElkSwimlaneLayout`, 없으면 `calculateElkLayout` 폴백. 엣지 type 보존(anomaly 엣지가 AnomalyEdge로 렌더링되도록).
  - `IssueFilterBar` 컴포넌트 — 그래프에서 고유 issue 라벨 추출 → 토글 칩 렌더링. 미선택 쟁점 노드는 hidden 대신 디밍.
  - `DetailOverlayPanel` 컴포넌트 — 노드 클릭 시 우측 슬라이드인 패널(`animate-stagger-enter`). label/summary/page/confidence/date 표시 + "원본 PDF 보기" 버튼 → `onNodeClick` 콜백으로 SourcePanel scrollToPage 연동.
  - `applyIssueFilter` — 선택된 쟁점 집합 기반 노드 data.dimmed 플래그 갱신. swimlane은 필터 제외.
  - `handleNodeClick` — swimlane 클릭 시 오버레이 미표시, 일반 노드 클릭 시 오버레이 + 외부 onNodeClick 호출.
  - `useRef` import 누락 버그 수정 (pollRef용).
- **Phase 9: AI 백엔드 인터페이스 갱신** (`app/ai-backend/src/tools/ediscovery.ts`):
  - `GraphNode` 인터페이스에 `parentId?`, `entity?`, `date?`, `summary?`, `issue?` 추가.
  - `GraphEdge` 인터페이스에 `data?: { conflict_reason? }` 추가.
- **Phase 10: i18n** (`app/frontend/src/locales/{ko,en,ja}/page.json`):
  - 신규 키 12개 추가 — `ediscoveryAnomalyBadge`, `ediscoveryIssueFilter`, `ediscoveryDetailTitle`, `ediscoveryViewSource`, `ediscoveryClose`, `ediscoverySummary`, `ediscoveryPage`, `ediscoveryConfidence`, `ediscoverySwimlanePlaintiff`/`Defendant`/`ThirdParty`/`Issue`.
- **검증**: 백엔드 import 성공 + 단위 테스트(날짜 정규화/주체 분류/swimlane 조립/anomaly 파싱) 통과, 기존 43개 테스트 회귀 없음, 프론트엔드 Vite 빌드 성공(2320 모듈), AI 백엔드 TypeScript 빌드 성공(에러 0).
- **배포 시 주의**: DB 마이그레이션 불필요 (`ediscovery_graphs`는 JSONB라 스키마 변경에 컬럼 추가 없음). 다만 `ediscovery_metrics`에 `anomalies_detected` 키가 추가되어 기존 job은 해당 키가 0/없음으로 표시됨.
- **핵심 파일**: `app/backend/core/pipeline_ediscovery.py`, `app/frontend/src/utils/elkLayout.js`, `app/frontend/src/components/flow/AnomalyEdge.jsx`, `app/frontend/src/components/EDiscoveryViewer.jsx`, `app/frontend/src/index.css`, `app/ai-backend/src/tools/ediscovery.ts`, `app/frontend/src/locales/{ko,en,ja}/page.json`.

### e-Discovery GraphRAG 백엔드 파이프라인 — 법률 문서 쟁점/증거 그래프 추출

- **목표**: 수천 장 단위의 법률 문서에서 쟁점(issue)/원고(plaintiff)/피고(defendant)/증거(evidence) 노드를 추출해 React Flow 시각화용 그래프 JSON으로 조립하는 e-Discovery 파이프라인을 백엔드(Python/FastAPI/Celery)에 추가. 기존 `annotate`/`xlsx_advanced`의 과금·상태 추적·Celery 큐잉 패턴을 재사용.
- **Phase 1: DB 마이그레이션** (`app/backend/db/migrations/031_add_ediscovery_fields.sql` 신규):
  - `jobs` 테이블에 8개 컬럼 추가: `ediscovery_status`, `ediscovery_job_id`, `ediscovery_graphs`(JSONB), `ediscovery_metrics`(JSONB), `ediscovery_params`(JSONB), `ediscovery_refundable`, `ediscovery_reserved_pages`, `ediscovery_reserved_period_start`.
  - `ediscovery_status` 부분 인덱스 생성 (`WHERE ediscovery_status <> ''`).
  - 번호 030은 기존 `030_add_chat_conversations.sql`이 사용 중이므로 031 사용.
- **Phase 2: 모델 업데이트** (`app/backend/db/models.py`):
  - `Job` 클래스에 8개 `ediscovery_*` 필드 매핑 추가 (기존 `annotate_*` 필드 그룹 패턴 준수).
- **Phase 3: 추출 파이프라인** (`app/backend/core/pipeline_ediscovery.py` 신규):
  - `extract_page_texts(job)`: `searchable_pdf_storage_path` → `pdf_storage_path` → `result_md_storage_path` 순서 폴백. PyMuPDF `page.get_text("blocks")`로 페이지별 텍스트 추출 (pdf_annotate_converter 패턴 재사용).
  - `build_parent_child_chunks(page_texts, chunk_size, overlap, page_range)`: 부모=페이지 전체, 자식=슬라이딩 윈도우(단어 단위, 기본 512단어 + 64 overlap). 페이지 메타데이터 보존.
  - `extract_nodes_from_chunk(chunk, endpoint, model, api_key)`: vLLM Proxy(`call_text`) 호출 → 쟁점/원고/피고/증거 노드 JSON 추출. 데이터 계약 스키마 준수.
  - `extract_nodes_concurrent(chunks, ...)`: ThreadPoolExecutor로 청크별 vLLM 호출 병렬화 (MAX_LLM_WORKERS=16 상한).
  - `filter_nodes_by_threshold(nodes, threshold)`: confidence 임계값 필터링 (파이프라인 방식).
  - `assemble_graph(nodes)`: 중복 제거(label+type 기준) + 같은 페이지 내 smoothstep 엣지 생성. 노드 수 상한 5000.
  - `run(job_id, chunk_size, threshold, page_range, max_chunks, query, max_docs)`: 전체 오케스트레이션. 상태 갱신(done/error), 환불 플래그, `ediscovery_graphs`/`ediscovery_metrics` JSONB 저장. `max_docs`는 `max_chunks`의 별칭(api/ediscovery.py 호환용).
- **Phase 4: Celery 태스크** (`app/backend/workers/tasks.py`):
  - `@celery.task run_ediscovery(job_id, chunk_size, threshold, page_range, max_chunks, query)` 등록 → `pipeline_ediscovery.run` 호출.
- **Phase 5: FastAPI 엔드포인트** (`app/backend/api/jobs.py`):
  - `POST /api/jobs/{job_id}/ediscovery/extract`: Celery 백그라운드 큐잉. 파라미터: chunk_size, threshold, max_chunks, query, page_range. 관리자 무료 / 일반 사용자 `premium_pages` 차감 + 환불 가능. 같은 파라미터 재사용 시 캐시 반환.
  - `GET /api/jobs/{job_id}/ediscovery`: 상태/그래프/메트릭 반환 (폴링용).
  - `POST /api/jobs/{job_id}/ediscovery/threshold`: 저장된 그래프에서 confidence 기준 재필터링 (재추출 없이 엣지/노드만 재구성).
  - `_job_summary()`에 `ediscovery_status`, `ediscovery_graphs`, `ediscovery_metrics`, `ediscovery_refundable` 필드 추가.
- **Phase 6: 병렬 에이전트 충돌 조정**:
  - `app/backend/api/ediscovery.py`에 동일 경로의 동기 처리 엔드포인트가 별도 존재했으나, `jobs.py`의 Celery 기반 엔드포인트와 중복되어 `main.py`에서 `ediscovery_router` 등록을 제거. `jobs.router`가 정식 제공자.
  - `pipeline_ediscovery.run`에 `max_docs` 별칭 파라미터 추가 — `api/ediscovery.py`의 `extract`/`threshold` 엔드포인트가 `max_docs=` 키워드로 호출하므로 호환성 유지.
- **검증**: Job 모델 필드 8개 import 성공, pipeline_ediscovery import 성공, run_ediscovery Celery 태스크 import 성공, run 시그니처 호환(max_docs/max_chunks/query 포함), FastAPI 라우터 3개 등록 확인(중복 없음), 청킹/필터/그래프 조립 단위 테스트 통과, 데이터 계약 스키마 준수 확인, 기존 43개 테스트 회귀 없음.
- **배포 시 주의**: DB 마이그레이션 `031_add_ediscovery_fields.sql`을 서버 `supabase-chungu-db` 컨테이너에 수동 적용 필요 (AGENTS.md "Deployment" 섹션 참조).
- **핵심 파일**: `app/backend/db/migrations/031_add_ediscovery_fields.sql`, `app/backend/db/models.py`, `app/backend/core/pipeline_ediscovery.py`, `app/backend/workers/tasks.py`, `app/backend/api/jobs.py`, `app/backend/main.py`.

### Flow Panel 에이전트 조작 도구 확장 — 드로잉/주석/노트/엣지/헤딩 노드 CRUD

- **목표**: 플로우뷰(React Flow)의 드로잉, 텍스트 주석, 노트 노드, 커스텀 엣지, 헤딩 노드 구조를 에이전트가 조작할 수 있도록 AI 백엔드 도구를 확장. 기존 `flow.ts`에는 읽기/분석 전용 도구 2개만 있었고, 드로잉/주석 CRUD, 노트/엣지 영속화, 헤딩 노드 조작 도구가 전무했음. 백엔드 `flow_drawings` API와 프론트엔드 저장 로직은 사용자 수동 조작용으로만 구현되어 있었음.
- **의존성 추가**: `app/ai-backend/package.json`에 `elkjs@^0.9.3` 추가 — 서버 사이드 레이아웃 계산용 (에이전트가 드로잉/주석을 노드 근처에 배치할 때 좌표 참조).
- **Phase 1: 백엔드 DB 마이그레이션 & API 확장**:
  - `app/backend/db/migrations/029_add_flow_notes_edges.sql` (신규): `flow_drawings` 테이블에 `note_nodes JSONB`, `custom_edges JSONB` 컬럼 추가.
  - `app/backend/db/models.py`: `FlowDrawing` 모델에 `note_nodes`, `custom_edges` 컬럼 추가.
  - `app/backend/api/flow_drawings.py`: `FlowDrawingData` Pydantic 모델 + GET/PUT 응답에 `note_nodes`, `custom_edges` 필드 포함.
- **Phase 2: AI 백엔드 proof-api.ts 클라이언트 확장**:
  - `app/ai-backend/src/lib/proof-api.ts`: `getFlowDrawings`/`saveFlowDrawings`/`deleteFlowDrawings` 클라이언트 메서드 추가 (GET/PUT/DELETE `/api/jobs/{jobId}/flow-drawings`).
- **Phase 3: 드로잉/주석 도구** (`app/ai-backend/src/tools/flow.ts`):
  - `createShapePath` 포팅: `drawingUtils.js`의 선/화살표/사각형/원 SVG path 생성 로직을 TypeScript로 이식.
  - `get_flow_layout`: elkjs로 마크다운 헤딩 노드 위치 계산 → 에이전트가 드로잉/주석 배치 시 좌표 참조.
  - `get_flow_drawings`: 서버에서 현재 paths, text_annotations, note_nodes, custom_edges 조회.
  - `add_flow_shape`: 도형(선/화살표/사각형/원) SVG path 생성 추가. 입력: shapeType, 좌표(x1,y1,x2,y2), strokeColor, strokeWidth.
  - `add_flow_text_annotation`: 텍스트 주석 추가. 입력: text, x/y, color, fontSize.
  - `delete_flow_drawing`: ID로 특정 path 또는 text annotation 삭제.
  - `clear_flow_drawings`: 모든 드로잉/주석/노트/엣지 초기화.
  - `save_flow_drawings`: 보류 중인 변경사항을 서버에 PUT 저장. 변경된 전체 상태 반환 (프론트엔드 동기화용).
  - read-modify-write 패턴: `ensureLoaded()`로 서버에서 로드 → 보류 버퍼에서 조작 → `save_flow_drawings`로 영속화 (markdown.ts의 edits 버퍼 패턴과 동일).
- **Phase 4: 노트 노드 & 커스텀 엣지 도구** (`flow.ts`):
  - `add_flow_note`: 스티키 노트 추가. 입력: text, x/y, width, height.
  - `update_flow_note`: 노트 텍스트/크기 수정. 입력: noteId, text?, width?, height?.
  - `delete_flow_note`: ID로 노트 삭제.
  - `add_flow_edge`: 두 노드 간 커스텀 엣지 추가. 입력: sourceNodeId, targetNodeId, label?.
  - `delete_flow_edge`: ID로 엣지 삭제.
- **Phase 5: 헤딩 노드 조작 도구** (`flow.ts` — 내부적으로 마크다운 편집):
  - `add_flow_heading`: 마크다운에 새 헤딩 추가 → 플로우뷰에 새 노드 생성. parentHeading 지정 시 해당 섹션 끝에, 생략 시 문서 끝에 추가.
  - `delete_flow_heading`: 헤딩 섹션 전체 삭제 → 플로우뷰에서 노드 제거.
  - `rename_flow_heading`: 헤딩 텍스트 변경 → 플로우뷰 노드 제목 수정.
  - `move_flow_heading`: 헤딩 레벨 변경 → 플로우뷰 노드 계층 이동.
  - `_findHeadingLineRange` 헬퍼: 마크다운에서 헤딩 라인 인덱스 범위 검색.
  - 헤딩 도구는 마크다운을 직접 수정하므로 `apply_edits`와 혼용 금지 (시스템 프롬프트에 명시).
- **Phase 6: route.ts 시스템 프롬프트 업데이트**:
  - `app/ai-backend/src/chat/route.ts`: `buildSystemPrompt()`에 "7. Flow view manipulation" 도구 카테고리 추가. 레이아웃/드로잉/주석/노트/엣지/헤딩 도구 사용 규칙 명시. "항상 `get_flow_layout` 먼저 호출", "조작 후 반드시 `save_flow_drawings` 호출", "헤딩 도구는 `apply_edits`와 혼용 금지" 지시.
- **Phase 7: 프론트엔드 동기화**:
  - `app/frontend/src/hooks/useFlowDrawing.js`: `noteNodes`/`customEdges` state 추가. 서버 GET/localStorage/자동 저장 PUT에 새 필드 포함. `updateFromAgent(data)` 메서드 추가 — 에이전트 도구 결과로 받은 전체 상태를 로컬에 즉시 반영.
  - `app/frontend/src/components/FlowViewer.jsx`: `forwardRef` + `useImperativeHandle`로 `updateFromAgent` 외부 노출. `drawingApiRef`로 FlowCanvas에 전달. `noteNodes`를 React Flow `noteNode` 타입 노드로 변환하여 `nodes` state에 통합. `customEdges`를 `custom` 타입 엣지로 변환하여 `edges` state에 통합.
  - `app/frontend/src/components/AgentChatModal.jsx`: `onFlowDrawingsUpdate` prop 추가. ChatSession에서 `messages`의 `save_flow_drawings` 도구 결과(`state === "output-available"`)를 감지하여 콜백 호출.
  - `app/frontend/src/pages/JobResultPage.jsx`: `flowViewerApiRef` 생성 → FlowViewer에 ref 연결. AgentChatModal에 `onFlowDrawingsUpdate` 콜백 전달 → `flowViewerApiRef.current.updateFromAgent(data)` 호출로 즉시 동기화.
- **Phase 8: i18n**: `app/frontend/src/locales/{ko,en,ja}/page.json`에 신규 도구 라벨 18개 추가 (`extract_flow_structure` ~ `move_flow_heading`).
- **검증**: AI 백엔드 TypeScript 빌드 성공 (에러 0), 프론트엔드 Vite 빌드 성공 (2337 모듈 변환), 백엔드 모델/API에 note_nodes/custom_edges 컬럼 정상 추가 확인.
- **배포 시 주의**: DB 마이그레이션 `029_add_flow_notes_edges.sql`을 서버 `supabase-chungu-db` 컨테이너에 수동 적용 필요 (AGENTS.md "Deployment" 섹션 참조).
- **핵심 파일**: `app/ai-backend/src/tools/flow.ts`, `app/ai-backend/src/lib/proof-api.ts`, `app/ai-backend/src/chat/route.ts`, `app/backend/db/migrations/029_add_flow_notes_edges.sql`, `app/backend/db/models.py`, `app/backend/api/flow_drawings.py`, `app/frontend/src/hooks/useFlowDrawing.js`, `app/frontend/src/components/FlowViewer.jsx`, `app/frontend/src/components/AgentChatModal.jsx`, `app/frontend/src/pages/JobResultPage.jsx`, `app/frontend/src/locales/{ko,en,ja}/page.json`.

### Flow Panel 기능 확장 — 드로깅/주석, 노드 리사이즈, 원문 PDF 스크롤 연동

- **목표**: React Flow 기반 Flow Panel 에 3가지 기능 추가: (1) 풍부한 드로잉/주석 도구, (2) 드래그앤드롭 노드 리사이즈, (3) 플로우 노드 클릭 시 왼쪽 SourcePanel 원문 PDF의 해당 페이지로 자동 스크롤. koda-learn 프로젝트의 `perfect-freehand` + SVG path 드로잉 엔진을 이식하고 React Flow의 `NodeResizer`/`ViewportPortal`로 통합.
- **의존성 추가**: `app/frontend/package.json`에 `perfect-freehand@^1.2.2` 추가 — 부드러운 곡선 생성.
- **Phase 1: 노드 리사이즈** (`app/frontend/src/components/FlowViewer.jsx`):
  - `HeadingNode`/`NoteNode`에 `@xyflow/react`의 `NodeResizer` 추가.
  - 선택 시에만 핸들 노출 (`isVisible={selected}`), 최소/최대 크기 제한 (`minWidth/maxWidth/minHeight`).
  - 고정 너비 CSS(`w-[280px]`, `w-[200px]`) 제거하고 `style={{ width: data.width }}`로 동적 적용. `elkLayout.js`는 이미 `data.width`/`data.height`를 존중.
- **Phase 2: 노드 클릭 → 원문 PDF 스크롤 연동**:
  - `app/frontend/src/utils/markdownToFlow.js`: `<!-- 페이지 N -->` HTML 주석을 정규식으로 추적, 각 heading 노드의 `data.page`에 페이지 번호 할당 (마커 없는 문서는 `1` 폴백).
  - `app/frontend/src/components/SourcePanel.jsx`: `forwardRef` + `useImperativeHandle`로 `scrollToPage(pageNum)` 메서드 외부 노출.
  - `app/frontend/src/pages/JobResultPage.jsx`: `sourcePanelApiRef` 생성 → `FlowViewer`의 `onNodeClick`에서 `sourcePanelApiRef.current.scrollToPage(node.data.page)` 호출.
- **Phase 3: 드로잉/주석 도구**:
  - `app/frontend/src/utils/drawingUtils.js` (신규): `getFreehandPath` (perfect-freehand), `createShapePath` (선/화살표/사각형/원), `eraseAtPoint`/`eraseTextAtPoint`.
  - `app/frontend/src/hooks/useFlowDrawing.js` (신규): 펜/형광펜/지우개/텍스트/도형 모드, 색상/굵기, Undo/Clear, localStorage 자동 저장 + 서버 자동 저장 (2초 debounce). 드로잉 중 동기 상태 추적을 위해 `isDrawingRef`/`currentPointsRef` 사용 (stale closure 방지).
  - `app/frontend/src/components/flow/DrawingOverlay.jsx` (신규): React Flow `ViewportPortal` 내부에 SVG 렌더링 → pan/zoom 자동 따라감. 드로잉 모드에서만 `pointerEvents: auto`.
  - `app/frontend/src/components/flow/DrawingToolbar.jsx` (신규): 하단 중앙 툴바 — 모드 전환, 색상 팝오버(8색), 굵기 슬라이더(1~20px), 도형 서브메뉴, Undo/Clear.
  - `FlowViewer.jsx` 통합: `useFlowDrawing` 훅 사용, 드로잉 모드 시 `panOnDrag={false}` + `nodesDraggable={false}`로 React Flow 상호작용 차단.
- **Phase 4: 서버 저장 (Supabase)**:
  - `app/backend/db/migrations/028_add_flow_drawings.sql` (신규): `flow_drawings` 테이블 — `job_id` + `user_id` UNIQUE, `paths JSONB`, `text_annotations JSONB`.
  - `app/backend/db/models.py`: `FlowDrawing` SQLAlchemy 모델 추가.
  - `app/backend/api/flow_drawings.py` (신규): GET/PUT/DELETE `/api/jobs/{job_id}/flow-drawings` CRUD API. `response_model=None`로 `CurrentUser` Pydantic 변환 회피.
  - `app/backend/main.py`: `flow_drawings_router` 등록.
  - `app/frontend/src/api.js`: `getFlowDrawings`/`saveFlowDrawings`/`deleteFlowDrawings` 클라이언트 메서드 추가.
- **Phase 5: i18n**: `app/frontend/src/locales/{ko,en,ja}/page.json`에 14개 드로잉 키 추가 (`flowSelectMode`, `flowDraw`, `flowHighlight`, `flowEraser`, `flowText`, `flowShape`, `flowShapeLine`, `flowShapeArrow`, `flowShapeRectangle`, `flowShapeCircle`, `flowStrokeColor`, `flowStrokeWidth`, `flowUndo`, `flowClear`).
- **디버깅/검증**: 로컬 Vite dev server + Playwright 브라우저에서 Flow 뷰 전환, 드로잉 툴바, 펜 드로잉 저장, 노드 클릭 → `scrollToPage` 호출, NodeResizer 핸들 노출, 프론트엔드 빌드, 백엔드 import 확인.
- **배포 시 주의**: DB 마이그레이션 `028_add_flow_drawings.sql`을 서버 `supabase-chungu-db` 컨테이너에 수동 적용 필요 (AGENTS.md "Deployment" 섹션 참조).
- **핵심 파일**: `app/frontend/src/components/FlowViewer.jsx`, `app/frontend/src/hooks/useFlowDrawing.js`, `app/frontend/src/utils/drawingUtils.js`, `app/frontend/src/components/flow/DrawingOverlay.jsx`, `app/frontend/src/components/flow/DrawingToolbar.jsx`, `app/frontend/src/pages/JobResultPage.jsx`, `app/frontend/src/components/SourcePanel.jsx`, `app/frontend/src/utils/markdownToFlow.js`, `app/backend/api/flow_drawings.py`, `app/backend/db/migrations/028_add_flow_drawings.sql`.

### Flow Panel — 마크다운 헤딩 구조를 React Flow 그래프로 시각화 + 드롭다운 뷰 전환

- **목표**: 결과페이지(JobResultPage)에 마크다운 문서의 헤딩(H1~H6) 구조를 React Flow 캔버스에 논리 흐름 그래프로 시각화하는 플로우 패널 추가. 기존 가로형 탭 버튼(Markdown/Excel/Excel Advanced)을 드롭다운 메뉴로 교체하여 Markdown/Excel/Flow 뷰를 전환. 상세 계획은 `FLOW_PANEL_PLAN.md` 참조.
- **MCP 조사 기반 구현**: context7 + deepwiki MCP로 React Flow v12, elkjs, marked의 최신 API 시그니처를 사전 조사하여 정확한 API 사용.
- **Phase 1: 의존성 설치 + 인프라**:
  - `@xyflow/react` (React Flow v12, 구 `reactflow`에서 패키지명 변경), `elkjs` (Eclipse Layout Kernel), `uuid` npm 설치.
  - `app/frontend/src/index.css`: `@import "@xyflow/react/dist/style.css"` 추가 (PostCSS `@import` 우선 순위 준수).
  - `app/frontend/src/locales/{ko,en,ja}/page.json`: flow 관련 i18n 키 11개 추가 (flow, flowView, flowLoading, flowEmpty, flowResetLayout, flowFitView, flowAnalyzeDeps, flowAnalyzing, flowDepEdges, flowHierarchyEdges, viewMode).
- **Phase 2: 마크다운 → Flow 파서 (순방향 파이프라인)**:
  - `app/frontend/src/utils/markdownToFlow.js`: `marked.lexer()`로 토큰화 → heading 토큰(`{ type, depth, text }`)을 React Flow 노드로 변환 → 스택 기반 부모-자식 계층 에지 생성 → 하위 콘텐츠를 `content`/`contentPreview`(200자)에 축적. 토큰 소모 0, 순수 파싱.
  - `app/frontend/src/utils/elkLayout.js`: `elkjs/lib/elk.bundled.js` import → ELK JSON 그래프 형식(`{ id, layoutOptions, children, edges }`) 구성 → `elk.layout()` 호출 → 계산된 x/y 좌표를 노드에 매핑. 레이아웃 옵션: `elk.algorithm: 'layered'`, `elk.direction: 'DOWN'`, `elk.spacing.nodeNode: '80'`, `elk.layered.spacing.nodeNodeBetweenLayers: '100'`.
- **Phase 3: FlowViewer 컴포넌트** (`app/frontend/src/components/FlowViewer.jsx`):
  - `HeadingNode` 커스텀 노드: 제목 + H레벨 배지 + 내용 미리보기 (line-clamp-3). `<Handle>` 컴포넌트로 연결점 표시.
  - `HierarchyEdge` 커스텀 엣지: 실선 (부모-자식 heading 관계). `BaseEdge` + `getBezierPath` 사용.
  - `DependencyEdge` 커스텀 엣지: 점선 + 호버 시 `EdgeLabelRenderer` 포털로 `reason` 툴팁 렌더링 (AI 의존성 분석 결과 표시용).
  - `ReactFlowProvider` + `useNodesState`/`useEdgesState` + `useReactFlow().fitView()`. `<Background>`, `<Controls>`, `<MiniMap>` 내장 컴포넌트. `proOptions={{ hideAttribution: true }}`.
- **Phase 4: 드롭다운 뷰 전환기** (`app/frontend/src/pages/JobResultPage.jsx`):
  - 기존 가로형 탭 버튼 3개(Markdown/Excel/Excel Advanced)를 드롭다운 메뉴로 교체. 기존 `openDropdown`/`closeDropdown` hover timer 패턴 재사용.
  - `previewMode` state에 `"flow"` 추가 (`"markdown" | "xlsxBasic" | "xlsxAdvanced" | "flow"`).
  - `renderRightContent()`에 flow 분기 추가: `FlowViewer` 컴포넌트 렌더링.
  - `Workflow`, `ChevronDown` 아이콘 import 추가. `FlowViewer` import 추가.
- **Phase 5: AI 의존성 추론 파이프라인 (백엔드)**:
  - `app/ai-backend/src/tools/flow.ts`: `buildFlowTools` 팩토리 — 2개 도구:
    - `extract_flow_structure`: 마크다운에서 헤딩 트리 추출 (토큰 소모 0, `marked.lexer()` 순수 파싱). 노드 배열 + 계층 에지 배열 반환.
    - `infer_flow_dependencies`: 압축 메타데이터를 LLM에 전달하여 크로스 섹션 논리적 의존성 에지 추론. 참고 자료의 시스템 프롬프트 템플릿 적용.
  - `app/ai-backend/src/chat/route.ts`: `buildFlowTools` import + `tools` 객체에 스프레드 등록. `buildSystemPrompt()`에 "6. Flow analysis" 도구 카테고리 설명 추가.
  - `app/ai-backend/package.json`: `marked` 의존성 추가.
- **Phase 6: 양방향 동기화 (향후 확장)**: 순환 참조 탐지(DFS), 다중 부모 검증, 위상 정렬 트리 복원, 드래그 앤 드롭 리팩토링, 실시간 동기화(Flow → 마크다운 에디터 `editor.commands.setContent()`). 별도 스프린트 예정.
- **핵심 파일**: `FLOW_PANEL_PLAN.md`, `app/frontend/src/utils/markdownToFlow.js`, `app/frontend/src/utils/elkLayout.js`, `app/frontend/src/components/FlowViewer.jsx`, `app/frontend/src/pages/JobResultPage.jsx`, `app/frontend/src/locales/{ko,en,ja}/page.json`, `app/frontend/src/index.css`, `app/ai-backend/src/tools/flow.ts`, `app/ai-backend/src/chat/route.ts`.

### AI 에이전트 툴콜 응답 처리 개선 — LLMLingua-2 동적 프롬프트 압축 + maxOutputTokens + 도구 출력 제한

- **목표**: 에이전트가 툴콜 결과를 읽고 다음 툴콜을 호출하지 못하는 문제를 5가지 방향으로 수정. Gemma 4-26B 모델의 토큰 예산 부족, 도구 출력 과다, 시스템 프롬프트 모호성, 디버깅 로그 부족을 해결.
- **maxOutputTokens 8192 설정** (`app/ai-backend/src/chat/route.ts`): vLLM 기본값(128~256)은 툴콜 결과 분석에 부족하므로 `streamText()`에 `maxOutputTokens: 8192` 추가.
- **LLMLingua-2 동적 프롬프트 압축 마이크로서비스** (`app/llmlingua-service/` — 3파일):
  - `main.py`: FastAPI 서버 — POST `/compress` 엔드포인트. LLMLingua-2 `PromptCompressor(model_name="microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank", use_llmlingua2=True)` 사용.
  - **동적 rate 선택** (`_selectDynamicRate`): 도구 결과 크기(문자 수)에 따라 3단계 자동 선택 — 4000~8000자→0.5(2x), 8000~20000자→0.3(3x), 20000자+→0.2(5x). 논문 Appendix L Sample-Wise Dynamic Compression Ratio 방식 적용.
  - **`dynamic_context_compression_ratio=0.4`**: 각 문맥(청크)마다 40% 가변 허용하여 정보 밀도에 맞춤.
  - **`force_tokens`**: 8개 핵심 JSON 키(`error`, `id`, `page`, `bbox`, `rect`, `color`, `contents`, `type`) 보존하여 좌표/ID/페이지/색상 손실 방지.
  - `Dockerfile`: Python 3.11-slim + llmlingua 패키지 + 모델 사전 다운로드 (런타임 지연 방지). builder/runtime 2단계 이미지.
  - `requirements.txt`: llmlingua>=0.2.0, fastapi, uvicorn, pydantic.
- **Node.js 클라이언트** (`app/ai-backend/src/lib/llmlingua.ts`):
  - `shouldCompress(text, threshold=4000)`: 임계값 초과 시만 압축.
  - `compressToolResults(text, dynamic=true)`: Python 서비스에 POST `/compress` 요청, 실패 시 원본 폴백 (30초 타임아웃).
- **prepareStep 통합** (`app/ai-backend/src/chat/route.ts`): `prepareStep` 콜백에서 이전 스텝의 tool 결과 JSON이 4000자 초과 시 LLMLingua-2 압축 적용. 압축된 데이터를 시스템 메시지로 주입.
- **도구 출력 크기 제한**:
  - `annotations.ts`: `get_elements` 50→20개, `read_job_json` 80→30개, `get_annotations` 80→30개.
  - `sandbox.ts`: `execute_in_sandbox` stdout 2000자/stderr 1000자 제한, `read_sandbox_file` content 4000자 제한 (`_truncate` 헬퍼 함수).
  - `spreadsheet.ts`: `get_sheet` rows 50→20행.
  - `browserless.ts`: `extract_web_text` text 3000자 제한.
- **시스템 프롬프트 개선** (`route.ts`): "CRITICAL: Always read and analyze tool results before making the next tool call" 지시 추가. "After calling a tool, summarize what you learned from its output before deciding the next step" 추가.
- **onStepFinish 로깅** (`route.ts`): 각 스텝 종료 시 `finishReason`, `toolCalls`, `toolResults`, `usage`(input/output tokens) 로그 출력.
- **docker-compose.yml + .env.example**: `llmlingua` 서비스 추가 (포트 8001), `ai-backend`에 `LLMLINGUA_URL=http://llmlingua:8000` 환경변수 추가. `.env.example`에 `LLMLINGUA_URL`/`LLMLINGUA_RATE`/`LLMLINGUA_MODEL` 3개 환경변수 추가.
- **리서치 근거**: LLMLingua-2 논문(arxiv 2403.12968) Table 5/6/12, Appendix L. 동적 압축(DCR)이 고정 비율(FR) 대비 5x/7x에서 +17.5% 성능 개선. 5x(rate=0.2)에서도 원본 대비 89% 성능 유지, 2.9x 지연 가속.
- **핵심 파일**: `app/llmlingua-service/`(3파일), `app/ai-backend/src/lib/llmlingua.ts`, `app/ai-backend/src/chat/route.ts`, `app/ai-backend/src/tools/annotations.ts`, `app/ai-backend/src/tools/sandbox.ts`, `app/ai-backend/src/tools/spreadsheet.ts`, `app/ai-backend/src/tools/browserless.ts`, `app/docker-compose.yml`, `app/.env.example`.

### Kata Containers + Cloud Hypervisor 기반 에이전트 샌드박스 (격리 실행 환경)

- **목표**: PROOF 결과 페이지의 문서/이미지/오디오/비디오 파일들을 격리된 Kata Containers microVM 내부의 `/workspace`로 마운트하여, 에이전트가 자유롭게 코드 작성/실행할 수 있도록 함. 300+ 동시 VM 목표 (고밀도 모드). 상세 계획은 `KATA_SANDBOX_PLAN.md` 참조.
- **rootfs 부팅 성공 (디버그 완료)**: 커스텀 `proof-agent.img` 가 Kata 런타임으로 부팅되도록 4가지 근본 원인 수정:
  1. **ext4 저널 유지**: Kata 런타임이 `rootflags=data=ordered` 를 자동 추가하는데, 저널 없는 ext4 는 `data=ordered` 모드를 지원하지 않아 `can't mount with data=, fs mounted w/o journal` 커널 패닉 발생. 저널 제거하지 않고 유지.
  2. **`kernel_params` 에 `rw` 제거**: Kata 가 디스크를 `readonly: true` 로 설정하는데 `rw` 파라미터가 충돌. `ro` (Kata 기본값) 사용. `kernel_params = "cgroup_no_v1=all systemd.unified_cgroup_hierarchy=1"` 만 지정.
  3. **`tmp.mount` 추가**: `kata-containers.target` 이 `Requires=tmp.mount` 로 의존하지만 Debian 12 slim 에는 tmp.mount 유닛이 기본 설치되지 않음. tmpfs /tmp 가 없으면 kata-agent 가 `/tmp/policy.jsonl` 에 쓰지 못해 `Failed to initialize agent policy: Read-only file system` 로 종료. `Dockerfile.rootfs` 에서 tmp.mount 유닛 파일 수동 생성.
  4. **`dbus` 패키지 설치**: kata-agent 가 cgroup 관리를 위해 D-Bus 시스템 버스에 연결해야 함. dbus 없으면 `Establishing a D-Bus connection: No such file or directory` 로 shim 실패. `Dockerfile.rootfs` 에서 `dbus` 패키지 설치 + `dbus.socket` 을 `kata-containers.target.wants` 에 등록.
- **sandbox e2e 테스트 완료**: nerdctl + Kata 런타임으로 VM 생성/명령실행/파일읽기/파일쓰기/Python실행/Node.js실행/git diff/종료 전 단계 검증. `--read-only` 플래그 정상 동작. `--security-opt seccomp=...` 는 Kata shim 의 capget 시스콜을 차단하여 사용 불가 (seccomp 는 Kata 레벨에서 `disable_guest_seccomp=false` 로 적용).
- **Phase 1: 호스트 환경 구성** (`infra/kata-host/` — 7파일):
  - `install-kata.sh`: Kata 3.31 + Cloud Hypervisor 설치, THP 비활성화 (KSM 4KB 페이지 병합률 확보), KSM 극대화 (pages_to_scan=5000), zRAM 128GB 압축 스왑, /dev/shm 160GB (기본 모드) / 75GB (고밀도 모드), disable-thp systemd 서비스.
  - `configuration-clh.toml`: 기본 모드 (150 VM, default_memory=2048MB, DAX 1GB 윈도우, virtio-mem 동적 확장 최대 8GB, cache=auto, reclaim_guest_freed_memory=true).
  - `configuration-clh-dense.toml`: 고밀도 모드 (300+ VM, default_memory=512MB, DAX 256MB 윈도우, virtio-mem 최대 4GB).
  - `containerd-config.toml`: RuntimeClass 등록 (kata-clh, kata-clh-dense).
  - `seccomp-proof-agent.json`: 시스템 파괴 시스콜 차단 (mount, init_module, pivot_root, reboot, bpf, perf_event_open 등).
  - `apparmor-proof-agent`: 위험 경로 접근 차단 (/dev/sda, /proc/kcore, /sys/firmware 등), /workspace·/tmp·/home/agent만 read-write.
  - `kata-opa-policy.rego`: Kata Agent Policy (OPA/Rego) — CreateContainer 이미지 화이트리스트, ExecProcess 명령어 블랙리스트, CLONE_NEWUSER 제한 (Layer 5 심화 보안).
- **Phase 2: 게스트 rootfs 빌드** (`infra/kata-guest/` — 5파일):
  - `Dockerfile.rootfs`: Debian 12 slim + systemd + dbus (kata-agent cgroup 관리용) + tmp.mount 유닛 (tmpfs /tmp, kata-agent 정책 초기화용) + LibreOffice/Pandoc/Poppler/Tesseract(kor/eng/jpn/chi-sim/chi-tra)/MarkItDown/PyMuPDF + FFmpeg/faster-whisper(small 모델 사전 다운로드)/pydub/librosa + ImageMagick/Ghostscript/Pillow/OpenCV/@napi-rs/canvas + Noto CJK/Nanum/Unfonts/Liberation 폰트 + Python 3.11/Node.js 20/git + 비특권 사용자 agent(UID 1000, sudo 불가). Chrome/Puppeteer 제외 (browserless 서버 공유로 ~500MB/VM 절약).
  - `build-rootfs.sh`: Docker 빌드 → rootfs 추출 → ext4 5GB 이미지 생성 → `/opt/kata/share/kata-containers/proof-agent.img` 배포.
  - `entrypoint.sh`: VM 진입점 — workspace 확인, git init, vsock 명령 수신 루프, 명령어 블랙리스트 필터링, 환경 변수 주입 제거.
  - `browserless-helper.py` / `browserless-helper.js`: a1 browserless 서버(`http://192.168.1.50:20047`) 원격 연결 헬퍼 (Python pyppeteer / Node.js puppeteer-core).
- **Phase 3: SandboxManager 코어** (`app/backend/core/sandbox/` — 6파일):
  - `manager.py`: SandboxManager — VM 생명주기 (create/execute/status/destroy), containerd CLI 호출, dense_mode 지원, 리소스 제한 (CPU/memory/timeout).
  - `workspace.py`: WorkspaceManager — 결과 파일 준비 (original/extracted/annotations/agent_output 디렉토리), Supabase Storage 다운로드, git init + .gitignore.
  - `communicator.py`: VsockCommunicator — Kata VM 과 AF_VSOCK 통신, HTTP 폴백 지원.
  - `collector.py`: ResultCollector — agent_output/extracted/annotations 파일 수집, git diff 추출, Supabase Storage 업로드.
  - `security.py`: 명령어 블랙리스트 (30+ 정규식 패턴: rm -rf /, dd of=/dev/, mkfs, mount, sysctl, insmod, reboot, fork bomb, curl|sh 등), 환경 변수 주입 제거.
- **Phase 4: FastAPI API + DB 마이그레이션**:
  - `app/backend/api/sandboxes.py`: REST API — POST/GET/DELETE /api/sandboxes, /execute, /files, /files/read, /files/write, /commit, /diff, /collect, /stats (관리자용 통계). 기존 `get_current_user` 인증 재사용, sandbox 소유자 검증.
  - `app/backend/db/migrations/026_add_sandboxes.sql`: sandboxes 테이블 생성 (id, job_id, user_id, status, vm_id, workspace_path, resource_limits JSONB, result JSONB, error, created_at, updated_at, expires_at).
  - `app/backend/db/models.py`: Sandbox SQLAlchemy 모델 추가.
  - `app/backend/main.py`: sandboxes_router 등록.
  - `app/backend/config.py`: sandbox_* 설정 10개 추가 (sandbox_enabled, sandbox_data_dir, sandbox_runtime, sandbox_runtime_dense, sandbox_image, sandbox_default_timeout, sandbox_max_concurrent, sandbox_max_concurrent_dense, sandbox_browserless_url).
- **Phase 5: Node.js AI 도구** (`app/ai-backend/src/`):
  - `tools/sandbox.ts`: 14개 도구 — create_sandbox, execute_in_sandbox, read/write/list_sandbox_files, commit_sandbox_changes, get_sandbox_diff, collect_sandbox_results, destroy_sandbox, download_file, convert_document (LibreOffice/Pandoc 자동 선택), transcribe_audio (faster-whisper), process_image (ImageMagick/Pillow — resize/convert/rotate/crop/grayscale/thumbnail), get_workspace_status.
  - `tools/browserless.ts`: 3개 도구 — browse_web (스크린샷), convert_web_to_pdf, extract_web_text. a1 browserless 서버 REST API 사용.
  - `lib/proof-api.ts`: sandbox API 메서드 10개 추가 (createSandbox, executeInSandbox, getSandboxStatus, listSandboxFiles, readSandboxFile, writeSandboxFile, commitSandboxChanges, getSandboxDiff, collectSandboxResults, destroySandbox).
  - `chat/route.ts`: sandbox + browserless 도구 통합, system prompt에 sandbox/web browsing 도구 사용 규칙 추가.
- **Phase 6: 5계층 보안 방어**:
  - Layer 1: read-only rootfs (시스템 바이너리 변경 차단).
  - Layer 2: capabilities drop (CAP_SYS_ADMIN/SYS_RAWIO/SYS_MODULE/SYS_BOOT 등 전면 제거).
  - Layer 3: seccomp 프로필 (mount, mkfs, init_module, reboot 등 시스콜 차단).
  - Layer 4: AppArmor 프로필 (/dev/sda, /proc/kcore, /sys/firmware 등 위험 경로 차단).
  - Layer 5: Kata Agent Policy OPA (이미지 화이트리스트, 명령어 블랙리스트, CLONE_NEWUSER 제한).
  - Sandbox Manager 레벨 명령어 블랙리스트 (30+ 정규식 패턴).
- **Phase 7: 프론트엔드 통합**:
  - `app/frontend/src/components/SandboxBrowser.jsx`: 신규 — workspace 파일 브라우저 (트리 뷰, 디렉토리 펼침/접힘, 파일 내용 미리보기, 새로고침).
  - `app/frontend/src/pages/JobResultPage.jsx`: sandboxId state, SandboxBrowser 패널 + 토글 버튼, AgentChatModal context에 sandboxId 전달.
  - `app/frontend/src/api.js`: sandbox API 메서드 12개 추가 (createSandbox, getSandbox, executeInSandbox, listSandboxFiles, readSandboxFile, writeSandboxFile, commitSandboxChanges, getSandboxDiff, collectSandboxResults, destroySandbox, getSandboxStats).
  - `app/frontend/src/locales/{ko,en,ja}/page.json`: sandbox i18n 키 22개 추가 (runInSandbox, sandboxStatus, fileBrowser, collectResults, stats 등).
  - `app/frontend/src/components/UploadWidget.jsx`: 파일/폴더 입력을 `<label>` + `<input ref>` 패턴으로 리팩터링 (버튼 클릭 → 숨겨진 input click 간접 트리거 제거). `jobId`/`onProgress` props 추가로 기존 Job에 파일 추가 모드 지원.
  - `app/frontend/src/api.js`: `initAddFiles`/`confirmAddFiles` 메서드 추가 (기존 Job 파일 추가 — 백엔드 엔드포인트 구현 필요).
- **Phase 8: 운영 (자동 정리 + 통계)**:
  - `app/backend/workers/tasks.py`: `cleanup_expired_sandboxes` Celery task — 만료된 sandbox 자동 종료 + 결과 수집 (sandbox_default_timeout 초과 시).
  - `app/backend/celery_app.py`: beat_schedule에 10분 간격 cleanup-expired-sandboxes 등록.
  - `app/backend/api/sandboxes.py`: `/api/sandboxes/stats` 엔드포인트 — 상태별 카운트, 디스크 사용량, 사용자별 활성 sandbox 수 (관리자용).
- **인프라 통합**:
  - `app/docker-compose.yml`: backend 서비스에 SANDBOX_* 환경변수 6개, ai-backend 서비스에 BROWSERLESS_URL/BROWSERLESS_TOKEN 추가. backend 서비스 `privileged: true` + 호스트 containerd socket/Kata 설정/nerdctl 볼륨 마운트 (Kata VM 생성/관리용). appdata volume 의 호스트 경로를 직접 마운트 (nerdctl bind mount 경로 일치).
  - `app/Dockerfile.backend`: nerdctl 바이너리 설치 (호스트 containerd socket 통해 Kata VM 생성), git/curl 추가.
  - `app/.env.example`: sandbox 환경변수 10개 + browserless 환경변수 2개 추가.
- **메모리 최적화 전략** (300+ VM 달성):
  - browserless 서버 공유 (a1, ~500MB/VM 절약).
  - virtio-mem 동적 메모리 (기본 512MB, 필요 시 4GB 확장, idle 시 회수).
  - KSM 페이지 병합 (THP 비활성화 후 4KB 단위, ~40% 절약).
  - zRAM 압축 스왑 (128GB, zstd 압축, 3:1 압축률).
  - virtio-fs DAX (host buffer cache를 guest에 직접 매핑, guest page cache 중복 제거).
  - reclaim_guest_freed_memory (게스트 해제 메모리 호스트 회수).
- **핵심 파일**: `KATA_SANDBOX_PLAN.md`, `infra/kata-host/`(7파일), `infra/kata-guest/`(5파일), `app/backend/core/sandbox/`(6파일), `app/backend/api/sandboxes.py`, `app/backend/db/migrations/026_add_sandboxes.sql`, `app/backend/workers/tasks.py`, `app/backend/celery_app.py`, `app/backend/config.py`, `app/backend/main.py`, `app/ai-backend/src/tools/sandbox.ts`, `app/ai-backend/src/tools/browserless.ts`, `app/ai-backend/src/lib/proof-api.ts`, `app/ai-backend/src/chat/route.ts`, `app/frontend/src/components/SandboxBrowser.jsx`, `app/frontend/src/pages/JobResultPage.jsx`, `app/frontend/src/api.js`, `app/frontend/src/locales/*/page.json`, `app/docker-compose.yml`, `app/.env.example`.

### AI agent 채팅 — Vercel ai-chatbot 템플릿 기반 UI 재작성 + FastAPI 리버스 프록시

- **FastAPI `/api/ai/*` 리버스 프록시** (`app/backend/main.py`, `app/backend/config.py`): Vercel AI SDK 5.x `useChat`가 `POST /api/ai/chat`으로 스트리밍 요청을 보내는데, Vite dev server proxy는 로컬 개발에서만 동작하고 프로덕션/단일 오리진 환경에서는 FastAPI가 빌드된 SPA를 서빙하므로 `POST /api/ai/chat`이 SPA catch-all GET 라우트에 걸려 **405 Method Not Allowed**를 반환하던 버그 수정. FastAPI에 `/api/ai/{path:path}` 리버스 프록시 라우트를 SPA catch-all 앞에 추가해 Node.js AI 백엔드(`ai_backend_url`, 기본값 `http://localhost:3001`)로 httpx 스트리밍 relay. hop-by-hop 헤더 제외, 모든 HTTP 메서드 지원.
- **`vite.config.js` `loadEnv` 버그 수정**: 기존 코드가 `process.env.VITE_DEV_BACKEND_URL`을 읽었으나 이는 쉘 환경변수이지 Vite env 파일의 변수가 아니어서 `.env.development`의 `VITE_DEV_BACKEND_URL`/`VITE_DEV_AI_BACKEND_URL`을 무시하고 항상 fallback 값(`192.168.1.50:28181`)을 사용하던 버그 수정. `loadEnv(mode, cwd/.., '')`로 envDir에서 env 파일을 로드.
- **Vercel ai-chatbot 템플릿 구조 포팅** (`app/frontend/src/components/ai-chat/`): shadcn/ui 의존성 없이 Tailwind + MD3 토큰으로 자체 구현. 템플릿의 컴포넌트 구조(`messages.tsx`, `message.tsx`, `ai-elements/tool.tsx`, `ai-elements/prompt-input.tsx`, `greeting.tsx`, `suggested-actions.tsx`)를 그대로 재구현.
  - **`Shimmer.jsx`**: "Thinking..." 그라데이션 스윕 애니메이션 (CSS `ai-chat-shimmer`).
  - **`Greeting.jsx`**: 빈 상태 중앙 환영 메시지 ("도와드릴까요?").
  - **`Tool.jsx`**: collapsible 도구 카드 + 상태 배지 (실행 중/완료/오류/거부). `Wrench` 아이콘 + 상태별 아이콘 + input/output JSON 토글.
  - **`Message.jsx`**: `PreviewMessage` + `ThinkingMessage`. 어시스턴트=좌측 Sparkles 아바타 + 전체 폭 콘텐츠(풍선 없음), 사용자=우측 정렬 풍선(`rounded-2xl rounded-br-md` + 그라데이션). `marked`로 마크다운 렌더링 (GFM + breaks).
  - **`Messages.jsx`**: 메시지 목록 + `useMessages` 훅(자동 스크롤, 맨 아래 감지) + scroll-to-bottom 버튼. 빈 상태면 `Greeting` 오버레이.
  - **`PromptInput.jsx`**: textarea composer (자동 높이 조정, Enter=전송/Shift+Enter=줄바꿈, 중지 버튼). `rounded-2xl` + focus shadow.
  - **`SuggestedActions.jsx`**: 컨텍스트별 제안 칩 (PDF=하이라이트/코멘트, 마크다운=글 다듬기/표 정리, 엑셀=셀 업데이트/행 추가).
- **`AgentChatModal.jsx` 재작성**: 새 `ai-chat/` 컴포넌트 조합. 헤더에 컨텍스트 표시(sourceType · activeEditor), 배경 클릭으로 닫기, system 메시지 필터링, 빈 상태 시 `SuggestedActions` 표시.
- **`AgentInputBar.jsx` 재작성**: 템플릿 composer 스타일 차용 (Sparkles 아이콘 + `rounded-2xl` + ArrowUp 버튼 + backdrop-blur).
- **`index.css` 애니메이션/스타일 추가**: `ai-chat-shimmer`, `ai-chat-fade-up`, `ai-chat-greeting`, `ai-chat-tool-open` 애니메이션 + `.ai-chat-markdown` 마크다운 렌더링 스타일 (코드 블록, 표, 인용구 등).
- **`AgentToolRenderer.jsx` deprecated**: 새 `Tool.jsx`로 대체. 더 이상 import되지 않음.
- **핵심 파일**: `app/backend/main.py`, `app/backend/config.py`, `app/frontend/vite.config.js`, `app/frontend/src/components/ai-chat/`(신규 7파일), `app/frontend/src/components/AgentChatModal.jsx`, `app/frontend/src/components/AgentInputBar.jsx`, `app/frontend/src/index.css`.

### AI agent — LangGraph → Vercel AI SDK 5.x 마이그레이션 + 채팅 버그 4종 수정

- **백엔드 마이그레이션** (`7cc6bf5`): LangGraph 기반 에이전트 런타임을 Vercel AI SDK 5.x (`ai@5.0.210`, `@ai-sdk/openai`) 기반 Node.js 백엔드(`app/ai-backend/`)로 교체. `streamText` + `tools` + `stopWhen: stepCountIs(N)` 로 단일 스트림 내 도구 루프를 처리하고, `toUIMessageStreamResponse()`로 프론트엔드에 스트리밍 응답을 전송. 도구 구현체(`tools/annotations.ts`, `tools/markdown.ts`, `tools/spreadsheet.ts`)는 Python FastAPI(`/api/v1/*`)를 호출해 기존 비즈니스 로직을 그대로 재사용.
- **ISSUE-001 — 인증 헤더 누락** (`75cffc7`): `useCompletion`/`useChat`가 `Authorization`/`X-Api-Key` 헤더를 전송하지 않아 AI 백엔드가 401을 반환하며 즉시 실패. `headers` 옵션으로 토큰/API key를 주입.
- **ISSUE-002 — `useCompletion` body 구조 오류** (`87f743a`): Novel의 `useCompletion` 패턴을 참고해 `body`에 `prompt`만 보내던 것을, Vercel AI SDK가 기대하는 `{ messages, ...options }` 형태로 수정.
- **ISSUE-003 — AgentInputBar focus로 인한 채팅 메시지 손실** (`f839280`): `AgentInputBar`가 input focus 시점에 채팅 모달을 열어 typed text가 유실되고 `AgentChatModal`이 빈 메시지를 전송하던 버그. submit 시점에 모달을 열고 `initialText`를 전달하도록 변경, `AgentChatModal`은 이미 열려 있어도 `initialText` 변경을 반영.
- **ISSUE-004 — `@ai-sdk/react` 버전 불일치** (`54f96ba`, `e449fd1`): `package.json`에 `@ai-sdk/react: ^1.0.0`(v1 API)이 고정되어 `ai@5.0.210`(v5 API)와 짝이 맞지 않아 `chat.sendMessage is not a function` 런타임 에러로 전송 버튼이 무반응. `@ai-sdk/react`를 `2.0.212`(ai-v5 dist-tag)로 업그레이드.
  - **`useAgentChat.ts` v5 API 재작성**: `sendMessage({ text })`, `parts` 기반 메시지 포맷, `transport`/`messages` 초기값 키 사용.
  - **무한 루프/브라우저 프리징 수정**: 매 렌더마다 `new DefaultChatTransport(...)`가 재생성되고 `useChat` 반환 객체가 `useCallback` deps에 들어가 스트리밍 토큰 도착 시마다 `sendContextualMessage`가 재실행 → 렌더러 CPU 100%+ 무한 루프. `transport`를 `useMemo`로 안정화하고 `sendMessage` 호출을 `ref` 기반으로 변경, 불필요한 `sendAutomaticallyWhen` 제거.
  - **`AgentToolRenderer.jsx` v5 tool part 포맷**: v1 형식(`part.toolInvocation`)을 기대하던 것을 v5 tool part(`type: "tool-${name}"`, `state`/`input`/`output`이 part에 직접 존재)로 수정.
- **핵심 파일**: `app/ai-backend/`(신규), `app/frontend/src/hooks/useAgentChat.ts`, `app/frontend/src/components/AgentChatModal.jsx`, `app/frontend/src/components/AgentInputBar.jsx`, `app/frontend/src/components/AgentToolRenderer.jsx`, `app/frontend/src/components/AiMenu.jsx`, `app/frontend/package.json`.

### AI agent 개발/검증 및 프론트엔드 연동

- **개발 환경 mock 모드 해제**: 로컬 백엔드의 `/api/dev/login` bypass가 405로 실패하면 프론트엔드가 mock 사용자로 전환되었는데, 이제는 API key 인증으로 백엔드와 직접 통신한다. `AuthContext.jsx`가 dev 모드에서 세션 대신 mock 사용자를 유지하면서 `api.js`가 `X-Api-Key` 헤더를 전송, `backend/api/auth.py`의 `get_current_user`가 `x-api-key` 헤더를 수락한다. `DevBypassBanner.jsx`도 API key 상태를 반영하도록 갱신.
- **API key 인증을 job 엔드포인트로 확장**: 기존 `/api/v1/agent/*`와 `/api/auth/me`만 API key를 지원했으나, `/api/jobs/*` 엔드포인트에도 `get_current_user_or_api_key` dependency를 추가해 웹 포털 세션과 API key를 모두 허용. 이로 인해 dev API key로 결과 페이지(`JobResultPage`)와 PDF 주석 UI를 확인할 수 있다.
- **HITL editor agent 검증**: `/api/v1/agent/run`으로 `editor` 그래프를 실행, `ask_user` 호출 시 `AgentRun`이 `interrupted` 상태로 전환되고 `AgentApprovalModal`이 표시됨을 확인. `/api/v1/agent/resume/{run_id}`로 사용자 승인 값을 전달하면 실행이 재개되어 `final_markdown`이 에디터에 반영된다.
- **Annotator agent end-to-end API 테스트**: `test_annotator.py` 스크립트로 테스트 PDF를 업로드하고 `AgentRun`을 직접 실행, `search_text` → `add_highlight` → `finish` 도구 체인이 동작하고 `final_annotations`에 highlight 항목이 생성되는 것을 확인.
- **PDF 주석 UI 버그 수정**:
  - `AnnotationListPanel.jsx`: EmbedPDF가 반환하는 numeric annotation type(예: `9` = highlight)에서 `(ann.type || "").toLowerCase()`가 `TypeError`를 내는 문제를 수정. 숫자형 type을 highlight/freetext로 매핑하고 `intent`도 함께 확인.
  - `JobResultPage.jsx`: AI 주석 생성(`startAnnotate` / `startAnnotateEdit`) 시 `i18n.language`를 참조했지만 `useTranslation()`에서 `i18n`을 destructuring 하지 않아 `i18n is not defined` 오류가 발생했던 버그를 수정.
- **개발 환경 UX 개선**: `api.js`의 `previewJob`이 dev 모드에서 브라우저/프록시 캐시로 인해 오래된 400 응답이 재사용되는 것을 방지하기 위해 `_t` 캐시 버스팅 파라미터를 추가. 임시 `/editor-test` 라우트는 제거.
- **핵심 파일**: `app/backend/api/auth.py`, `app/backend/api/jobs.py`, `app/frontend/src/AuthContext.jsx`, `app/frontend/src/api.js`, `app/frontend/src/components/DevBypassBanner.jsx`, `app/frontend/src/components/AnnotationListPanel.jsx`, `app/frontend/src/pages/JobResultPage.jsx`, `app/frontend/src/components/SourcePanel.jsx`, `app/backend/tests/test_agent_graph.py`, `test_annotator.py`.

### AI 주석 — 페이지 범위 지정 + 주석 편집 패널

- **페이지 범위 지정**: AI 주석 생성 시 처리할 페이지를 지정할 수 있다. FAB 다이얼로그의 "고급 옵션" 토글을 펼치면 페이지 범위 입력 필드가 표시되며, `"1-5,7,10-12"` 형태로 입력한다. 빈 값이면 **현재 보고 있는 페이지만** 처리 (기본값). 이전에는 항상 전체 페이지를 처리해 LLM 프롬프트가 `MAX_ELEMENTS_FOR_LLM=400`으로 잘려 뒷부분 페이지의 요소가 무시되는 문제가 있었다.
- **`_parse_page_range()` 헬퍼** (`api/jobs.py`): `"1-5,7,10-12"` 문자열을 1-based 페이지 번호 리스트로 변환. 역순 범위(`5-3`) 허용, `total_pages` 초과 시 클램프, 빈 입력 → None(전체 페이지 의미).
- **과금 변경**: 지정한 페이지 수만큼만 과금 (`units = page_range_count`). 관리자는 무제한. `annotated_pdf_files` entry에 `page_range` 저장하여 재시도/중복 검사에 사용.
- **백엔드 필터링** (`pdf_annotate_converter.py:run()`): `page_range`가 None이 아니면 `image_paths`와 `elements`를 지정 페이지로 필터링. Vision LLM 경로와 텍스트 LLM 경로 모두에 적용. `tasks.py:annotate_pdf_job()` 시그니처에 `page_range` 파라미터 추가.
- **사용자 편집 AI 주석 보존**: 같은 `annotation_index`로 AI 주석을 재생성해도 사용자가 편집한 주석을 덮어쓰지 않도록 보존. `_merge_annotations_for_run()`이 `_userEdited: true` 플래그가 있는 주석은 제거하지 않고 유지. `save_user_annotations()`가 export된 주석과 기존 JSON을 비교해 사용자가 AI 주석의 색상/코멘트/위치/투명도를 변경했는지 감지 (`_is_annotation_edited()`), 변경 시 `_mark_user_edited()`로 플래그 설정. 사용자가 삭제한 AI 주석은 export에 없으므로 자동 제외.
- **주석 편집 패널** (`AnnotationListPanel.jsx`): PDF 뷰어 우측 상단 List 아이콘 버튼으로 토글. 주석을 페이지별로 그룹화해 리스트 표시. 항목 클릭 시 해당 페이지로 스크롤 + 주석 선택. 확장 시 색상(8색 컬러피커)/코멘트(textarea)/투명도(range slider) 편집 UI + 삭제 버튼. 변경 시 기존 `onAnnotationChanged` debounce 자동 저장 경로 재사용.
- **PdfViewer ref API 확장**: `getAnnotations()`, `selectAnnotation(pageIndex, id)`, `updateAnnotation(pageIndex, id, patch)`, `deleteAnnotation(pageIndex, id)`, `scrollToPage(pageNumber)` 노출. embedpdf annotation plugin의 메서드를 래핑.
- **i18n 키 추가** (ko/en/ja `page.json`): `annotateAdvancedOptions`, `annotatePageRangeLabel`, `annotatePageRangePlaceholder`, `annotatePageRangeHint`, `annotationListTitle`, `annotationListEmpty`, `annotationPage`, `annotationTypeHighlight`, `annotationTypeCallout`, `annotationNoText`, `annotationEditColor`, `annotationEditComment`, `annotationEditOpacity`, `annotationDelete`.
- **핵심 파일**: `api/jobs.py`, `workers/tasks.py`, `core/pdf_annotate_converter.py`, `api.js`, `PdfViewer.jsx`, `SourcePanel.jsx`, `AnnotationListPanel.jsx`, `JobResultPage.jsx`.

### AI 주석 — Callout (FreeTextCallout)

- **여백 주석 → callout 전환**: 기존 `margin_note`/`both` 모드는 페이지 우측에 mediabox를 확장해 FREETEXT 박스를 배치했으나, JSON 오버레이 방식 전환 후 mediabox 확장이 빠져 여백 박스가 페이지 밖에 떠 있어 보이지 않는 버그가 있었다. 이를 embedpdf의 `FreeTextCallout`(텍스트 박스 + 화살표 리더 라인)로 대체 — 페이지 내 빈 모서리/외곽 여백에 텍스트 박스를 배치하고 화살표로 원본 요소를 가리킨다.
- **`build_embedpdf_annotations()` 시그니처 변경**: 새 파라미터 `page_elements_bboxes: dict[int, list[tuple]]` 추가 (1-based page_no → PDF user-space bbox 목록). callout 텍스트 박스 배치 시 기존 OCR 요소와의 충돌 회피에 사용.
- **callout 배치 알고리즘** (`pdf_annotator.py:_find_free_callout_slot()`): 페이지 4모서리 + 4외곽 여백 중심 후보 영역 중 기존 요소/대상/같은 페이지 선행 callout 박스와 충돌하지 않는 가장 가까운 빈 영역 선택. 전부 충돌하면 최소 겹침 후보로 폴백.
- **calloutLine 계산** (`_compute_callout_line()`): `[arrowTip, knee, connectionPoint]` 3점으로 L자 리더 라인 생성. arrowTip은 대상 가장자리 중점, knee는 꺾임점, connectionPoint는 텍스트 박스 가장자리 중점(embedpdf `computeCalloutConnectionPoint` 로직과 동일). knee가 텍스트 박스 내부에 있으면 2점 직선 callout으로 폴백.
- **EmbedPDF 호환 필드**: callout 주석에 `intent: "FreeTextCallout"`, `calloutLine`, `rectangleDifferences`(PDF /RD), `lineEnding: 4`(OpenArrow), `strokeColor`, `strokeWidth` 추가. `importAnnotations()`/`exportAnnotations()` round-trip 지원.
- **코드 정리**: `annotate_pdf()`, `_extend_mediabox_for_visual_margins()`, `_layout_margin_notes()`, `_apply_target()` 및 관련 상수(`MARGIN_WIDTH_PT` 등) 제거 — 더 이상 PDF에 주석을 구워 넣거나 mediabox를 확장하지 않음.
- **converter 연동**: `pdf_annotate_converter.py`에서 `elements`의 `bbox_px`를 PDF user-space로 변환해 `page_elements_bboxes`를 빌드하고 `build_embedpdf_annotations()`에 전달. 고급주석(Vision LLM) 경로에서는 `elements`가 비어 충돌 검사 없이 모서리에 배치.
- **테스트 파일**: `test_annotate_compare.py`를 `build_embedpdf_annotations` 기반으로 업데이트 — PDF + annotations JSON을 분리 저장.
- **핵심 파일**: `pdf_annotator.py`, `pdf_annotate_converter.py`, `test_annotate_compare.py`.

### 브랜딩 (로고)

- **공식 로고 적용**: `proof-logo.png`(가로형, 16:9)를 앱 전반의 공식 로고로 사용. 원본(800×450, 77KB)을 400×225(32KB)로 리사이즈하여 `app/frontend/public/proof-logo.png`에 배치 — Vite가 루트 경로(`/proof-logo.png`)로 서빙.
- **재사용 가능한 Logo 컴포넌트**: `app/frontend/src/components/Logo.jsx` — `height`, `toHome`(Link 래핑 토글), `className` 등의 prop 제공. 모든 주요 브랜드 노출 위치에서 재사용.
- **적용 위치**:
  - 랜딩페이지(`UploadPage.jsx`) 네비게이션: 54px
  - 작업 확인 페이지(`JobConfirmPage.jsx`) 네비게이션: 54px
  - 사이드바(`SidebarLayout.jsx`): 펼침 48px, 접힘 42px
- **Favicon**: `app/frontend/index.html`에 `<link rel="icon">` 및 `apple-touch-icon` 추가.
- **원본 백업**: `proof-logo.original.png`를 루트에 보관(public 밖이므로 서빙되지 않음).
- **회사 로고(teamcat)**: `teamcat-logo.png`(정사각형, 64×64, 6KB)를 `app/frontend/public/`에 배치. `GlobalFooter.jsx`의 copyright 텍스트(`© 2026 TeamCat`) 앞에 18×18px로 작게 표시.
- **PoetryProgress guard clause**: `app/frontend/src/components/PoetryProgress.jsx`에서 `poems[slideIdx]`가 undefined일 때 `.title` 접근으로 발생하던 `TypeError` 수정 — `if (!poem) return null;` 추가 (i18n 로딩 중 빈 배열일 때 크래시 방지).
- **tasks.py import 경로 수정**: `app/backend/workers/tasks.py`의 `_build_and_upload_searchable_pdf()`와 `_image_to_searchable_pdf()`에서 `from .core.*`을 `from ..core.*`로 수정 (workers 패키지 내부에서 core로의 상대 임포트 경로 오류).

### Searchable PDF (텍스트 레이어)

- **업로드 시점 텍스트 레이어 생성**: PaddleOCR이 반환한 `overall_ocr_res`의 `rec_texts`/`rec_boxes`를 사용해 원본 PDF/이미지에 투명 텍스트 레이어를 추가. `app/backend/core/pdf_text_layer.py`의 `add_text_layer_from_ocr()`가 핵심.
- **원본 미리보기 대체**: `app/backend/api/jobs.py:_source_files()`와 `_build_source_file_item()`에서 원본 PDF/이미지의 `preview_url`을 `searchable_pdf_storage_path`로 대체. 다운로드용 `url`은 원본 유지.
- **DB 메타데이터**: `Job` 테이블에 `searchable_pdf_storage_path` 컬럼 추가. 단일 PDF 업로드는 Job 컬럼 사용, 멀티파일 이미지는 `extracted_files` JSONB에 `searchable_pdf_storage_path` 필드 추가.
- **AI 주석 최적화**: `app/backend/core/pdf_annotate_converter.py`에서 `job.searchable_pdf_storage_path`가 있으면 OCR을 생략하고, `_collect_page_elements_from_searchable_pdf()`로 텍스트 레이어에서 `elements`를 추출. `TextLayerSearcher`로 직접 bbox 검색.
- **좌표 보정**: `pdf_annotator.py`와 `pdf_user_annotator.py`의 `_rect_to_embedpdf_rect()`/`_fitz_rect_to_embedpdf_rect()`에 `page.rect.x0`을 고려해 CropBox/MediaBox가 있는 PDF에서도 정확히 정렬.
- **핵심 파일**: `pdf_text_layer.py`, `pipeline_vision.py`, `workers/tasks.py`, `api/jobs.py`, `pdf_annotate_converter.py`, `db/models.py`.

### AI 주석 (PDF Annotation)

- **비동기/원자적 인덱스**: 주석 생성 요청마다 고유 인덱스를 원자적으로 할당해 파일 덮어쓰기 및 동시 생성 충돌 방지.
- **JSON 오버레이 단일 진실원**: 주석을 PDF에 구워 넣지 않고 embedpdf `AnnotationTransferItem[]` JSON 오버레이로만 표시. `pdf_annotate_converter.run()`은 깨끗한 보정 이미지 PDF를 표시 기반으로 업로드하고 `build_embedpdf_annotations()`로 JSON을 생성. 하이라이트는 `HIGHLIGHT`, 코멘트는 `FreeTextCallout`(텍스트 박스 + 화살표 리더 라인)로 생성 — 페이지 내 빈 모서리/외곽 여백에 배치. flatten 다운로드는 embedpdf snippet 자체의 다운로드 UI가 처리.
- **원본 내장 주석 중복 방지**: 원본 PDF에 이미 내장된 하이라이트/코멘트 주석이 있으면, embedpdf가 이를 자동으로 렌더링하고 `exportAnnotations()`에 포함해 `user_annotations.json`이 반복 저장되면서 중복 증식하는 문제를 방지. `api/jobs.py:_source_files()`에서 원본 PDF의 내장 주석을 PyMuPDF로 추출하여 `user_annotations.json` 초기값으로 저장하고, 주석이 제거된 `clean.pdf`를 별도 Storage 경로(`{job_id}/clean.pdf`)에 업로드해 원본 대신 표시. `pdf_user_annotator.py`에 `extract_pdf_annotations()`와 `remove_pdf_annotations()` 추가.
- **좌표 변환**: `_rect_to_embedpdf_rect()`가 PDF user-space(원점 좌하단, y↑)를 embedpdf device-space(원점 좌상단, y↓)로 변환할 때 `origin.y = page_height - y1`로 y축 flip. embedpdf가 annotation `rect.origin.y`를 CSS `top`으로 직접 렌더링하므로 flip이 필수.
- **JSONB 변경 감지**: `annotated_pdf_files`는 SQLAlchemy JSONB 컬럼이며, dict/list를 직접 변경한 뒤 재할당해도 SQLAlchemy가 변경을 감지하지 못하는 경우가 있으므로, 해당 컬럼을 수정하는 모든 경로(`pdf_annotate_converter.py`, `api/jobs.py`)에서 `flag_modified(job, "annotated_pdf_files")`를 호출해야 한다. 이를 누락하면 주석 생성이 완료되어도 DB entry 상태가 `processing`으로 남는다.
- **자동 저장**: 원본 패널에서 사용자가 그린 주석을 자동 저장하며, 무한 파일 증식 및 404 깜빡임 문제를 방지.
- **AI 주석 생성**: PDF 패널 하단 중앙 플로팅 FAB으로 AI 주석 생성 트리거 이동; Vision LLM이 mode/comment_mode를 동적으로 결정.
- **실패 처리**: AI 주석 생성이 실패(`status === "error"`)하거나 처리 중(`status === "processing"`)인 파일의 파일탭(좌측 다중 파일 목록)에 재시도/취소 버튼 표시; `SourcePanel.jsx`에서 `onRetryAnnotation` / `onDeleteFile` 콜백으로 `JobResultPage`와 연결.
- **버그 수정**: 병렬 AI 주석 생성 중에도 `converting` 상태로 FAB이 비활성화되지 않던 문제 수정.

### 마크다운 에디터

- **자동 저장**: 결과 페이지 마크다운 에디터에 1초 debounce 자동 저장 적용; `lastMarkdownRef` 동기화로 피드백 및 콘텐츠 중복/리셋 문제 해결.
- **AI 텍스트 생성**: Tiptap 에디터에 Novel의 `ai/react` `useCompletion` 패턴을 참고한 AI 텍스트 생성 기능 추가.
  - **백엔드**: `POST /api/v1/ai/generate` 스트리밍 엔드포인트 (`app/backend/api/v1/ai.py`), `app/backend/core/ai_client.py`에서 OpenAI-compatible vLLM/llama.cpp endpoint로 스트리밍 요청.
  - **LLM**: 기존 `default_llm_endpoint` (Gemma-4 26B vLLM) 재사용; `app/backend/core/llm_utils.py`로 `chat_template_kwargs.enable_thinking=true`와 `thinking_token_budget=256` 공통 처리.
  - **프론트**: `app/frontend/src/components/AiMenu.jsx` — Improve, Fix grammar, Make shorter, Make longer, Continue writing, Custom command (zap) 기능 제공.
  - **UX**: 텍스트 선택 시 Tiptap `BubbleMenu`로 AI 메뉴를 표시하고, 툴바에도 AI 버튼을 유지; 선택하지 않은 상태에서도 버튼이 활성화되어 AI 기능을 바로 인지할 수 있도록 수정.
  - **i18n**: `page:components.ai.*` 번역 키를 `ko/page.json`, `en/page.json`, `ja/page.json`에 추가.
- **UX 개선**: AI 버튼이 `editable` prop 누락으로 렌더링되지 않던 문제 수정; 번역 키(namespace) 불일치로 키가 그대로 노출되던 문제 수정.

### 엑셀 베이직

- **자동 저장**: 1초 debounce 자동 저장 추가.
- **UI 정리**: 베이직 탭에서 다운로드/초기화 버튼이 포함된 툴바 제거.
- **안정성**: `handleAutoSave` 사용 순서로 인한 TDZ(Temporal Dead Zone) 에러 수정.

### 개발 환경

- **로컬 프론트엔드 개선**: a1 백엔드/Supabase 연결을 위한 `app/.env.development.example` 및 `scripts/dev-tunnel.sh` 보강.

## Tech Stack

- **Backend**: FastAPI + SQLAlchemy + Celery + Redis
- **Frontend**: React + Vite + Tailwind CSS + react-i18next (en/ko/ja)
- **Storage**: Supabase Storage (PDFs, inputs, results)
- **Database**: PostgreSQL via Supabase (`supabase-chungu-db`)
- **LLM Inference (Images/PDF)**: vLLM proxy (`192.168.1.69:18080`) — round-robin load balancer to two Gemma-4 26B A4B AWQ 4bit instances (`18000` on GPU 1/2, `18001` on GPU 0/3); proxy auto-rewrites the request `model` name to the actual model loaded on the chosen backend
- **LLM Inference (Audio/Video/Images)**: llama.cpp (`192.168.1.82:18080`) — Gemma-4 12B GGUF Q4_K_M, 4 parallel slots
- **Deployment**: Docker Compose on `a1` (local server), exposed via Cloudflare Tunnel at `proof.teamcat.app`

## Directory Structure

```
app/
  backend/          FastAPI app, workers, DB models, API endpoints
    api/v1/         Public API v1 (jobs, account, keys)
    auth/           JWT auth, API key auth
    core/           OCR pipeline, media loader, rate limit
      docling_client.py           Docling 서비스 클라이언트
      paddleocr_client.py         PaddleOCR 클라이언트
      paddleocr_fallback.py       PaddleOCR 폴백 제어 (회로 차단기)
      paddleocr_parameter_recommender.py  Vision LLM 샘플 기반 파라미터 추천
      pdf_annotate_converter.py   PDF 하이라이트/여백 주석 오케스트레이터
      pdf_annotator.py            PDF 주석 적용
      pdf_coords.py               좌표 변환
      ocr_layout.py               OCR 레이아웃 파싱
      xlsx_advanced_converter.py  마크다운에서 고급 XLSX 변환
      pipeline_docling.py         Docling 파이프라인
      pipeline_vision.py          Vision 파이프라인
      pipeline_media.py           Media 파이프라인
      pipeline_hybrid.py          Hybrid 파이프라인 (사용하지 않음)
    db/             SQLAlchemy models and migrations
    workers/        Celery tasks
    docling_service/ Docling 서비스 (별도 Docker 컨테이너)
  frontend/         React SPA
    src/locales/   i18n translation files (en/ko/ja × common/page)
    src/i18n.js     i18next configuration
    src/LanguageContext.jsx  Language provider with Supabase persistence
  docs/              Docusaurus documentation site (API docs, AI prompts)
    docs/            Markdown content (en: source of truth)
    i18n/ko/         Korean translations
    i18n/ja/         Japanese translations
    static/img/      PROOF logo & favicon SVGs
    docusaurus.config.js
    build/           Generated static site (gitignored)
  Dockerfile.backend
  docker-compose.yml
  .env.example
infra/
  mailu/            Mailu mail server deployment
ocr_output/         OCR output artifacts (ignored in git)
*.py                Standalone scripts and test helpers
```

## Environment Setup

Copy `app/.env.example` to `app/.env` and fill in:

- `DATABASE_URL`
- `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SERVICE_ROLE_KEY`
- `REDIS_URL`
- `DEFAULT_LLM_ENDPOINT`, `DEFAULT_LLM_MODEL` (vLLM for images/PDF)
- `MEDIA_LLM_ENDPOINT`, `MEDIA_LLM_MODEL` (llama.cpp for audio/video + image share)
- `PUBLIC_BASE_URL` (external URL for download links)
- `SUPABASE_URL` (internal), `SUPABASE_PUBLIC_URL` (external proxied URL)
- `JWT_SECRET_KEY` (for Supabase token verification)
- `ADMIN_EMAIL`, `ADMIN_PASSWORD_HASH`
- Turnstile: `TURNSTILE_SITE_KEY`, `TURNSTILE_WORKER_URL`, `VITE_TURNSTILE_SITE_KEY`, `VITE_TURNSTILE_WORKER_URL`
- Toss/Paddle keys for payments
- PaddleOCR: `PADDLEOCR_SERVICE_URL`, `PADDLEOCR_API_TOKEN`, `PADDLEOCR_API_URL`, `PADDLEOCR_FALLBACK_ENABLED`
- Docling: `DOCLING_ENABLED`, `DOCLING_SERVICE_URL`, `DOCLING_REFINEMENT_ENABLED`

## Local Development

### Full Local Stack (backend + frontend + worker)

```bash
cd app
# Backend
cd backend
pip install -r requirements.txt
uvicorn backend.main:app --reload --port 28181

# Frontend
cd ../frontend
npm install
npm run dev

# Worker
cd ../backend
celery -A backend.celery_app.celery worker --loglevel=info

# Docs (Docusaurus)
cd ../docs
npm install
npm run build        # outputs to docs/build/
npm run start        # dev server at localhost:3000
```

### Local Frontend with a1 Backend/Supabase

a1 서버에서 백엔드/워커/Supabase가 이미 실행 중일 때, 로컬 머신에서 프론트엔드만 띄워 개발할 수 있습니다. Vite dev server의 `/api`, `/supabase` 프록시를 a1로 전달합니다.

#### 1. 환경변수 설정

`app/.env.development.example`을 `app/.env.development`로 복사하고 값을 채웁니다.

```bash
cp app/.env.development.example app/.env.development
```

핵심 변수:

- `VITE_DEV_BACKEND_URL`: a1 백엔드 주소
  - 내부망 직접 연결: `http://192.168.1.50:28181`
  - SSH 터널링 사용: `http://localhost:28181`
- `VITE_SUPABASE_ANON_KEY`: a1 Supabase anon key
- `VITE_TURNSTILE_SITE_KEY` / `VITE_TURNSTILE_WORKER_URL`: CAPTCHA 사용 시 (비워두면 미사용)

#### 2. 직접 연결 (내부망)

```bash
cd app/frontend
npm install
npm run dev
```

`http://localhost:5173`에서 프론트엔드가 실행되며, API/Supabase 요청은 `VITE_DEV_BACKEND_URL`로 프록시됩니다.

#### 3. SSH 터널링 (내부망에 접근 불가하거나 원격 개발 시)

```bash
# LAN 우선, 실패 시 WAN으로 시도
./scripts/dev-tunnel.sh

# 터미널을 하나 더 열어
VITE_DEV_BACKEND_URL=http://localhost:28181 npm run dev
```

스크립트는 a1의 `28181`(backend)과 `28000`(Supabase) 포트를 로컬로 포워드합니다. SSH 키는 `~/Documents/ssh-key-backup/`에서 자동 감지하며, 필요하면 `SSH_KEY` 환경변수로 직접 지정할 수 있습니다. WAN 주소는 `A1_WAN_HOST` 환경변수로 설정합니다.

#### 4. 인증 방식

- **Dev bypass 자동 로그인** (기본): a1 `.env`에 `DEV_BYPASS_AUTH=true`가 설정되어 있으면, `npm run dev` 실행 시 `/api/dev/login`으로 자동 로그인됩니다. 화면 상단에 파란색 배너가 표시됩니다. **프로덕션 a1에서는 절대 활성화하지 마세요.**
  - `DEV_BYPASS_EMAIL` / `DEV_BYPASS_PASSWORD`로 설정된 계정을 실제 Supabase Auth에 로그인하여 세션을 발급합니다. local DB에도 동일 사용자가 있어야 업로드 및 job 생성 등 모든 기능이 정상 동작합니다.
  - `DEV_BYPASS_AUTH_EMAIL` / `DEV_BYPASS_AUTH_PASSWORD`는 사용하지 않습니다. (config.py의 필드명은 `dev_bypass_email` / `dev_bypass_password`이며, Pydantic은 `DEV_BYPASS_EMAIL` / `DEV_BYPASS_PASSWORD` 환경변수를 매핑합니다.)
- **실제 Supabase Auth**: a1 `.env`에 `DEV_BYPASS_AUTH=false`이면 정상적인 회원가입/로그인을 사용합니다. Turnstile이 활성화되어 있으면 CAPTCHA도 필요합니다.
- **Mock 모드**: a1에 연결할 수 없거나 bypass가 비활성화되면 자동으로 mock 사용자로 전환됩니다. 화면 상단에 노란색 배너가 표시됩니다. 이는 UI 레이아웃 점검용이며 실제 데이터 흐름은 테스트하지 않습니다.

#### 5. TUS 업로드 개발 주의

a1 Supabase의 `SUPABASE_PUBLIC_URL`이 `https://proof.teamcat.app/supabase`로 설정되어 있으면, TUS 업로드 중 Supabase가 반환하는 `Location` 헤더가 외부 도메인을 가리킬 수 있습니다. `app/frontend/src/tusUpload.js`는 개발 모드에서 이 URL을 자동으로 `window.location.origin/supabase`로 재작성하여 로컬 개발이 원활하도록 합니다.

## LLM Routing & Load Balancing

- **Audio/Video**: E4B (llama.cpp, `192.168.1.82:18080`) — **현재 서버 다운, 비활성화**
- **PDF routing** (임시 정책 — vLLM/Docling 서버 개선 전까지):
  - **기본변환** (`ocr_model == "basic"`): `has_pdf_text_layer()` → True면 Docling, False면 `run_vision`(PaddleOCR 우선)
  - **고급변환** (`ocr_model == "premium"`): 무조건 `run_vision` — 모든 페이지 PaddleOCR 우선, 실패 시 vLLM fallback
  - **이미지 파일**: `run_media` → PaddleOCR 우선 (`is_fallback_preferred() == True`)
  - 라우팅 분기 순서: `tasks.py`에서 `ocr_model == "basic" and has_pdf_text_layer()` → True면 Docling, 그 외 PDF는 `run_vision`
  - `run_vision` 내에서 개별 페이지 텍스트 레이어 검사 없음 — 모든 페이지 동일하게 PaddleOCR 우선 처리
- **PDF pages (pipeline=vision)**: rendered to PNG by PyMuPDF and sent page-by-page to the vLLM proxy (`192.168.1.69:18080`). The proxy round-robins between two Gemma-4 26B A4B AWQ 4bit instances (`18000` on GPU 1/2, `18001` on GPU 0/3). `run_vision`은 항상 vLLM endpoint로 라우팅 (E4B media endpoint 라우팅 제거됨).
- **Mixed media batches** (images/audio/video): `pipeline_media.py:_resolve()`에서 동적 라우팅 — E4B 서버 다운 시 media_endpoint 없이 vLLM만 사용
- Routing logic in `pipeline_media.py:_resolve()` and `pipeline_vision.py:resolve_endpoint()`
- E4B has 4 parallel slots (`--parallel 4`) — **현재 다운, 비활성화**
- vLLM is optimized for high-batch throughput
- Celery worker concurrency: 8 (prefork)
- Thread limits per job: `llm_max_workers=64` (vLLM), `media_max_workers=8` (E4B), `ocr_max_workers=8` (Tesseract), `docling_max_workers=16` (Docling)
- `max_pages=10000` per file (configurable via settings_store)

## PaddleOCR Fallback System

- **회로 차단기 (Circuit Breaker) 패턴**: `paddleocr_fallback.py`에서 Redis 기반 상태 관리, Redis 불가 시 in-memory fallback
- **상태 전환**: 1분 내 3회 이상 실패 시 OPEN → 600초 후 HALF_OPEN → 성공 시 CLOSED 복귀
- **임시 정책**: `is_fallback_preferred()`가 항상 `True`를 반환하여 PaddleOCR을 우선 사용 (vLLM/Docling 서버 개선 전까지)
- **폴백 제어**: `fallback_controller.can_use_fallback()`로 폴백 가능 여부 판단, `consume_fallback()`로 사용 기록
- **설정 옵션**:
  - `paddleocr_fallback_enabled`: 폴백 시스템 활성화/비활성화
  - `paddleocr_fallback_failure_threshold`: 회로 차단기 임계값 (기본값 3)
  - `paddleocr_fallback_open_seconds`: OPEN 상태 지속 시간 (기본값 600초)
- **Key files**: `app/backend/core/paddleocr_fallback.py`, `app/backend/core/paddleocr_client.py`, `app/backend/core/paddleocr_parameter_recommender.py`

## XLSX Advanced Converter

- **기능 개요**: 마크다운 결과에서 고급 XLSX 변환 — 페이지별 표 정리/재구성 후 통합 XLSX 저장
- **처리 흐름**:
  1. 원본 job 마크다운 로드 (편집된 마크다운 우선)
  2. `<!-- 페이지 N -->` 마커 기준 페이지 분할
  3. 첫 페이지에서 컬럼 구조 추출 (Vision LLM 또는 텍스트 LLM)
  4. 페이지별 표 정리/재구성 (컬럼 구조 기반)
  5. openpyxl로 XLSX 통합 저장 (스타일 적용)
  6. 원래 job 업데이트 (결과 파일 경로, 상태)
- **컬럼 추출**: Vision LLM (`call_vision`) 우선, 실패 시 텍스트 LLM (`call_text`) 폴백
- **스타일링**: openpyxl로 헤더 폰트, 정렬, 배경색 적용
- **오류 처리**: 실패 시 job 상태를 `error`로 변경하고 `refundable=True` 설정
- **Key files**: `app/backend/core/xlsx_advanced_converter.py`

## Large Image Tiling (Whiteboard/Planner)

- PDF pages for the vision pipeline are rendered to PNG by PyMuPDF (`ocr_client.render_pdf()`) using multi-threaded page rendering (16 workers), replacing the previous single-threaded `pdftoppm` path.
- High-resolution images (whiteboards, planners, posters) that exceed Gemma 4's vision encoder pixel limit (~2.58M pixels, ~1606x1606) are automatically split into overlapping tiles.
- Tiling logic in `ocr_client.py:tile_large_image()` — 15% overlap between tiles to avoid cutting text/tables at boundaries.
- `pipeline_media.py:_process_file()` calls `tile_large_image()` for each image; if tiling is needed, each tile is sent to the LLM separately and results are concatenated with `\n\n`.
- Images within the pixel limit are processed as-is (no tiling overhead).
- Tiles are generated in left-to-right, top-to-bottom reading order.
- No additional billing: tiling is an internal processing detail; the user is charged per original image, not per tile.
- Key files: `app/backend/core/ocr_client.py` (`tile_large_image`, `fit_image_to_gemma4_resolution`), `app/backend/core/pipeline_media.py` (`_process_file`).

## Docling Service

- **기능 개요**: Docling 전처리 서비스 (a1 CPU 서버) — PDF/이미지/HWP를 마크다운으로 변환, 선택적 LLM 후처리
- **서비스 URL**: `http://docling:28182` (Docker compose 내부 서비스 이름)
- **동적 타임아웃**: 파일 크기(MB) 기반 최소 24시간, `max(86400, file_size_mb * 60)` 초
- **Health check**: `/health` 엔드포인트로 서비스 상태 확인
- **폴링**: 30초 간격으로 `/convert/async` 결과 폴링, `processing` + health OK 시 타임아웃 연장
- **LLM Refinement**: Docling 마크다운를 LLM에 전송해 후처리 (선택적)
  - 최대 20개 이미지를 LLM에 전송 (`docling_max_images_per_doc`)
  - 이미지 최대 긴 변 1920px (`docling_image_max_size`)
  - `build_docling_refinement_prompt`로 프롬프트 생성
- **OCR 백엔드 선택**: `ocr_backend` 설정으로 `docling` 또는 `paddleocr` 선택
- **설정 옵션**:
  - `docling_enabled`: Docling 서비스 활성화/비활성화
  - `docling_service_url`: Docling 서비스 URL
  - `docling_refinement_enabled`: LLM 후처리 기본 활성화
  - `docling_max_images_per_doc`: 문서당 LLM 전송 이미지 상한
  - `docling_image_max_size`: 추출 이미지 최대 긴 변 (px)
- **Key files**: `app/backend/core/docling_client.py`, `app/backend/core/pipeline_docling.py`

## Supabase Proxy

- FastAPI reverse proxy at `/supabase/*` routes to internal Supabase (`192.168.1.50:28000`)
- Frontend uses `window.location.origin + '/supabase'` as Supabase URL (no hardcoded IPs)
- Signed download URLs are rewritten from internal to external proxied URLs in `supabase_client.py`
- Proxy implementation: `app/backend/api/supabase_proxy.py`

## Public URL & Email Confirmation

- All externally visible URLs must use the public domain (`https://proof.teamcat.app`), never internal IPs.
- `app/backend/config.py` defaults `public_base_url` to `https://proof.teamcat.app` and `supabase_public_url` to `https://proof.teamcat.app/supabase` so that missing `.env` values do not leak internal addresses.
- In `app/.env` (and on the server):
  - `PUBLIC_BASE_URL=https://proof.teamcat.app` (used by `email_sender.py` for download links)
  - `SUPABASE_PUBLIC_URL=https://proof.teamcat.app/supabase` (used by `supabase_client.py` to rewrite signed Storage URLs)
- For self-hosted Supabase (`/opt/supabase-chungu/.env` on `a1`):
  - `SITE_URL=https://proof.teamcat.app`
  - `ADDITIONAL_REDIRECT_URLS=https://proof.teamcat.app/**`
  - `MAILER_URLPATHS_CONFIRMATION="/supabase/auth/v1/verify"`
  - `MAILER_URLPATHS_INVITE="/supabase/auth/v1/verify"`
  - `MAILER_URLPATHS_RECOVERY="/supabase/auth/v1/verify"`
  - `MAILER_URLPATHS_EMAIL_CHANGE="/supabase/auth/v1/verify"`
- With this setup, Supabase Auth emails generate links like `https://proof.teamcat.app/supabase/auth/v1/verify?token=...&type=signup`, which are proxied by FastAPI's `/supabase/*` route to the internal Supabase Auth service (`192.168.1.50:28000`).
- Internal IPs (`192.168.1.x`, `localhost`, `127.0.0.1`) are reserved for backend-only services: LLM endpoints, Docling service, and the internal `SUPABASE_URL`.

## Email System

### Supabase Auth Emails (English Fixed)

- GoTrue는 단일 템플릿만 지원하므로 인증 메일은 **영어 고정**.
- 템플릿 파일: `/opt/supabase-chungu/volumes/templates/confirmation.html` (서버)
- docker-compose.yml에 `GOTRUE_MAILER_TEMPLATES_CONFIRMATION`, `GOTRUE_MAILER_SUBJECTS_CONFIRMATION` 환경변수 및 volume 마운트 추가.
- 회원가입 시 프론트엔드(`AuthPage.jsx`)에서 스팸 폴더 확인 안내 표시 (`signupSuccessTitle`, `signupSuccessBody`, `signupSpamNotice` i18n 키).

### App Emails (Multi-language: ko/en/ja)

- **완료 메일** (`build_done_email`): 사용자 프로필 언어에 따라 결과 페이지 링크(`/jobs/{jobId}`) 포함.
- **실패 메일** (`build_error_email`): 사용자 프로필 언어에 따라 에러 내용 통지.
- 언어 조회: `tasks.py`에서 `job.user_id` → `User.language` 조회 후 `lang` 파라미터로 전달. 비회원(`user_id == None`)은 기본값 `"en"`.
- 다운로드 링크: `/api/dl/{token}?type=docx` — auth 없이 `download_token`으로 302 redirect (이메일 버튼용). DOCX 파일이 아직 생성되지 않은 경우 on-demand 변환(`_generate_office_on_demand`) 후 redirect.
- XLSX 다운로드는 이메일에서 제외: 결과 페이지(`/jobs/{jobId}`)에서 인증 후 다운로드 가능.
- Key files:
  - `app/backend/email_sender.py` — `_DONE_T`, `_ERROR_T` 다국어 딕셔너리, `build_done_email`, `build_error_email`
  - `app/backend/workers/tasks.py` — `_handle_job_failure`, `run_job` Step 7에서 언어 조회 후 이메일 발송
  - `app/backend/api/jobs.py` — `/api/dl/{token}` redirect 엔드포인트

## Model Selection UI

- `JobConfirmPage.jsx`에서 OCR 엔진 선택 및 고급 옵션 UI 제거 — "기본 모델"과 "고급 모델" 두 가지 선택지만 제공.
- 기본 모델: 대량의 스캔된 PDF에 최적화된 빠른 OCR 및 데이터 변환 (1P/페이지, 매일 100페이지 무료).
- 고급 모델: high performance AI 비전 모델 (모든 페이지 정밀 분석, 비전 AI 에이전트 교차 검증 복원, 오디오/비디오/이미지 변환 지원, 5P/페이지).
- 오디오/비디오 파일이 포함된 경우 기본 모델 비활성화, 고급 모델 강제.
- i18n 키: `basicFeature1-3`, `premiumFeature1-3` (ko/en/ja).

## Price & Payment Page

- **PricePage** (`app/frontend/src/pages/PricePage.jsx`): 카드형 디자인으로 파일 형식(MD, CSV, XLSX, DOCX)과 모델(기본/고급)을 아이콘과 함께 표시.
  - 파일 형식 카드: 고정 너비, `flex-wrap` 배치, PowerPoint 제외.
  - 모델 카드: 기능 목록 중앙 정렬, 고급 모델에 "추천" 배지.
  - 크레딧 구매 카드: 단가($1.00/credit), 최소 충전액($5.00), 예시 금액 표시.
  - i18n 키: `creditTitle`, `creditDesc`, `creditProduct`, `creditUnitPrice`, `creditMinimum`, `creditExamples`, `mostPopular` (ko/en/ja).
- **PaymentPage** (`app/frontend/src/pages/PaymentPage.jsx`): 충전 금액 입력 위에 단가/최소 금액 안내 추가. 결제 동의 안내는 크레딧 충전 카드 내부 오른쪽에 배치. 환불 안내 문구에 `/refund-policy` 링크 추가.
- **세금 안내**: `taxNotice` i18n 키를 "세금은 결제 시 별도로 계산되어 추가될 수 있습니다"로 변경 (ko/en/ja).

## Global Footer

- **GlobalFooter** (`app/frontend/src/components/GlobalFooter.jsx`): 모든 페이지에서 공통으로 사용하는 글로벌 푸터 컴포넌트. 저작권, 서비스 이용약관, 개인정보처리방침, 환불 정책, API 문서, 관리자 링크 포함.
- 푸터가 있는 페이지: UploadPage, PricePage, PaymentPage, OnPremisePage, LegalTermsPage, LegalPrivacyPage, LegalRefundPage, SidebarLayout 사용 페이지 (Dashboard, Developer, Jobs, Settings).
- 푸터가 없는 페이지 (의도적): AuthPage, AdminLogin, AdminDashboard, JobConfirmPage, JobResultPage.
- UploadPage는 기존 인라인 푸터를 `GlobalFooter` 컴포넌트로 교체.

## Logout Fix

- `SidebarLayout.jsx`: `signOut()` 후 `navigate("/")`로 랜딩 페이지 이동. (기존 `signOut()`만 호출하면 `onAuthStateChange`로 인한 재렌더링이 `DashboardPage`의 `!user && !error` 로딩 조건을 만족시켜 무한 스피너가 표시됨)
- `DashboardPage.jsx`: 로딩 조건을 `if (authLoading)`로 단순화 — 로그아웃 후 `user == null`일 때 무한 로딩 스피너 방지.

## Cloudflare Turnstile CAPTCHA

- 백엔드에서 Worker를 통해 Turnstile 토큰을 검증. secret key는 Cloudflare Worker secret(`TURNSTILE_SECRET_KEY`)으로만 보관하고, 애플리케이션 서버에는 저장하지 않음.
- Worker URL: `https://turnstile-siteverify-proof.mtgmtg.workers.dev`
- Widget site key: `0x4AAAAAADux9LO13vEhA4F7`
- 프론트엔드는 Turnstile 위젯으로 토큰만 수집하고, Worker 직접 검증은 하지 않음. **Turnstile 토큰은 1회용**이므로 프론트엔드와 백엔드에서 이중 검증하면 두 번째 검증이 실패함.
- Supabase JS 클라이언트는 `turnstile_token` 대신 `options.captchaToken`을 받아 요청 본문의 `gotrue_meta_security.captcha_token`으로 전송. 백엔드 `supabase_proxy.py`는 이 필드를 추출하여 Worker로 검증.
- 로그인/회원가입/관리자 로그인 시 백엔드가 토큰을 검증. 실패 시 `403` 응답과 `"bot 확인에 실패했습니다. 다시 시도하세요."` 메시지 반환.
- Widget 도메인: `localhost`, `127.0.0.1`, `proof.teamcat.app`
- Key files:
  - `app/backend/core/turnstile.py` — Worker 경유 토큰 검증
  - `app/backend/api/supabase_proxy.py` — `/supabase/auth/v1/token` 요청 시 Turnstile 검증
  - `app/backend/api/admin.py` — 관리자 로그인 Turnstile 검증
  - `app/frontend/src/pages/AuthPage.jsx` — Turnstile 위젯, 토큰 수집
  - `app/frontend/src/pages/AdminLogin.jsx` — Turnstile 위젯, 토큰 수집
  - `app/backend/config.py` — `turnstile_site_key`, `turnstile_worker_url` 설정
  - `app/.env.example` — 환경변수 예시
  - `app/Dockerfile.backend` — `VITE_TURNSTILE_SITE_KEY`, `VITE_TURNSTILE_WORKER_URL` build args
  - `app/docker-compose.yml` — build args 전달

## PDF Viewer & Markdown Editor Optimization

- **PdfViewer** (`app/frontend/src/components/PdfViewer.jsx`):
  - 브라우저 네이티브 PDF 뷰어를 `<iframe src="{pdf_url}#page={page}" />`로 표시한다. Chrome PDFium, Safari PDFKit 등 브라우저의 네이티브 엔진이 렌더링하므로 100페이지 이상 대용량 PDF도 빠르게 표시된다.
  - 툴바에서 이전/다음 페이지, 페이지 번호 직접 입력으로 이동할 수 있다. 입력한 페이지 번호는 `#page` URL 프래그먼트로 iframe에 전달된다.
  - Markdown 미리보기와의 동기화는 **툴바로 페이지 이동할 때만** `onPageChange` 콜백을 통해 이루어진다. iframe 내부에서 사용자가 스크롤하거나 네이티브 뷰어의 페이지 컨트롤을 사용하면 부모에게 이벤트가 전달되지 않아 양방향 동기화는 불가능하다.
  - PDF.js, 캔버스 렌더링, 썸네일 패널은 사용하지 않는다.
- **Preview Backend Optimization** (`app/backend/core/pdf_preview_converter.py`, `app/backend/api/jobs.py`, `app/backend/core/supabase_client.py`):
  - DOCX/HWP 미리보기 PDF를 생성할 때 PyMuPDF로 `linear=True` 선형화를 적용하여 브라우저가 첫 페이지 바이트만 받아도 렌더링할 수 있게 한다.
  - 10MB 이상 또는 50페이지 이상인 PDF/DOCX/HWP에 대해 `preview_pdfs_lowres/` 아래에 100 DPI 저해상도 미리보기 PDF를 별도 생성한다. 용량은 줄지만 텍스트 레이어는 사라진다.
  - 저화질/선형화 생성 중 오류가 발생하면 원본 PDF의 서명 URL로 폴백하여 프리뷰 패널이 blank 되지 않도록 한다.
  - `/api/jobs/{id}/preview` 응답을 Redis에 `preview:{job_id}:{start_page}:{end_page}` 키로 5분 TTL 캐싱한다. `save_result_markdown` / `save_result_page`에서 `preview:{job_id}:*` 패턴으로 캐시를 무효화한다.
  - `_source_files()`에서 `concurrent.futures.ThreadPoolExecutor(max_workers=3)`로 여러 파일의 signed URL 생성을 병렬화한다. 스레드당 `create_fresh_service_client()`로 새로운 Supabase 클라이언트를 생성하여 스레드 안전을 확보한다.
- **MarkdownPreview** (`app/frontend/src/components/MarkdownPreview.jsx`):
  - 읽기 전용 마크다운 뷰어. `marked.parse`로 HTML 렌더링 후 `dangerouslySetInnerHTML` 사용 (백엔드 신뢰 출력, DOMPurify 미사용).
  - `<!-- 페이지 N -->` 마커 기준으로 마크다운을 페이지 섹션으로 분할.
  - `content-visibility: auto` + `containIntrinsicHeight`로 화면 외 섹션 렌더링 스킵 (가상화).
  - `IntersectionObserver`로 가시 페이지 추적.
  - `scrollToPage(pageNum)` imperative API로 PDF 페이지 이동 시 해당 섹션으로 스무스 스크롤.
  - `React.memo` 적용.
  - **방어 로직**: 첫 페이지는 초기부터 `visible`로 설정, `markdown` 변경 시 `visiblePages` 초기화. 페이지 수가 10개 이하일 때는 `content-visibility` 가상화를 비활성화하여 브라우저별 렌더링 차이/blank 현상을 방지.
- **SimpleEditor** (`app/frontend/src/components/SimpleEditor.jsx`):
  - Tiptap 기반 편집 가능 마크다운 에디터.
  - `PageMarkerNode` 커스텀 Tiptap 노드: `<!-- 페이지 N -->` 마커를 `div[data-page-marker]`로 변환하여 ProseMirror 스키마에 등록. 기본 스키마에 없는 div가 `setContent` 시 제거되는 문제 해결.
  - `turndown` 규칙: 저장 시 `div[data-page-marker]`를 다시 `<!-- 페이지 N -->` 마커로 역변환 (round-trip 보존).
  - `scrollToPage(pageNum)` imperative API로 PDF 페이지 이동 시 해당 마커로 스크롤.
  - `React.memo` 적용.
- **PagedResultViewer** (`app/frontend/src/components/PagedResultViewer.jsx`):
  - 100페이지 초과 작업용 페이지별 뷰어. `api.previewJob(jobId, pageNum, pageNum)`으로 단일 페이지 로드.
  - 보기 모드(`MarkdownPreview`)와 편집 모드(`SimpleEditor`) 토글 지원. **기본 모드는 편집 모드**.
  - `React.memo` 적용.
- **JobResultPage** (`app/frontend/src/pages/JobResultPage.jsx`):
  - `editMode` state로 보기/편집 모드 전환. **초기값은 `true`로 편집 모드로 진입**. 보기 모드: `MarkdownPreview`, 편집 모드: `SimpleEditor`.
  - `currentPdfPage` 변경 시 에디터/프리뷰에 `scrollToPage` 호출하여 원본-결과 동기 스크롤.
  - `loadPreview()`에서 `preview.last_page > PAGE_THRESHOLD` 폴백 체크: DB의 `total_pages`가 잘못되어도 마크다운의 실제 페이지 수로 페이징 모드 전환.
  - `loadPreview()` **대형 작업 최적화**: `needsPagedMode(job)`(100페이지 초과)로 미리 판단된 작업은 전체 마크다운을 받아오지 않고 `api.previewJob(jobId, 1, 1)`로 첫 페이지 메타/소스 정보만 획득. 이후 `PagedResultViewer`가 페이지별로 개별 로드하여 300페이지 이상 문서에서 스켈레톤 화면이 멈추는 문제를 방지.
  - `autoSaveMarkdown()`는 `pages.length > 0`으로 페이징 모드 판단하여 PagedResultViewer에 flush를 위임하고, 단일/다중 파일 마크다운은 API로 자동 저장 (DB 값 의존 제거). 수동 저장 버튼은 제거.
  - **Markdown Auto-save**:
    - `SimpleEditor`에서 Tiptap `update` 이벤트를 감지, 1.5초 debounce 후 `onChange` 콜백으로 변경된 마크다운을 상위에 전달. `lastMarkdownRef`로 `setContent`에 의한 중복 저장을 방지.
    - `JobResultPage`는 `SimpleEditor`의 `onChange`를 `autoSaveMarkdown(updated)`에 연결. 저장 완료 시 `autoSaveMessage`로 "자동 저장됨"을 표시.
    - `PagedResultViewer`는 현재 페이지의 `SimpleEditor`에 `onChange`를 연결하여 페이지별로 자동 저장. 언마운트/페이지 전환 시 `pendingMarkdownRef`에 남은 변경분을 flush.
    - 파일 선택 전환, MD 다운로드, Office/Excel 변환, 고급 Excel 변환 시작 전에 `autoSaveMarkdown()`으로 pending 변경분을 먼저 서버에 저장.
    - i18n 키: `autoSaved` (ko: "자동 저장됨", en: "Auto-saved", ja: "自動保存しました").
  - `MarkdownViewToolbar`로 보기/편집 토글 UI 제공.
  - i18n 키: `editMode`, `viewMode`, `edit`, `view` (ko/en/ja).
  - **방어 로직**: 다중 파일 작업에서 `source_files[i].result_markdown`이 비어 있을 경우 전체 결합 마크다운로 폴백하여 빈 화면 방지.
- **total_pages 보정** (`app/backend/workers/tasks.py`):
  - 워커 처리 후 `total_pages`를 `len(page_tables)`로 덮어쓰지 않고 `max(job.total_pages, len(page_tables))`로 업로드 시점 페이지 수 보존. 빈 페이지로 인해 `total_pages`가 감소하는 것 방지.
  - 멀티미디어/이미지 작업 완료 후 `total_pages`/`done_pages` 설정 추가 (기존에는 0으로 유지됨).
- **CSS** (`app/frontend/src/index.css`):
  - `.markdown-page-section`: 페이지 섹션 구분선 스타일.
  - `.page-marker`: Tiptap 페이지 마커 div (`pointer-events: none`).
- 페이지 마커 형식: `<!-- 페이지 N -->` (백엔드 `converter.build_layout_markdown_string()`에서 생성).

## Deployment

Docker 이미지 빌드는 **a1 서버에서 수행**한다. 로컬에서 Docker 빌드를 하지 않는다.

```bash
bash deploy_a1.sh
```

이 스크립트는 다음을 수행한다:

1. LAN(a1) 또는 WAN(wan-1)으로 SSH 연결
2. `rsync`로 로컬 `app/` 디렉토리를 서버 `~/chungu-app/`에 동기화 (`.env` 제외)
3. 서버에서 `docker compose down && docker compose up --build -d` 실행 (이미지 빌드 + 컨테이너 재시작)
4. 컨테이너 상태 확인

서버 `.env`는 rsync로 덮어쓰지 않으므로 수동으로 관리해야 한다.
DB 마이그레이션 SQL 파일은 배포 후 서버에서 수동으로 적용한다 (실제 DB 컨테이너명은 `supabase-chungu-db`, DB명은 `postgres`):

```bash
cat app/backend/db/migrations/020_add_pdf_annotate_fields.sql | ssh a1 'docker exec -i supabase-chungu-db psql -U postgres -d postgres'
```

## Storage Retention & Source Cleanup

- OCR 원본 업로드 파일은 `Job.created_at` 기준 **48시간** 후 Supabase Storage `pdfs` 버킷에서 자동 삭제된다.
- 변환 결과 파일(`results` 버킷)은 별도 보관 정책을 유지하며, 원본 삭제와 무관하게 다운로드 가능하다.
- DB의 `jobs` 레코드는 유지되며, 삭제 후 `pdf_storage_path` 및 `extracted_files` 내 `storage_path` 참조만 제거된다.
- 삭제 스케줄링: Celery beat가 1시간마다 `cleanup_expired_uploads` 태스크를 실행한다.
- 사용자가 수동으로 작업을 삭제하면 DB 레코드 삭제 전에 `pdfs` 버킷 원본 파일도 함께 삭제된다.
- jobs 리스트에는 `source_expires_at`를 기준으로 남은 시간(일/시간/분)이 표시된다.
- Key files:
  - `app/backend/api/jobs.py` — `_source_expires_at()`, `delete_job` Storage 정리
  - `app/backend/core/supabase_client.py` — `delete_source_files()`, `clear_source_paths()`
  - `app/backend/workers/tasks.py` — `cleanup_expired_uploads` periodic task
  - `app/backend/celery_app.py` — Celery beat schedule
  - `app/frontend/src/pages/JobsPage.jsx` — 남은 시간 표시
  - `app/docker-compose.yml` — `beat` 서비스

## Docling Service Details

- **서버 환경**: Xeon Scalable CPU 서버 (a1 GPU 아님), CPU PyTorch + Intel Extension for PyTorch (IPEX) for VNNI/OneDNN acceleration
- **OCR 엔진 선택**: `OCR_ENGINE=tesseract` (기본값) 또는 `OCR_ENGINE=easyocr` 설정. `OCR_LANG=ko+en+ja`로 Tesseract 언어 팩 제어
- **Tesseract 5.5.1**: Xeon 6230 듀얼 소켓 속도 최적화. `ppa:alex-p/tesseract-ocr5` PPA 사용. 컨테이너 내 `tesseract -v`로 `Found AVX512VNNI`, `Found AVX512F`, `Found AVX2`, `Found OpenMP` 확인
- **EasyOCR**: 회전/노이즈 스캔에 더 좋지만 느림. Tesseract는 깨끗한 deskewed 스캔에 최적
- **HWP/HWPX 지원**: `run_hwp`가 pyhwp의 `hwp5odt`로 ODT 변환 → LibreOffice headless로 DOCX 변환 → Docling 서비스 전송. pyhwp2md/hwp5odt가 일부 다중 페이지 HWP 파일의 첫 페이지만 추출하는 문제 회피. LibreOffice 또는 Docling 실패 시 기존 pyhwp 기반 변환기로 폴백
- **Threading**: `torch.set_num_threads(2)` (요청당 2 스레드), `AcceleratorOptions(num_threads=80)` (총 80 스레드 = Xeon 6230 듀얼 소켓에서 40 동시 요청). OpenVINO `INFERENCE_NUM_THREADS=2`
- **Celery worker concurrency**: 16 (prefork)
- **Backend `docling_max_workers`**: 16 동시 Docling 요청
- **NUMA binding**: 컨테이너 시작 시 `numactl --cpunodebind=0 --membind=0` 사용. 듀얼 소켓 6230의 경우 최대 처리량을 위해 각 NUMA 노드에 바인딩된 두 개의 독립 worker 실행
- **Model quantization** (`_apply_ipex` warm-up 후 적용):
  - **RTDetrV2 (layout)**: OpenVINO NNCF INT8 quantization with `torch.jit.trace` → `ov.convert_model` → `nncf.quantize`. 디스크 캐시 `/data/ov_cache/`. `INFERENCE_NUM_THREADS=2`로 컴파일
- **Key files**:
  - `app/backend/docling_service/main.py` — CPU accelerator, model quantization, IPEX warm-up이 있는 FastAPI 서비스
  - `app/backend/docling_service/Dockerfile` — Ubuntu 22.04 + CPU PyTorch + IPEX + Tesseract language packs
  - `app/backend/docling_service/requirements.txt` — Docling/FastAPI deps (torch GPU 없음). `openvino>=2024.0` 및 `nncf>=3.0` 포함
  - `app/backend/docling_service/benchmark_ocr.py` — EasyOCR vs Tesseract A/B benchmark 도구
  - `app/docker-compose.docling.yml` — GPU 예약 없는 Compose
  - `app/backend/core/docling_client.py` — Docling 서비스용 a1 backend 클라이언트
  - `app/backend/core/pipeline_docling.py` — Docling markdown + 선택적 LLM refinement
  - `app/backend/core/hwp_converter.py` — pyhwp 기반 HWP/HWPX text/image/page extraction
  - **EfficientViT (detection)**: `torch.quantization.quantize_dynamic` (Linear INT8). OpenVINO conversion hangs due to dynamic control flow in forward.
  - **TableModel04_rs (table structure)**: `torch.quantization.quantize_dynamic` (Linear INT8). Discovered via `table_model.tf_predictor._model`.
  - **OCR model**: kept in FP32 to preserve recognition quality.
- `torch.autocast` patched to CPU float32 to avoid slow bfloat16 emulation on CPU.
- Batch sizes: Docling defaults (no custom env vars).
- Refinement costs: `cost_per_docling_refinement_page_krw` / `cost_per_docling_refinement_page_usd` in `settings_store`.
- Docs: `app/docs/docs/docling.md` and `app/docs/docs/hwp.md` (HWP Phase 2).

## PaddleOCR Fallback (AI Studio API)

- PaddleOCR AI Studio API (`https://paddleocr.aistudio-app.com/api/v2/ocr/jobs`)를 폴백 OCR 백엔드로 사용한다.
- AI Studio API는 **이미지 파일만** 지원한다 (png/jpg/bmp/tiff/webp). PDF, 오피스 문서, HWP/HWPX는 직접 전송하지 않는다.
- 폴백 대상:
  - **Vision 파이프라인** (`pipeline_vision.py`): PDF 페이지를 PNG로 렌더링 후, 모든 페이지를 PaddleOCR 우선 처리. 개별 페이지 텍스트 레이어 검사 없음.
  - **Media 파이프라인** (`pipeline_media.py`): 이미지 파일만 폴백 (비디오/오디오 제외).
  - **Docling 파이프라인** (`pipeline_docling.py`): 폴백 안 함 (이미지가 아닌 문서).
- 폴백 우선 조건 (`paddleocr_fallback.py:is_fallback_preferred()`):
  - `paddleocr_fallback_enabled == True`이면 항상 `True` 반환 — 모든 변환 요청이 PaddleOCR을 우선 사용 (임시 정책)
- 회로 차단기 (Circuit Breaker):
  - 60초 내 3회 실패 → OPEN (600초)
  - OPEN 경과 후 → HALF_OPEN → 성공 시 CLOSED 복귀
  - `can_use_fallback()`: fallback_enabled AND 회로 차단기가 OPEN이 아님
  - 한도 은행(Limit Bank) 시스템은 제거됨 — 사용량 제한 없음
- `paddleocr_service/main.py`의 `/api/convert` 엔드포인트는 이미지 확장자만 허용하며, AI Studio API에 비동기 job을 제출하고 폴링으로 결과를 수신한다.
- PaddleOCR 결과에 포함된 이미지는 **base64 data URI**로 markdown에 직접 삽입된다 (컨테이너 내부 경로 의존성 제거, 프론트엔드에서 직접 표시 가능).
- `paddleocr_client.py`는 `convert_file()` (docling_client 호환 시그니처) 및 `convert_image()` (경량 이미지 전용) 함수를 제공한다.
- Key files:
  - `app/backend/core/paddleocr_fallback.py` — 회로 차단기 + `is_fallback_preferred()`
  - `app/backend/core/paddleocr_client.py` — AI Studio API 클라이언트 (이미지 확장자 체크)
  - `app/backend/paddleocr_service/main.py` — AI Studio API 프록시 서비스 (`/api/convert`)
  - `app/backend/paddleocr_service/Dockerfile` — AI Studio API 프록시용 컨테이너
  - `app/backend/core/pipeline_vision.py` — PaddleOCR 우선 + vLLM fallback
  - `app/backend/core/pipeline_media.py` — 이미지 전용 폴백
  - `app/backend/core/ocr_client.py` — `has_pdf_text_layer()` PDF 텍스트 레이어 검사
  - `app/backend/workers/tasks.py` — PDF 라우팅 분기 (기본변환: 텍스트 레이어 → Docling / 스캔 → run_vision / 고급변환: 무조건 run_vision)
- Docker Compose: `paddleocr_service` 서비스 정의, worker/beat에 `PADDLEOCR_SERVICE_URL` 환경변수 전달.
- 환경변수: `PADDLEOCR_API_TOKEN`, `PADDLEOCR_API_URL`, `PADDLEOCR_SERVICE_URL`, `PADDLEOCR_FALLBACK_ENABLED`, `PADDLEOCR_FALLBACK_FAILURE_THRESHOLD`, `PADDLEOCR_FALLBACK_OPEN_SECONDS` 등.

## PaddleOCR Auto Parameter Recommendation

- 사용자가 기술 용어를 몰라도, 업로드된 문서의 샘플 페이지를 Vision LLM이 보고 PaddleOCR-VL 최적 파라미터를 자동으로 결정한다.
- 샘플링: PDF/오피스 문서의 전체 페이지 수 기준 `ceil(total_pages × 0.01)` 장, **최소 1장, 최대 3장**.
  - 1장일 때는 중간 페이지, 2장일 때는 첫/마지막 페이지, 3장일 때는 첫/중간/마지막 페이지를 선택하여 문서 전체 구조를 대표한다.
- Vision LLM은 문서 유형(receipt/invoice/form/paper/table_heavy/image_heavy/business_card/report/mixed)을 판단하고, 아래 파라미터를 JSON으로 추천한다:
  - `layout_threshold`, `layout_merge_bboxes_mode` (`large`/`small`/`union`), `layout_unclip_ratio`, `layout_nms`
  - `use_doc_orientation_classify`, `use_doc_unwarping`, `use_layout_detection`, `use_ocr_for_image_block`, `format_block_content`
  - `use_chart_recognition`, `use_seal_recognition`
- 추천값은 범위를 벗어나면 clamping되고, JSON 파싱/추천 실패 시 `mixed` 문서 유형 프리셋으로 안전하게 fallback한다.
- 적용 범위:
  - `paddleocr_service/main.py`의 로컬 PaddleOCRVL 파이프라인 (`predict()`에 동적 파라미터 전달)
  - AI Studio API 폴백 (`/api/convert`)의 `optionalPayload`에 동일 파라미터를 camelCase로 변환하여 전달
- 설정 옵션:
  - `paddleocr_auto_parameter_enabled`: 자동 파라미터 추천 활성화/비활성화
  - `paddleocr_sample_dpi`: 샘플링 DPI (기본값 150)
  - `paddleocr_sample_max_tokens`: 샘플링 최대 토큰 (기본값 2000)
- Key files: `app/backend/core/paddleocr_parameter_recommender.py`
- 환경변수:
  - `PADDLEOCR_AUTO_PARAMETER_ENABLED=true` — 자동 추천 On/Off
  - `PADDLEOCR_SAMPLE_DPI=150` — 샘플 페이지 렌더링 해상도 (비용 절감)
  - `PADDLEOCR_SAMPLE_MAX_TOKENS=2000` — 추천 LLM 응답 길이 제한
- Key files:
  - `app/backend/core/paddleocr_parameter_recommender.py` — 샘플 추출, LLM 추천, 파라미터 검증/프리셋
  - `app/backend/core/prompts.py` — `build_paddleocr_parameter_recommendation_prompt()`
  - `app/backend/paddleocr_service/main.py` — `_get_paddleocr_params()`, `_run_paddleocr()`, AI Studio API payload 변환
  - `app/backend/paddleocr_service/Dockerfile`, `Dockerfile.pipeline` — `Pillow`/`ImageMagick` 및 `backend/core/*` 복사

## PDF Highlight & Margin Annotation (하이라이트/여백 주석)

- **기능 개요**: 원본 PDF/이미지에서 자연어 조건(예: "80만원 이상 이체된 줄", "사람 이름이 있는 부분")에 맞는 텍스트 요소를 찾아 **형광펜 하이라이트**와/또는 **여백 코멘트 주석**을 추가해 다운로드할 수 있는 기능. 변호사 등 법률 실무에서 스캔 문서를 그대로 제출용으로 표시해야 하는 요구에서 시작됨.
- **주석 대상**: 표의 행(table_row)뿐 아니라 제목/단락/각주/도장 내 글자 등 모든 텍스트 블록(text)이 주석 대상이 된다. PaddleOCR-VL의 `parsing_res_list`에서 `block_label`이 `table`인 블록은 행 단위로, 그 외 텍스트가 포함된 블록(`text`/`title`/`figure_title`/`seal` 등)은 블록 전체를 하나의 요소로 취급한다. `image`/`figure` 등 텍스트가 없는 블록은 제외.
- **이미지 파일 지원**: 원본 PDF가 없는 경우(zip 속 이미지 파일 등), 이미지들을 PyMuPDF로 PDF로 변환한 후 주석을 적용한다. `_images_to_pdf()`가 각 이미지를 RENDER_DPI 기준 포인트 크기의 페이지로 삽입해 단일 PDF를 생성한다. 이미지 파일은 주석 생성 직전에 `pdfs` 버킷에 개별 업로드되어야 하며, `supabase_client.upload_image()`가 담당한다.
- **이미지 전처리 (보정)**: OCR bbox와 주석 PDF의 좌표를 정확히 맞추기 위해 이미지 페이지를 보정한다.
  1. `image_deskew.deskew_image()`로 미세 기울기(수평에서 몇 도 벗어난 스캔/사진)를 보정한다. `deskew>=1.5.0` 패키지를 사용하며, |각도| < 0.5°면 보정을 생략한다.
  2. PaddleOCR-VL(AI Studio)의 `doc_preprocessor_res.angle` 코드(0/1/2/3)를 기반으로 90°/180°/270° 단위 대회전을 `_rotate_image_90()`로 적용한다. AI Studio의 `useDocOrientationClassify` 결과를 클라이언트 측에서 재현하는 것이다.
  3. 보정이 완료된 이미지를 기준으로 bbox를 수집하고, 동일한 보정 이미지로 주석 PDF를 생성한다. 원본 PDF 벡터 정보는 포기하고 시각적 정확도를 우선한다.
- **처리 흐름**:
  1. `_get_page_image_paths()`로 원본 PDF/이미지에서 페이지 이미지 확보 (PDF는 DPI 200 재렌더링, 이미지는 `pdfs` 버킷에서 다운로드)
  2. `deskew_image()` + `_rotate_image_90()`로 페이지 이미지 보정
  3. PaddleOCR-VL(AI Studio 유료 API, 현재 사용 중)로 페이지별 bbox 원본(layout) 확보
  4. 모든 텍스트 요소(표 행 + 텍스트 블록)를 텍스트로만 LLM(vLLM Gemma-4)에 전달해 조건에 맞는 요소 선택 (좌표 추론은 LLM에 절대 맡기지 않음 — grounding 신뢰도가 낮다는 리서치 결과 반영)
  5. 선택된 요소의 bbox를 PDF 좌표로 변환
  6. 깨끗한 보정 이미지 PDF를 Storage에 업로드 (주석을 PDF에 구워 넣지 않음)
  7. `build_embedpdf_annotations()`로 EmbedPDF `AnnotationTransferItem[]` JSON 생성 후 Storage에 업로드
  8. 프론트 `PdfViewer`가 JSON을 `importAnnotations()`로 오버레이; flatten 다운로드는 embedpdf snippet 자체 다운로드 UI가 처리
- **사용자 인터페이스**: 결과 페이지(JobResultPage)의 "AI 주석" 버튼 → 지시문 입력(예: "출금금액이 1000만원 이상인 거래 행", "사람 이름이 있는 부분") + 표시방식(`highlight`/`margin_note`/`both`) + 여백 코멘트 방식(`user_text`/`llm_summary`) 선택 → Celery 비동기 처리 (xlsx_advanced와 동일한 구독 사용량 예약/재시도 패턴)
- **PaddleOCR-VL 1.6 실제 원본 스키마** (a1 프로덕션에서 실측, 사전 조사했던 PP-StructureV3 계열 `table_res_list`/`cell_box_list` 스키마와는 다름에 주의):
  - `{"width": px, "height": px, "layout_det_res": {...}, "parsing_res_list": [{"block_label": "table"|"text"|"title"|"seal"|..., "block_content": "<table>...</table>" (표는 HTML 문자열), "block_bbox": [xmin,ymin,xmax,ymax], ...}]}`
  - 표는 **블록 전체 bbox만 있고 행/셀 단위 bbox가 없다** — `core/ocr_layout.py`가 `block_content`의 HTML을 `lxml`로 파싱하고, `block_bbox`를 `<tr>` 개수만큼 세로로 균등 분할해 각 행의 근사 bbox를 만든다.
  - 텍스트 블록은 `block_bbox`를 그대로 사용한다 (블록 전체가 하나의 주석 대상).
  - AI Studio API(`layoutParsingResults[].prunedResult`)와 로컬 PaddleOCR-VL 파이프라인(`res.json`)은 `input_path`/`page_index` 차이만 있고 스키마가 동일하므로, 로컬 서버로 전환해도 `core/ocr_layout.py`는 수정할 필요가 없다 — `core/paddleocr_client.py`의 `convert_image_with_layout()` 내부 호출 엔드포인트만 교체하면 됨.
- **PDF 좌표 변환 시 주의 (실측으로 발견한 함정들)**:
  - `use_doc_orientation_classify`/`use_doc_unwarping`이 켜지면 bbox가 "보정된 이미지" 기준으로 나와 원본 좌표와 어긋난다 — AI Studio 잡 제출 시(`_aistudio_submit_job`) 항상 `False`로 고정 전송.
  - `/Rotate 90/180/270`이 걸린 PDF는 OCR bbox(시각적/렌더링 좌표)와 PyMuPDF 주석 API가 기대하는 좌표계가 다르다 — `page.derotation_matrix`로 변환 필요.
  - PyMuPDF의 주석/텍스트 삽입 좌표는 **PDF 절대좌표가 아니라 "현재 mediabox의 좌상단(x0,y0)을 원점으로 하는 로컬 좌표"**다. PaddleOCR-VL 1.6의 원점도 좌상단이며, **우측/하단 여백을 늘리면 x0/y0가 이동하지 않아 보정이 불필요**하다. 좌측/상단 여백을 늘리면 x0/y0가 이동해 기존 좌표가 어긋나므로, 본 기능은 우측/하단 여백만 추가한다. 기본적으로는 우측에만 여백을 추가하고, 주석 박스가 페이지 하단을 넘어 겹칠 경우에만 하단을 필요한 만큼 늘린다 (원점 이동 보정 로직은 제거됨).
  - **mediabox 원점 보존 (실측으로 발견한 함정)**: `page.rect`는 PyMuPDF가 **y0를 항상 0으로 정규화**한 시각적 사각형이다. 원본 mediabox가 `(0, 50, 400, 350)`처럼 y0≠0인 페이지에서 `page.rect` 기반으로 새 mediabox를 계산하면 y0가 0으로 덮어씌워져 **페이지 콘텐츠 전체가 위로 밀려 잘못된 위쪽 여백**이 생긴다. 따라서 여백 확장은 `page.rect`가 아닌 **원본 `page.mediabox`를 직접 확장**해야 한다 (`_extend_mediabox_for_visual_margins()`). 회전된 페이지(90/180/270)에서는 시각적 우측/하단이 raw mediabox의 어느 변에 해당하는지 회전 각도에 따라 계산한다.
  - 텍스트 레이어 없는 스캔본에서 `add_highlight_annot()`에 raw bbox를 넣으면 MuPDF가 사각형이 아닌 타원형 브러시로 그린다 — `add_rect_annot()`(Square 주석) + 반투명 채우기로 대체.
  - 여백은 **기본적으로 우측에만** 추가한다. 주석 박스가 많아져 페이지 하단을 넘어 겹치게 되면, 하단도 필요한 만큼 늘린다. PaddleOCR-VL / PDF 시각 좌표계의 원점이 좌상단이므로 우측/하단 확장은 원점을 이동시키지 않는다. 좌측/상단 여백은 건드리지 않는다.
- 여백 코멘트 박스는 서로 겹치지 않도록 세로 위치를 순서대로 밀어내며 배치하고(`_layout_margin_notes`), 원래 요소 위치와 배치된 박스 위치가 달라지면 꺾이는 연결선(callout)으로 이어준다. **박스 높이는 텍스트 양에 따라 가변** (`_estimate_note_height`): 폰트 8pt 기준 약 22문자/줄로 줄 수를 추정해 높이를 계산, 최소 11pt(약 1줄)~최대 120pt(약 10줄) 범위에서 조절된다.
- LLM 요소 선택 프롬프트(`build_element_highlight_prompt`)는 표 행과 텍스트 블록이 혼합된 요소 목록에서 조건에 맞는 요소를 선택한다. 표 행은 헤더 컬럼명을 정확히 매칭하도록 명시하고, 텍스트 블록은 특정 단어/이름/날짜 포함 여부로 판단한다. 완전한 정확도는 보장되지 않으므로 결과 검토가 필요하다. 텍스트 블록은 앞 200자만 LLM에 전달해 토큰 폭증을 방지한다. **주석 코멘트는 사용자가 instruction에 사용한 언어로 작성**된다 — 프롬프트에서 "write the comment in the SAME language as the user's condition text"로 지시하여, 앱 지원 언어(ko/en/ja) 외의 언어(예: 불어, 스페인어)로 조건을 입력한 사용자도 자신의 언어로 주석을 받을 수 있다. 프롬프트 자체는 모두 영어로 작성되어 있다.
- **EmbedPDF AnnotationTransferItem[] 주석 (단일 진실원)**: 백엔드는 주석을 PDF에 구워 넣지 않고, 깨끗한 보정 이미지 PDF + EmbedPDF `importAnnotations()`가 기대하는 `AnnotationTransferItem[]` JSON만 저장한다. JSON이 있으면 프론트 `PdfViewer`가 초기 로드 시 `importAnnotations()`로 주석을 복원하고, 사용자는 뷰어 내에서 주석을 추가/편집/삭제할 수 있다. flatten 다운로드(주석이 포함된 PDF)는 embedpdf snippet 자체의 다운로드 UI가 `saveAsCopy()`로 처리한다. JSON 좌표는 PDF user-space(원점 좌하단, y↑)에서 embedpdf device-space(원점 좌상단, y↓)로 y축 flip한 포인트 좌표를 사용하며 (`origin.y = page_height - y1`), `PdfAnnotationSubtype`은 숫자 enum 값(`HIGHLIGHT=9`, `FREETEXT=3`)으로 기록한다.
- **사용자 주석 편집/저장**: 프론트에서 편집이 발생하면 "주석 저장" 버튼이 활성화된다. `SourcePanel`이 `exportAnnotations()`로 현재 JSON을 받아 `POST /api/jobs/{id}/user-annotations`로 전송하면, 백엔드는 `pdf_user_annotator.py`로 PyMuPDF 주석을 다시 렌더링하여 주석 PDF를 덮어쓰고, JSON 파일도 함께 갱신한다. Storage 경로는 `annotated_pdf_files[].annotations_json_storage_path`에 기록된다. `annotated_pdf_files` JSONB 배열의 각 객체는 이제 `storage_path`, `filename`, `annotations_json_storage_path`를 포함할 수 있다.
- **DB 필드**: `Job.annotate_instruction/annotate_mode/annotate_comment_mode/annotate_status/annotate_job_id/annotate_recovery_notes/annotate_refundable/annotate_reserved_pages/annotate_reserved_period_start`, `result_ocr_layout_storage_path`, `result_annotated_pdf_storage_path` (`020_add_pdf_annotate_fields.sql`). `annotate_job_id`/`result_xlsx_advanced_job_id`는 VARCHAR(64) (`021_widen_job_id_columns.sql`). 주석 결과 파일 목록은 `annotated_pdf_files` JSONB (`022_add_annotated_pdf_files.sql`). 고급주석(Vision LLM) 여부는 `annotate_advanced` BOOLEAN (`023_add_annotate_advanced.sql`).
- Key files:
  - `app/backend/core/ocr_layout.py` — PaddleOCR-VL `parsing_res_list` → `PageLayout`/`OcrTable`/`OcrRow`/`OcrTextBlock` 정규화 (HTML 표 파싱 + 행 bbox 균등분할 추정, 텍스트 블록 추출)
  - `app/backend/core/pdf_coords.py` — 픽셀 bbox ↔ PDF 포인트 변환, 페이지 경계 clamp
  - `app/backend/core/pdf_annotator.py` — `AnnotationTarget` 기반 하이라이트/여백 주석 렌더링 (회전 보정, 원본 mediabox 직접 확장으로 원점 이동 방지, 텍스트 양에 따른 가변 박스 높이, 겹침 방지 배치). `build_embedpdf_annotations()`로 EmbedPDF `AnnotationTransferItem[]` 형식 변환 (PDF user-space → device-space y축 flip). `annotate_pdf()`는 테스트용으로만 사용 (프로덕션은 JSON 오버레이 방식).
  - `app/backend/core/pdf_annotate_converter.py` — 오케스트레이터 (`run()`): 페이지 이미지 확보 → 보정(deskew + 90° 회전) → OCR bbox 확보 → 요소 수집(표 행+텍스트 블록) → LLM 요소 선택 → 좌표 변환 → 깨끗한 보정 이미지 PDF 업로드 + `.annotations.json` 업로드 (주석을 PDF에 구워 넣지 않음). `_images_to_pdf()`로 이미지→PDF 변환 지원.
  - `app/backend/core/pdf_user_annotator.py` — 사용자/백엔드 생성 JSON을 PyMuPDF로 렌더링 (highlight/underline/strikeout/free-text/rectangle/circle/line/arrow/ink 지원). `apply_user_annotations(pdf_bytes, annotations)`로 새 PDF 생성.
  - `app/backend/core/image_deskew.py` — 이미지 미세 기울기 보정 (`deskew` 라이브러리). 0.5° 미만은 생략, 흰색 배경으로 채움.
  - `app/backend/core/prompts.py` — `build_element_highlight_prompt()` (표 행+텍스트 블록 혼합, 사용자 조건 문구 언어로 코멘트 작성 지시), `build_row_highlight_prompt()` (레거시, 표 전용). 모든 프롬프트는 영어로 작성.
  - `app/backend/core/paddleocr_client.py` — `convert_image_with_layout()` (bbox 포함 변환, angle_code 반환), `_convert_and_poll()` 공통 폴링
  - `app/backend/paddleocr_service/main.py` — `_extract_layout_from_result()`, `ConvertResponse.layout` 필드, AI Studio `prunedResult` 전달
  - `app/backend/core/supabase_client.py` — `upload_image()` (원본 이미지를 `pdfs` 버킷에 개별 업로드). `_get_page_image_paths()`가 이 경로를 다운로드할 수 있도록 동일 버킷을 사용해야 한다.
  - `app/backend/workers/tasks.py` — `annotate_pdf_job` Celery task; 이미지 파일 처리 후 `extracted_files[i].storage_path`를 `upload_image()`로 설정
  - `app/backend/api/jobs.py` — `POST /jobs/{id}/annotate`, `POST /jobs/{id}/annotate-action` (xlsx_advanced와 동일 패턴), `POST /jobs/{id}/user-annotations` (사용자 주석 저장). preview/삭제 시 JSON 파일 동시 처리.
  - `app/frontend/src/components/PdfViewer.jsx` — `@embedpdf/react-pdf-viewer`의 `PDFViewer` 래퍼. `forwardRef`로 `exportAnnotations()` 노출, `importAnnotations()`로 초기 주석 로드, `onAnnotationChanged` 이벤트 상위 전달.
  - `app/frontend/src/components/SourcePanel.jsx` — `annotations_json_url` fetch, "주석 저장" 버튼, `onSaveAnnotations` 콜백.
  - `app/frontend/src/components/PagedResultViewer.jsx` — `SourcePanel`에 `onSaveAnnotations` 전달.
  - `app/frontend/src/pages/JobResultPage.jsx` — 하이라이트/주석 생성 버튼 + 모달 + 상태 폴링. `saveUserAnnotations()` API 호출.
  - `app/frontend/src/api.js` — `annotateJob()`, `annotateAction()`, `saveUserAnnotations()`.
  - `app/frontend/src/locales/{ko,en,ja}/page.json` — `saveAnnotations` i18n 키.

## OCR Progress Reporting

- `status == "ocr"`일 때 프론트엔드는 `job.done_pages / job.total_pages * 100`으로 퍼센트를 표시한다.
- **시간진행바 (Time Progress Bar)**:

  - 실제 진행률이 늦게 보고될 때 프로그레스 바가 멈춘 것처럼 느껴지는 문제를 해결하기 위해, 경과 시간 기반 추정 진행률을 추가한다.
- **Vision 파이프라인** (`pipeline_vision.py` / `run_vision`):

  - PDF -> PNG 렌더링과 OCR을 겹쳐 실행한다. 페이지가 렌더링되자마자 `ocr_client.render_pdf()`의 `on_page_rendered` 콜백으로 해당 페이지를 OCR executor에 즉시 제출한다.
  - 전체 작업을 2×N 단위로 보고: 각 페이지는 렌더링(1단위) + OCR(1단위). 프로그레스는 `(rendered_count + ocr_done_count) / (2 * total_pages) * 100`으로 계산한다.
  - 렌더링 워커는 `ThreadPoolExecutor`로 최대 64개까지 병렬 처리한다.
- **PagedResultViewer** (`app/frontend/src/components/PagedResultViewer.jsx`):

  - 100페이지 초과 작업의 결과 보기 페이지. 페이지 목록 사이드바와 툴바 페이지네이션을 제거하고, 상단에 저장 버튼만 남긴다.
  - 소스 PDF/문서 뷰어의 내부 페이지 컨트롤만 사용하며, `SourcePanel`과 `SimpleEditor`는 좌우 패널로 유지된다.
- **Docling 파이프라인** (`pipeline_docling.py` / `run_docling`):

  - Docling 서비스는 내부적으로 페이지별 진행률을 제공하지 않으므로, 경과 시간 기반 추정치(0~99%)를 사용하고 완료 시 100%로 설정한다.
- Key files:

  - `app/backend/core/ocr_client.py` — `render_pdf()` 진행률 콜백, `on_page_rendered` 콜백, 64 workers
  - `app/backend/core/pipeline_vision.py` — 렌더링/OCR 스트리밍, 2×N 진행률
  - `app/backend/core/docling_client.py` — Docling 폴링 진행률 추정
  - `app/frontend/src/utils/progress.js` — `getDisplayProgress`, `getTimeProgress`, `getActualProgress`
  - `app/frontend/src/pages/JobsPage.jsx` — 1초 타이머, 데스크톱/모바일 시간진행바 적용
  - `app/frontend/src/pages/JobResultPage.jsx` — `PoetryProgress`에 시간진행바 적용, `PagedResultViewer` 호출
  - `app/frontend/src/components/PagedResultViewer.jsx` — 100페이지 초과 결과 보기 (페이지네이션 제거, 저장 버튼만 유지)
- **PoetryProgress** (`app/frontend/src/components/PoetryProgress.jsx`):

  - 작업 진행 중 로딩 화면에 한국 명시를 표시하며, 30초 간격으로 랜덤하게 시가 교체됩니다.
  - 76편의 시가 수록되어 있으며 (윤동주 21편, 김소월 48편, 기존 7편), 시 데이터는 `ko/page.json`의 `poems` 배열에서 i18n으로 로드됩니다.
  - 같은 시가 연속으로 표시되지 않도록 중복 방지 로직이 포함되어 있습니다.
  - `SLIDE_INTERVAL = 30000` (30초, 기존 10초의 3배).

## GPU OCR Backends (Suspended)

- **Status**: b2 GPU server (RTX 3080) is currently down with boot failures and is scheduled for repair. All GPU OCR backend work is suspended until the server is recovered.
- **PaddleOCR-VL 1.6**: dual-container architecture (vLLM + PaddleOCR Pipeline) was in progress on b2. Files remain in `app/backend/paddleocr_service/` and `app/docker-compose.paddleocr.yml` for resumption after repair.
- **Nemotron-OCR-v2**: Docker-based evaluation was attempted but could not complete due to the b2 outage. The model is Turing/CC-7.5 unsupported by NVIDIA's official docs; evaluation will resume on a compatible GPU if available.
- **Fallback**: production currently uses the CPU-only Docling service with `OCR_ENGINE=easyocr`.

## Internationalization (i18n)

- Frontend uses `react-i18next` with two namespaces: `common` and `page`
- Translation files: `app/frontend/src/locales/{en,ko,ja}/{common,page}.json`
- Language detection: browser language → localStorage (`proof-language`) → Supabase user profile
- Backend persists user language via `PATCH /api/auth/language`
- `LanguageSelector` component in sidebar for manual switching
- `LanguageContext.jsx` provides `useLanguage()` hook for global access
- API docs translated: `app/API.md` (en), `app/API.ko.md` (ko), `app/API.ja.md` (ja)
- Docusaurus docs site supports en/ko/ja via `i18n/{locale}/docusaurus-plugin-content-docs/current/` directories
- Docusaurus docs are served at `/docs/` by FastAPI (`main.py` mounts `docs/build/` as static files)
- Admin pages (`AdminDashboard.jsx`, `AdminLogin.jsx`) are not yet internationalized
- When adding new UI strings, add keys to all three languages and use `t('namespace:key')`

## Subscription Service

- **기능 개요**: 구독 기반 사용량 관리 — 플랜별 월간 한도, 기간별 사용량 추적, 예약/차감/환불
- **플랜별 한도**:
  - `free`: basic_pages=1000, premium_pages=500, media_seconds=150분
  - `pro`: basic_pages=10000, premium_pages=5000, media_seconds=1500분
  - `max`: basic_pages=60000, premium_pages=30000, media_seconds=9000분
- **기간 계산**: 사용자의 `subscription_period_start` 기준 월간 기간, 없으면 달력월 시작일 사용
- **사용량 관리**:
  - `reserve_usage()`: 작업 시작 전 사용량 예약
  - `consume_usage()`: 작업 완료 후 실제 사용량 차감
  - `release_usage()`: 작업 실패 시 예약된 사용량 환불
- **구독 상태**: `is_subscription_active()`로 활성 여부 확인
- **Key files**: `app/backend/core/subscription_service.py`

## API Notes

- Base path: `/api/v1`
- Authentication: `X-API-Key: chu_live_...` or `Authorization: Bearer <key>`
- Billing: points are deducted per page/image/audio/video
- Docs: `/api/v1/docs` (OpenAPI/Swagger)
- Developer portal: `/developer` in the web UI
- Docusaurus docs site: `/docs/` (served by FastAPI from `docs/build/`)

## Office Conversion (DOCX/PPTX) & Excel Basic/Advanced Conversion

- Conversion is handled by `app/backend/core/office_converter.py` (basic) and `app/backend/core/xlsx_advanced_converter.py` (advanced).
- **DOCX**: renders headings, paragraphs with inline formatting (`**bold**`, `*italic*`, `~~strike~~`), bullet/numbered lists, tables, and code blocks. Free of charge.
- **HTML-aware DOCX/PPTX conversion**: PaddleOCR 등 HTML을 반환하는 OCR 엔진의 결과를 DOCX/PPTX로 변환할 때 HTML 태그를 정상적으로 파싱하여 포맷된 문서로 변환한다.
  - `_contains_html()`로 HTML 태그 감지 (`<table>`, `<img>`, `<div>`, `<p>`, `<h1>`~`<h6>` 등).
  - HTML 감지 시 `_html_to_docx()` / `_html_to_pptx()` 경로로 라우팅, 순수 마크다운은 기존 경로 유지.
  - 변환 매핑: `<img src="data:image/...;base64,...">` → 임베디드 이미지, `<table>` → DOCX 표 (Table Grid), `<h1>`~`<h6>` → 제목, `<p>`/`<div>` → 문단, `<ul>`/`<ol>` → 목록, `<b>`/`<i>`/`<strong>` → 인라인 서식, `<!-- 페이지 N -->` → 페이지 브레이크 (DOCX) / 슬라이드 분할 (PPTX).
  - 단독 HTML 요소(`<table>`만 입력 등) 처리를 위해 `<html><body>` 래핑 후 lxml 파싱.
  - 의존성: `lxml.html` (HTML 파싱), `Pillow` (base64 이미지 디코딩), `python-docx` (DOCX 생성), `python-pptx` (PPTX 생성).
  - 단위 테스트: `app/backend/tests/test_office_converter.py` (18개 테스트 — HTML 감지, HTML→DOCX 변환, 순수 마크다운 회귀, HTML→PPTX 변환).
- **PPTX**: removed from the UI. Backend code remains but no button is exposed.
- **Excel Basic** (`xlsx_basic` / `csv_basic`):
  - `_parse_markdown_tables()` extracts markdown tables → `_merge_tables()` merges consecutive tables with identical headers → `_normalize_rows()` pads all rows to the same column count.
  - `markdown_to_csv_basic()` writes a single CSV file with all merged tables.
  - `markdown_to_xlsx_basic()` writes a single-sheet xlsx with bold headers and auto-width columns.
  - **Pricing**: Excel Basic export is free of charge (`page:price.exportExcelBasicPrice` = "Free" / "무료" / "無料"). CSV Basic is also free.
  - Cost: **1 point/page** (deducted once per bundle — csv + xlsx generated together).
  - Already-converted files are reused (no double charging).
- **Excel Advanced** (`xlsx_advanced`):
  - LLM-based multi-pass conversion via `xlsx_advanced_converter.py` + Celery task `convert_xlsx_advanced`.
  - Pipeline: load markdown → split by pages → extract common column structure from first page (LLM text) → per-page: normalize with LLM text → if invalid, reconstruct with vision LLM (up to 3 retries with evaluation) → merge all tables → write xlsx.
  - Cost: **3 points/page**. On failure, user can retry (no extra charge) or refund.
  - Status tracked via `job.xlsx_advanced_status` (`""` → `"processing"` → `"done"` / `"error"`).
  - Recovery notes (`job.xlsx_advanced_recovery_notes`) record pages where vision reconstruction had issues.
  - `job.xlsx_advanced_refundable` indicates whether the user can request a refund.
  - Retry/refund endpoints: `/api/jobs/{id}/xlsx-advanced-action` (web) and `/api/v1/jobs/{id}/xlsx-advanced-action` (API).
- **Frontend**:
  - `JobResultPage.jsx`: Single download icon button (`FileDown`) with a hover menu containing Excel Basic, Excel Advanced, Word, and Markdown. The previous separate Excel and Office buttons were merged. Preview tabs for Markdown / Excel Basic / Excel Advanced use `SpreadsheetEditor.jsx` (Luckysheet-based xlsx editor).
  - `JobsPage.jsx`: `DownloadMenu` shows Markdown (free), CSV Basic, Excel Basic, Excel Advanced, Word (free). Polling includes `xlsx_advanced_status === "processing"` jobs.
  - `ExcelPreview.jsx`: deprecated, replaced by `SpreadsheetEditor.jsx`.
- **DB migration**: `013_add_xlsx_conversion_fields.sql` adds `result_xlsx_basic_storage_path`, `result_xlsx_advanced_storage_path`, `result_xlsx_advanced_job_id`, `xlsx_basic_converted`, `xlsx_advanced_converted`, `xlsx_advanced_status`, `xlsx_advanced_recovery_notes` (JSONB), `xlsx_advanced_refundable` columns.
- **Backward compatibility**: legacy `xlsx`/`csv` format requests are aliased to `xlsx_basic`/`csv_basic` via `_convert_format_alias()`. `result_xlsx_storage_path` is still set for backward compatibility.
- Conversion endpoints: `/api/jobs/{id}/convert` (web) and `/api/v1/jobs/{id}/convert` (API).
- Key files:
  - `app/backend/core/office_converter.py` — `_parse_markdown_tables`, `_merge_tables`, `_normalize_rows`, `markdown_to_csv_basic`, `markdown_to_xlsx_basic`, `_contains_html`, `_html_to_docx`, `_html_to_pptx`
  - `app/backend/tests/test_office_converter.py` — HTML→DOCX/PPTX 변환 및 순수 마크다운 회귀 단위 테스트
  - `app/backend/core/xlsx_advanced_converter.py` — LLM + vision advanced conversion pipeline
  - `app/backend/workers/tasks.py` — `convert_xlsx_advanced` Celery task
  - `app/backend/api/jobs.py` — web convert/download/xlsx-advanced-action endpoints
  - `app/backend/api/v1/jobs.py` — API v1 convert/download/xlsx-advanced-action endpoints
  - `app/frontend/src/pages/JobResultPage.jsx` — Excel/Office button groups, preview tabs
  - `app/frontend/src/pages/JobsPage.jsx` — DownloadMenu with new formats
  - `app/frontend/src/components/SpreadsheetEditor.jsx` — Luckysheet-based xlsx editor (replaces `ExcelPreview.jsx`)
  - `app/frontend/src/components/ExcelPreview.jsx` — deprecated, no longer imported
  - `app/frontend/src/api.js` — `xlsxAdvancedAction`, `saveEditedXlsx`, `editedXlsxUrl` API methods
  - `app/backend/db/migrations/013_add_xlsx_conversion_fields.sql` — DB migration
  - `app/backend/db/migrations/014_add_edited_xlsx_path.sql` — adds `result_edited_xlsx_storage_path` column

## Spreadsheet Editor (Luckysheet)

- Excel Basic / Excel Advanced 미리보기가 읽기 전용 `ExcelPreview.jsx`에서 완전한 스프레드시트 편집기 `SpreadsheetEditor.jsx`로 교체되었다.
- **라이브러리 로드 방식 (UMD 스크립트 태그)**: Vite + ESM 환경에서 CommonJS 기반 Luckysheet를 사용하기 위해, `plugin.js`, `luckysheet.umd.js`, `luckyexcel.umd.js`를 모두 `<script>` 태그로 동적 로드한다. 이는 전역 jQuery를 공유하여 `mousewheel` 플러그인 등이 정상 작동하도록 보장한다.
  - jQuery는 먼저 `import("jquery")`로 로드하여 `window.jQuery` / `window.$`에 노출한다.
  - CSS 3종 (`pluginsCss.css`, `luckysheet.css`, `iconfont.css`)은 `await import()`로 로드한다.
  - `loadScript()` 헬퍼 함수로 Vite `?url` import 경로를 받아 `<script>` 태그를 생성한다.
  - 로드 완료 후 `window.luckysheet`와 `window.LuckyExcel` 전역 객체를 사용한다.
- **Race condition 해결**: `libsLoaded` 상태 플래그로 스크립트 로드 완료 시점과 `downloadUrl` 설정 시점을 동기화한다. 첫 `useEffect`에서 스크립트 로드 완료 시 `setLibsLoaded(true)`, 두 번째 `useEffect`에서 `libsLoaded && downloadUrl` 모두 만족 시 `loadExcel` 호출.
- **컨테이너 스타일**: `position: absolute`, `width: 100%`, `height: 100%` 인라인 스타일로 Luckysheet가 컨테이너 offset을 정상 읽도록 보장한다.
- **툴바 설정**: `showtoolbar: true`만 사용하고 `showtoolbarConfig` 커스텀 설정은 제거한다. 커스텀 설정 시 일부 툴바 버튼이 DOM에 존재하지 않아 `offset().left`가 undefined가 되는 버그(`Cannot read properties of undefined (reading 'left')`)를 방지.
- **luckysheet.create 호출 시점**: `requestAnimationFrame` 2회 중첩으로 DOM 렌더링을 보장한 후 호출한다.
- **LuckyExcel** (`luckyexcel` npm package)로 XLSX 파일을 Luckysheet JSON으로 변환한다. `transformExcelToLucky(file, callback)`에 `File` 객체를 전달한다.
- **SheetJS** (`xlsx` npm package)로 Luckysheet 데이터를 XLSX Blob으로 변환한다. `getAllSheets()` → `luckysheetDataToWorkbook()` → `XLSX.write()` → Blob.
- **편집 기능**: 기본 툴바 (undo/redo, 서식, 글꼴, 정렬, 정렬/필터, 차트, 이미지, 인쇄), 시트 추가/삭제, 줌, 상태 표시줄.
- **서버 저장**: `POST /api/jobs/{job_id}/save-edited-xlsx` — 편집된 XLSX를 Supabase Storage `results` 버킷에 업로드하고 `job.result_edited_xlsx_storage_path`에 경로를 저장한다.
- **편집본 재조회**: `GET /api/jobs/{job_id}/edited-xlsx-url` — 저장된 편집본의 signed URL을 반환한다. `SpreadsheetEditor` 로드 시 편집본이 있으면 원본 대신 편집본을 우선 로드한다. 편집본이 없으면 404가 반환되며 정상 동작이다.
- **로컬 다운로드**: 편집된 데이터를 XLSX Blob으로 생성하여 브라우저에서 직접 다운로드한다.
- **초기화**: 원본(또는 편집본) 데이터로 `luckysheet.create()`를 다시 호출하여 편집 내용을 되돌린다.
- **언마운트/재로드**: `luckysheet.destroy()`를 호출하여 메모리 누수를 방지한다.
- **DB 마이그레이션**: `014_add_edited_xlsx_path.sql`이 `result_edited_xlsx_storage_path` 컬럼을 `jobs` 테이블에 추가한다.
- Key files:
  - `app/frontend/src/components/SpreadsheetEditor.jsx` — Luckysheet 기반 스프레드시트 편집기
  - `app/frontend/src/api.js` — `saveEditedXlsx`, `editedXlsxUrl` API 메서드
  - `app/backend/api/jobs.py` — `save_edited_xlsx`, `get_edited_xlsx_url` 엔드포인트
  - `app/backend/core/supabase_client.py` — `upload_edited_xlsx()` 함수
  - `app/backend/db/models.py` — `result_edited_xlsx_storage_path` 필드
  - `app/backend/db/migrations/014_add_edited_xlsx_path.sql` — DB 마이그레이션
  - `app/frontend/src/pages/JobResultPage.jsx` — Excel Basic/Advanced 탭에서 `SpreadsheetEditor` 렌더링

## DOCX/HWP Preview

- `docx` and `hwp` source files are converted to PDF on the backend using LibreOffice headless.
- The converted PDF is stored in Supabase Storage under the `pdfs` bucket (`preview_pdfs/` prefix) and reused across preview requests.
- The frontend renders the converted PDF with `PdfViewer` (PDF.js), just like native PDFs.
- Preview conversion is a server-side operation; no client-side load is added.
- CJK (Korean/Chinese/Japanese) fonts are installed in the Docker image so that non-Latin characters render correctly:
  - `fonts-noto-cjk`, `fonts-nanum`, `fonts-unfonts-core`, `fonts-noto-color-emoji`
  - `libreoffice-l10n-ko`, `libreoffice-help-ko`, `locales` with `LANG=ko_KR.UTF-8`/`LC_ALL=ko_KR.UTF-8`
- For `.hwp` files, the backend first tries `pyhwp`'s `hwp5odt` to produce an ODT and then converts it to PDF with LibreOffice. If `hwp5odt` is unavailable or fails, it falls back to direct LibreOffice conversion.
- Key files: `app/backend/core/pdf_preview_converter.py`, `app/Dockerfile.backend`, `app/backend/api/jobs.py`, `app/frontend/src/components/SourcePanel.jsx`, `app/frontend/src/components/PdfViewer.jsx`.

## Result Preview & Multi-file Uploads

- Uploading multiple files creates one job; each file's parsing result is stored separately in `extracted_files[].result_markdown`.
- The combined markdown uses file markers (`<!-- 파일 N -->`) via `converter.build_combined_file_markdowns()`.
- `/api/jobs/{id}/preview` returns `source_files` (name, type, url, storage_path, page_num, result_markdown, source_index, source_kind) for each original file. PDF 원본은 signed URL로 브라우저 네이티브 뷰어에 표시된다.
- **원본 파일 삭제**: 결과 페이지의 `SourcePanel` 파일 목록 각 항목에 휴지통 아이콘을 표시한다. 클릭 시 확인 모달을 띄우고, 확인하면 `DELETE /api/jobs/{id}/source-files/{source_kind}/{source_index}`를 호출한다.
  - `source_kind`는 `original` (원본 파일) 또는 `annotation` (주석 PDF)이다.
  - 백엔드는 Supabase Storage에서 실제 파일을 삭제하고, DB의 `extracted_files` 또는 `annotated_pdf_files`에서도 항목을 제거한다.
  - 단일 PDF/DOCX/HWP 업로드의 경우 `pdf_storage_path`를 직접 삭제한다.
  - 이미 생성된 변환 결과물(마크다운, XLSX, DOCX 등)은 재생성하지 않고 그대로 유지한다.
  - i18n 키: `page:result.deleteSourceFileTitle`, `page:result.deleteSourceFileDesc` (ko/en/ja).
  - Key files: `app/backend/api/jobs.py` (`delete_source_file`, `_delete_original_file`, `_delete_annotation_file`), `app/frontend/src/components/SourcePanel.jsx`, `app/frontend/src/pages/JobResultPage.jsx`.
- PDF preview uses an iframe with the browser's native PDF viewer (`PdfViewer`). The toolbar with page navigation is at the top of the preview panel. The preview panel scrolls independently and the page is aligned to the top.
- `SourcePanel` renders a single source when only one exists, and a file list + selected preview when multiple sources exist.
- `SourcePanel` supports controlled selection via `selectedFileIndex` / `onFileSelect` props.
- `JobResultPage` manages `fileMarkdowns` state: when multiple files exist, `SimpleEditor` shows only the selected file's markdown.
- Saving in multi-file mode uses `api.saveResultFileMarkdowns()` (PUT `file_markdowns` array); single-file mode uses `api.saveResultMarkdown()`.
- The `save_result_markdown` backend endpoint accepts `file_markdowns` (array) to update `extracted_files` and rebuild the combined markdown.
- When adding new source media types, update `SourcePanel.jsx` and add i18n keys to `page:result` and `page:components`.

## Upload Page File Management

- Upload page hero title: `page:upload.title` — "수백개 자료도 원클릭 데이터 변환" (ko), "Hundreds of files, one-click data conversion" (en), "数百のファイルもワンクリックでデータ変換" (ja).
- 드래그앤드롭, 파일 선택, 폴더 선택 모두 기존 파일 리스트에 **누적 추가**된다 (이전에는 대체).
- 동일한 이름+크기의 파일은 중복으로 간주하여 **건너뛴다**.
- 파일 입력 `<input>`은 선택 후 `e.target.value = ""`로 초기화하여 같은 파일 재선택이 가능하다.
- 드래그앤드롭 영역이 `<label>`에서 `<div>`로 변경되었으며, `onDragOver`/`onDrop`/`onDragEnter`/`onDragLeave`에 `preventDefault`를 사용해 브라우저 기본 동작을 차단한다.
- `document` capture phase에서 전역 `dragover`/`drop` 기본 동작을 차단하여, drop zone 밖에 떨어뜨려도 브라우저가 파일을 열지 않는다.
- `handleDrop()`에서 파일 아이템은 `item.getAsFile()`로 직접 수집하고, 디렉토리 아이템만 `webkitGetAsEntry()` + `traverseEntry()`로 재귀 처리한다. `dataTransfer.items`가 없으면 `dataTransfer.files`를 fallback로 사용한다.
- `handleDrop()`과 `traverseEntry()`에서 발생하는 예외를 catch하여 전체 페이지가 멈추지 않도록 한다.
- 각 파일 항목에 개별 삭제 버튼(X 아이콘)이 있으며, "취소" 버튼은 전체 리스트 초기화 역할을 유지한다.
- Key file: `app/frontend/src/pages/UploadPage.jsx` — `addFiles()`, `removeFile()`, `handleDrop()`

## GridScan WebGL Fallback

- `GridScan`은 Three.js WebGLRenderer를 사용한 배경 시각 효과 컴포넌트이다.
- WebGL 컨텍스트를 생성할 수 없는 환경(일부 headless 브라우저, WebGL 비활성화 등)에서 전체 페이지가 crash되지 않도록, 렌더러 생성 실패 시 `glFailed` 상태를 설정하고 `null`을 반환한다.
- Key file: `app/frontend/src/components/GridScan.jsx`

## Sidebar Account Navigation

- 사이드바 하단의 "Logged in as" 계정 카드에서 이메일 주소를 클릭하면 `/settings?tab=account`로 이동하여 계정 설정을 열 수 있다.
- 이메일은 `react-router-dom`의 `Link` 컴포넌트로 렌더링되며, 호버 시 primary 색상과 밑줄이 표시된다.
- Key file: `app/frontend/src/components/SidebarLayout.jsx`

## UI/UX Design System

- **Skeleton Loading**: All dynamic data areas use skeleton components (`Skeleton`, `SkeletonCard`, `SkeletonTable`, `SkeletonPageResult`) from `app/frontend/src/components/Skeleton.jsx` instead of spinner loaders. Pages with `dataLoading` state: DashboardPage, JobsPage, JobResultPage, PaymentPage, DeveloperPage, SettingsPage, JobConfirmPage.
- **Staggered List Animation**: All list/table rows use `AnimatedRow` from `app/frontend/src/components/AnimatedList.jsx` for sequential entrance animation. CSS keyframes `stagger-enter` defined in `app/frontend/src/index.css` (240ms ease-out, 30ms stagger per item).
- **Sharp Corners (No Border Radius)**: All `borderRadius` values set to `0` in `app/frontend/tailwind.config.js`. Scrollbar thumb and ProseMirror marks also have `border-radius: 0` in `index.css`.
- **Reduced Font/Element Scale**: Font sizes and spacing reduced ~10-20% via `tailwind.config.js` (`fontSize`, `spacing`). Individual pages have further padding reductions (e.g., `p-8` → `p-5`, `py-3` → `py-2`).
- **Applied Pages**: DashboardPage, JobsPage, JobResultPage, PaymentPage, DeveloperPage, SettingsPage, UploadPage, AuthPage, AdminLogin, AdminDashboard, JobConfirmPage, PoetryProgress, SidebarLayout.
- Key files:
  - `app/frontend/src/components/Skeleton.jsx` — Reusable skeleton components
  - `app/frontend/src/components/AnimatedList.jsx` — `AnimatedRow` / `AnimatedList` wrappers
  - `app/frontend/src/index.css` — `@keyframes stagger-enter`, scrollbar/mark border-radius overrides
  - `app/frontend/tailwind.config.js` — Reduced fontSize, spacing, borderRadius: 0

## API Error Messages (English)

- All backend `HTTPException`, `JSONResponse`, `RuntimeError`, `ValueError`, `FileNotFoundError`, and `TimeoutError` messages are in **English**.
- Korean error messages were fully translated across all backend files: `api/`, `auth/`, `core/`, `workers/`, `docling_service/`, `paddleocr_service/`, `email_sender.py`, `compare_ocr.py`.
- Frontend UI strings remain i18n (ko/en/ja) via `react-i18next`.
- Turnstile verification failure returns `"Bot verification failed. Please try again."` (was Korean).

## On-Premise Inquiry

- On-premise local server quote page at `/on-premise` (`OnPremisePage.jsx`).
- Backend: `app/backend/api/on_premise.py` — `POST /api/on-premise/inquiry` creates an inquiry, sends admin email.
- Pricing: linear from $20,000 (3,000 pages/hr) to $80,000 (12,000 pages/hr), in 1,000-page/hr increments.
- DB: `on_premise_inquiries` table (`016_add_on_premise_inquiry.sql`).
- Key files: `app/backend/api/on_premise.py`, `app/frontend/src/pages/OnPremisePage.jsx`, `app/backend/db/models.py` (`OnPremiseInquiry`).

## Dev Auth (Local Development Only)

- `app/backend/api/dev_auth.py` — bypasses Supabase Auth for local development.
- Only active when `DEV_BYPASS_AUTH=true` in `.env`.
- `POST /api/dev/login` issues a Supabase-compatible JWT for a fixed dev user (`dev@proof.local`).
- **Never enable in production.**
- **Frontend Dev Mock Mode** (`import.meta.env.DEV`):
  - Vite dev 모드에서 자동 활성화되며, 백엔드 `/api/dev/login` 우선 시도 후 실패 시 mock 사용자로 폴백합니다.
  - `app/frontend/src/dev/mockUser.js` — mock 사용자/세션 객체.
  - `app/frontend/src/dev/mockApi.js` — 모든 API 요청을 가로채 mock 응답 반환 (빈 목록, 기본 프로필, 더미 작업 등).
  - `app/frontend/src/components/DevBypassBanner.jsx` — mock 모드 활성 시 상단에 안내 배너 표시.
  - `app/frontend/src/AuthContext.jsx` — `AuthProvider`가 dev 모드에서 초기 mock 세션 설정, 실제 세션 감지 시 mock 비활성화.
  - `app/frontend/src/api.js` — `devMockEnabled` 플래그로 `mockRequest()` 라우팅.
  - 실제 백엔드 세션이 감지되면 자동으로 mock 모드가 비활성화됩니다.

## GDPR / Account Data

- `app/backend/api/gdpr.py` — GDPR compliance endpoints.
- `GET /api/account/export` — exports all user data as JSON (jobs, payments, API keys, usage).
- `DELETE /api/account/delete` — deletes user account and all associated data.
- Key file: `app/backend/api/gdpr.py`.

## Legal Pages & Cookie Consent

- `/terms` — Terms of Service (`LegalTermsPage.jsx`, i18n).
  - 6장 18조 구조: 제1장 총칙·이용계약(s1–s5), 제2장 서비스 아키텍처·기술적 한계(s6–s7), 제3장 데이터 국지화·개인정보 보호(s8–s9), 제4장 자체 호스팅 AI 지식재산권·환각 면책(s10–s12), 제5장 API 모네타이제이션·B2B 책임 통제(s13–s14), 제6장 책임 제한·수출 통제·분쟁 해결(s15–s18).
  - `renderParagraphs()` 헬퍼로 `\n` 기준 다단락 렌더링, `h2`(장) + `h3`(조) 계층 구조.
  - i18n 키: `legal.terms.ch1Title`~`ch6Title`, `legal.terms.s1Title`~`s18Title`, `legal.terms.s1Body`~`s18Body`, `legal.terms.contactTitle/contactBody`.
  - 시행일: 2026-07-03.
- `/privacy` — Privacy Policy (`LegalPrivacyPage.jsx`, i18n).
- `/refund-policy` — Refund Policy (`LegalRefundPage.jsx`, i18n).
  - Paddle 심사 통과를 위한 별도 페이지. 미사용 크레딧 14일 환불, 사용 후 불가, 청구 방법, 처리 기간 안내.
  - i18n 키: `legal.refund.title`, `legal.refund.lastUpdated`, `legal.refund.effectiveDate`, `legal.refund.body` (ko/en/ja).
- `CookieConsent` component shown on all pages (bottom banner).
- Legal contact email: `admin@proof.teamcat.app`.
- Key files: `app/frontend/src/pages/LegalTermsPage.jsx`, `app/frontend/src/pages/LegalPrivacyPage.jsx`, `app/frontend/src/pages/LegalRefundPage.jsx`, `app/frontend/src/components/CookieConsent.jsx`, `app/frontend/src/components/GlobalFooter.jsx`.
- Locale files: `src/locales/{ko,en,ja}/common.json` — `legal.terms`, `legal.privacy`, `legal.refund` 섹션.

## Docusaurus Docs Site

- Served at `/docs/` by FastAPI (`main.py` mounts `docs/build/` as static files).
- Source: `app/docs/docs/` (English), translations under `app/docs/i18n/{ko,ja}/docusaurus-plugin-content-docs/current/`.
- **External links**: use `pathname:///path` protocol (e.g., `pathname:///developer`, `pathname:///api/v1/docs`) in both `docusaurus.config.js` and markdown files. Relative paths like `../../developer` cause broken links on i18n pages.
- **Doc-internal links**: use doc IDs without `.md` extension (e.g., `[HWP Support](hwp)`, `[file formats](file-formats)`), not file paths like `./hwp.md` or `../file-formats`.
- Sidebars: `app/docs/sidebars.js` — three sidebars: `docsSidebar`, `apiReferenceSidebar`, `aiPromptsSidebar`.
- Build: `cd app/docs && npm run build` (outputs to `docs/build/`).
- When adding new docs pages, create EN source + KO/JA translations and register in `sidebars.js`.

## Agent Guidelines

- Prefer minimal, focused edits. Follow existing code style.
- Add DB schema changes to `app/backend/db/migrations/` as SQL files.
- Do not commit media files, PDFs, or `node_modules`.
- Test API changes by creating a temporary API key and running the full upload→confirm→download flow.
- Keep the workflow-linear code style with flow comments at the top of major functions.
- When adding UI text, always use i18n translation keys. Never hardcode user-facing strings.
- Add new translation keys to all three locale files (en/ko/ja) simultaneously.
- When adding new Docusaurus docs pages, create the English source in `app/docs/docs/` and add Korean/Japanese translations under `app/docs/i18n/{ko,ja}/docusaurus-plugin-content-docs/current/`.

## Subscription Plans (Free / Pro / Max)

- **UI users** (web app) use subscription plans only. API users continue to use the pay-as-you-go credit system (`points_balance`).
- **Plans**:
  - Free: 1,000 basic pages + 500 premium pages + 150 min media/month
  - Pro: $20/month or $200/year — 10,000 basic + 5,000 premium + 1,500 min media/month
  - Max: $100/month or $1,000/year — 60,000 basic + 30,000 premium + 9,000 min media/month
- **Key files**:
  - `app/backend/core/subscription_service.py` — monthly quota tracking and reservation.
  - `app/backend/api/subscriptions.py` — public plan listing, checkout, and cancel endpoints.
  - `app/backend/api/payments.py` — Paddle webhook handling for `subscription.*` events.
  - `app/backend/db/migrations/018_add_subscription_plan.sql` — schema migration.
  - `app/frontend/src/pages/PlansPage.jsx` — subscription plan UI.
  - `scripts/create_paddle_subscription_catalog.py` — automated Paddle product/price creation.
- **Paddle API key**: store in `app/.env` as `PADDLE_API_KEY`. It is seeded into `app_settings` via `settings_store.py` and `config.py`.
- **Creating catalog**: run `PADDLE_API_KEY=... DATABASE_URL=... python scripts/create_paddle_subscription_catalog.py`. This creates products and monthly/yearly prices for Free/Pro/Max and saves the resulting `price_id`s into `app_settings`.
- **Webhooks**: Paddle dashboard must send `subscription.created`, `subscription.updated`, `subscription.canceled`, and `transaction.completed` to `https://proof.teamcat.app/api/payments/paddle/webhook`.
- **Free $0 note**: if Paddle does not allow a $0 recurring checkout, the Free tier can stay internal-only (no Paddle subscription) and only Pro/Max use Paddle checkout. The backend treats `subscription_plan == "free"` as always active.

## Frontend Dropdown Hover UX

- CSS-only `group-hover` dropdowns (e.g. the download icon button in `JobResultPage.jsx`) can disappear when the cursor crosses the small gap between the trigger button and the dropdown panel.
- Use React state + `useRef` timer instead:
  - `onMouseEnter`: clear any pending close timer and open the dropdown.
  - `onMouseLeave`: start a short timeout (e.g. 150ms) before closing the dropdown.
  - Apply the handlers to both the trigger button wrapper and the dropdown panel itself so moving the mouse between them keeps the dropdown open.
- Replace `hidden group-hover:flex` with conditional classes driven by the open state: `${open ? "flex" : "hidden"}`.
- Key files: `app/frontend/src/pages/JobResultPage.jsx` (Excel/Office dropdowns).

## PDF Annotation (PDF 하이라이트/여백 주석)

- **구독 기능**: PDF 주석 생성은 구독 기반의 프리미엄 기능입니다. 비회원 사용자는 사용할 수 없습니다.
- **비회원 처리**: `job.user_id`가 `None`인 경우 402 에러("구독이 필요한 기능입니다.")를 반환하고, 프론트엔드에서는 price 페이지로 리디렉트합니다.
- **관리자 권한**: `mtgmtg@naver.com` (관리자)는 모든 기능을 무제한으로 사용할 수 있습니다. 구독 체크를 건너뛰고 바로 처리합니다.
- **백엔드 로직** (`app/backend/api/jobs.py`의 `annotate_job` 및 `annotate_action` 엔드포인트):
  - `job.user_id`가 `None`이면 402 에러 반환 (주석 생성뿐 아니라 재시도 action 엔드포인트에서도 동일 체크)
  - `db_user.is_admin`가 `True`이면 구독 체크 없이 바로 처리 (환불 불필요, 예약 페이지 수 0)
  - 일반 사용자는 `subscription_service.reserve_usage()`로 구독 한도 체크 및 차감
- **프론트엔드 처리**:
  - `app/frontend/src/pages/JobResultPage.jsx`의 `startAnnotate(instruction)` 함수가 API를 호출하고, 에러 메시지에 "구독이 필요" 또는 "subscription"이 포함되면 2초 후 price 페이지로 자동 이동합니다.
  - `app/frontend/src/components/SourcePanel.jsx`의 `AiAnnotationFab` 컴포넌트가 PDF 소스 패널 하단 중앙에 작은 FAB으로 표시됩니다. 클릭하면 `scale`/`opacity`/`translate` 트랜지션으로 입력 카드 팝업이 부드럽게 펼쳐지며, instruction을 입력하고 생성할 수 있습니다.
  - i18n 키 `page:errors.subscriptionRequired` 사용 (ko/en/ja 모두 추가)
- **주석 생성 비용**: 프리미엄 페이지 수(`premium_pages`)로 차감됩니다. 관리자는 차감되지 않습니다.
- **재시도 액션** (`annotate_action` 엔드포인트): 주석 생성이 `error` 상태로 실패한 경우 사용자가 재시도(retry)할 수 있습니다. 구독제이므로 환불(refund) 기능은 제공하지 않습니다. 비회원 사용자는 이 액션 엔드포인트에서도 402 에러를 받습니다.
- **결과 파일 노출**: 주석 생성이 완료되면 `JobResultPage.jsx`의 파일 탭에 `<원본파일명>_annotation1.pdf`, `_annotation2.pdf` … 형식으로 누적 추가됩니다. 별도의 ‘주석 PDF 다운로드’ 버튼은 생성되지 않으며, AI 주석 FAB은 PDF 패널 하단에 계속 떠 있는 작은 트리거로 유지됩니다.
- **결과 저장**: `app/backend/core/pdf_annotate_converter.py`는 각 주석을 `results/{job_id}/annotated_{N}.pdf`로 저장하고, `Job.annotated_pdf_files` JSONB 목록에 `storage_path`, `filename`, `instruction`, `mode`, `comment_mode`, `created_at`을 기록합니다. 동일한 `(instruction, mode, comment_mode)`로 재요청하면 기존 파일을 반환합니다.

## Frontend Variable Naming Conventions

- **JobResultPage.jsx**: XLSX 변환 비용 표시 시 `xlsxBasicCost`/`xlsxAdvancedCost` 대신 `xlsxBasicUnits`/`xlsxAdvancedUnits`를 사용해야 합니다.
- 이 두 변수는 이미 409-410번 라인에서 정의되어 있으며: `job.total_pages || job.total_files || 1` 값으로 계산됩니다.
- 구독제에서는 실제 달러 비용이 아니라 구독 월간 페이지 한도를 차감하므로 "units"라는 명칭이 더 정확합니다.
- i18n 키 `page:result.xlsxBasic`과 `page:result.xlsxAdvanced`는 `cost` 파라미터를 받아 표시합니다.

## Backend 테스트 실행 참고

- `backend` 폴더에서 `pytest`를 실행할 때 `core` 패키지와 `backend` 패키지가 모두 정상적으로 임포트되도록 하려면 작업 디렉터리를 `app/backend`로 설정하고 `PYTHONPATH`에 `app`의 상위 디렉터리(`app`)를 추가해야 한다.
  - 예: `cd /path/to/repo/app/backend && PYTHONPATH=/path/to/repo/app python -m pytest tests/`
  - `PYTHONPATH=/app`를 지정하면 `backend.*` 모듈 임포트가 가능하고, 현재 디렉터리 `app/backend`가 `sys.path`에 포함되어 `core.*` 직접 임포트도 가능하다.
- 프론트엔드: `cd app/frontend && npm run test` / `npm run build`

## Searchable PDF 우선순위 — 텍스트 레이어가 있는 원본 PDF 사용

- `app/backend/workers/tasks.py`에서 `_build_and_upload_searchable_pdf`보다 `_register_searchable_pdf_if_text_layer`를 먼저 호출해야 합니다.
- `_build_and_upload_searchable_pdf` 내부 맨 앞에 `if job.searchable_pdf_storage_path: return` guard를 추가해, 이미 원본이 등록된 경우 OCR 재생성으로 덮어쓰지 않습니다.
- 이렇게 하면 텍스트 레이어가 있는 PDF는 PaddleOCR 재변환 없이 원본의 정확한 텍스트 좌표를 그대로 사용하므로, 에이전트 하이라이트 y축 반전/오차가 해결됩니다.
- `_insert_invisible_text`의 `baseline_y = y0 + font_size` 계산은 실제로 투명 텍스트 검색 bbox가 원래 bbox 안에 들어오므로 수정하지 않습니다.
- 회귀 테스트: `tests/test_tasks_searchable_pdf_priority.py`, `tests/test_pdf_text_layer_baseline.py`

## OCR Layout PDF user-space 감지

- `app/backend/paddleocr_service/main.py`의 `_extract_layout_from_result`는 AI Studio에 원본 PDF를 직접 제출했을 때 반환 bbox가 PDF user-space(y↑)일 수 있으므로 동적으로 감지한다.
- `page_height_px`가 `page_height_pt`와 비슷하고(0.8~1.2배), 상단 블록 샘플의 y 평균이 페이지 상반부에 있으면 PDF user-space로 판단해 y축을 뒤집는다.
- `_normalize_bbox` / `_normalize_points`는 `flip_y` 플래그로 top-left normalized(y=0 상단)를 생성한다.
- 이렇게 하면 OCR로 생성된 searchable PDF 텍스트 레이어 좌표가 원문과 상하 반전되는 문제를 방어할 수 있다.
- 회귀 테스트: `tests/test_paddleocr_layout_pdf_user_space.py`

## OCR searchable PDF y-flip canary 검증 + 좌표계 변환 일원화

- `app/backend/core/pdf_text_layer.py`의 `add_text_layer_from_ocr`는 파일당 1개 canary 페이지로 y-flip을 검증한다.
  - 원본 PDF에서 canary 텍스트를 `page.search_for`로 찾아 ground truth bbox를 확보한다.
  - OCR bbox를 PDF user-space로 변환한 표준/반전 두 rect 중 ground truth와 IoU가 더 높은 쪽을 선택해 파일 전체에 적용한다.
  - `force_flip_y` 파라미터로 외부에서 강제할 수도 있다.
- `app/backend/core/pdf_coordinate_transform.py`를 신설해 모든 y-flip/스케일 변환을 `fitz.Matrix`로 한 곳에서 처리한다.
  - `normalized_top_left_to_pdf_user`, `image_top_left_to_pdf_user`, `pdf_user_to_device`, `device_to_pdf_user`, `embedpdf_rect_from_pdf_user`, `pdf_user_rect_from_embedpdf` 등을 제공한다.
- `pdf_text_layer.py`, `pdf_coords.py`, `pdf_annotator.py`, `pdf_user_annotator.py`의 산발적 `1 - y` 계산을 `pdf_coordinate_transform` 함수로 대체한다.
- 회귀 테스트: `tests/test_pdf_text_layer_canary.py`, `tests/test_pdf_coordinate_transform.py`, `tests/test_coord_transform.py`
