# Subagent C Status
- Branch: feature/canonical-annotation-coords
- Worktree: /Users/jun16/repo/chungu-worktree-c
- Status: completed
- Started: previous thread
- Last update: done

## 완료한 작업

### 백엔드 (Python)
1. `app/backend/core/canonical_annotation_coords.py`
   - device-space ↔ canonical normalized (0-1, 좌상단 원점, y↓) ↔ PDF user-space 간 rect/point 변환 함수 유지 및 보강
2. `app/backend/core/pdf_annotate_converter.py`
   - AI 주석 생성 시 canonical JSON document(`coordinate_system`, `source_pdf_storage_path`, `source_pdf_bucket`, `page_dimensions`, `annotations`)로 저장
3. `app/backend/core/pdf_user_annotator.py`
   - `device` / `pdf_user` / `canonical` 간 양방향 변환 지원 (`_convert_annotations_to_pdf_user`, `_convert_annotations_to_canonical`)
4. `app/backend/api/jobs.py`
   - `save_user_annotations`: `input_space`에 `"canonical"` 추가, viewer가 보내는 device-space를 canonical로 변환 후 저장
   - `get_job_annotations` / `get_job_result_json(kind="annotations")`: Storage의 canonical document를 읽어 PDF user-space로 변환하여 반환
   - `_load_all_annotations`: list(legacy device)와 canonical object를 모두 수용, dict(`annotations` 등) 반환
   - `update_job_annotation`: canonical object 형태 보존하면서 주석 속성 업데이트

### 프론트엔드 (React)
5. `app/frontend/src/components/SourcePanel.jsx`
   - `annotations_json_url`로 받은 JSON이 canonical object일 경우 `page_dimensions`를 이용해 device-space로 변환 후 `PdfViewer`에 전달
   - `normalizeAnnotationsJson`, `canonicalToDeviceAnnotation` 등 헬퍼 추가
6. `app/frontend/src/api.js`
   - `saveUserAnnotations` 요청에 `input_space: 'device'` 명시

### AI 백엔드 (TypeScript)
7. `app/ai-backend/src/lib/proof-api.ts`
   - `saveAnnotations`의 `inputSpace` union에 `"canonical"` 추가

### 테스트
8. `app/backend/tests/test_canonical_annotation_coords.py` (신규)
   - canonical ↔ device / PDF user-space round-trip 및 edge case 검증
9. `app/backend/tests/test_pdf_annotate_converter_run.py`
   - 업로드된 주석 JSON이 canonical document임을 확인하도록 assertion 수정
10. `app/backend/tests/test_pdf_annotator_build.py`
    - `build_embedpdf_annotations`가 canonical 좌표를 반환함에 맞춰 rect assertion 수정
11. `app/backend/tests/test_load_annotations.py`
    - `_load_all_annotations`가 dict를 반환함에 맞춰 test helper/assertion 수정

## 검증 결과

- `cd app/backend && .venv/bin/python -m pytest tests/ -q` → 237 passed
- `cd app/frontend && npm run build` → success
- `cd app/frontend && npm run test` → 9 passed, 61 tests
- `cd app/ai-backend && npm run build` → tsc success

## 주요 변경 파일

- `app/backend/api/jobs.py`
- `app/backend/core/canonical_annotation_coords.py`
- `app/backend/core/pdf_annotate_converter.py`
- `app/backend/core/pdf_user_annotator.py`
- `app/backend/core/pdf_annotator.py` (일부)
- `app/frontend/src/components/SourcePanel.jsx`
- `app/frontend/src/api.js`
- `app/ai-backend/src/lib/proof-api.ts`
- `app/backend/tests/test_canonical_annotation_coords.py` (신규)
- `app/backend/tests/test_pdf_annotate_converter_run.py`
- `app/backend/tests/test_pdf_annotator_build.py`
- `app/backend/tests/test_load_annotations.py`

## 참고

- `build_embedpdf_annotations`는 이제 canonical normalized 좌표(`origin`/`size` 0-1)를 반환하며, 실제 EmbedPDF 뷰어에 넣기 전/후 변환은 `SourcePanel`/`save_user_annotations`에서 담당한다.
- 기존 legacy list 형태의 주석 JSON은 `coordinate_system`이 없으면 device로 간주하여 하위 호환된다.
