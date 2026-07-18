# PDF 주석 영구 저장 제거 플랜

## 목표

`saveUserAnnotations` → PyMuPDF로 PDF 파일에 주석을 새겨 영구 저장하는 플로우를 제거한다. 사용자 주석은 JSON 오버레이로만 저장하고, PDF flatten 다운로드는 EmbedPDF 브라우저 내 `export` 기능에 맡긴다.

## 원칙

- 시스템에 영향이 없는 한도 내에서 깨끗이 제거한다.
- AI annotate(`pdf_annotate_converter.py`)는 이미 JSON-only 설계이므로 `annotated.pdf`를 `searchable.pdf`로 이름만 바꾼다.
- `result_annotated_pdf_storage_path` 필드를 완전히 제거하고, `annotated_pdf_files` entry의 `storage_path`만 searchable PDF 경로로 사용한다.
- `pdf_user_annotator.py` 자체는 `_ensure_clean_source_pdf` 등 좌표 변환/내장 주석 추출 용도로 계속 필요하므로 유지한다.

## 단계별 체크리스트

### Phase 1: 백엔드 `api/jobs.py` 정리

- [ ] `save_user_annotations`에서 PyMuPDF 주석 적용 제거
  - `pdf_user_annotator.apply_user_annotations` 호출 제거
  - `results` 버킷에 PDF bytes 덮어쓰기 제거
  - `source_index >= 0` 분기와 `_save_user_annotations_json` 통합
  - 반환값에서 `storage_path` 제거, `annotations_json_storage_path`만 반환
- [ ] `_create_user_annotated_pdf` 제거
  - 호출처 확인 후 제거 (dead code로 보임)
- [ ] `download_job`에서 `annotated_pdf` 타입 제거
- [ ] `_delete_annotation_file`에서 PDF 삭제 로직 정리
  - `result_annotated_pdf_storage_path` 삭제 제거
  - `annotated_pdf_files` entry 제거 + JSON 삭제만 수행
- [ ] `_source_files` 정리
  - `result_annotated_pdf_storage_path` 하위 호환 블록 제거
  - `annotated_pdf_files` entry의 `url`은 clean 원본/검색 PDF, `annotations_json_url`은 JSON 오버레이 유지
- [ ] AI annotate entry 생성/완료 시 `storage_path`를 searchable PDF로 사용
  - `shared_storage_path = f"{job.id}/annotated.pdf"` → `f"{job.id}/searchable.pdf"`
  - `result_annotated_pdf_storage_path` 설정 제거

### Phase 2: DB 모델 및 마이그레이션

- [ ] `db/models.py`에서 `result_annotated_pdf_storage_path` 컬럼 제거
- [ ] 마이그레이션 파일 추가 (`db/migrations/XXX_drop_result_annotated_pdf_storage_path.sql`)
- [ ] `annotated_pdf_files` entry에서 `storage_path`만 searchable PDF 경로로 사용

### Phase 3: `pdf_annotate_converter.py` 이름 변경

- [ ] `shared_storage_path`를 `f"{job.id}/searchable.pdf"`로 변경
- [ ] 하위 호환 `result_annotated_pdf_storage_path` 마이그레이션 블록 제거
- [ ] 관련 테스트에서 `annotated.pdf` 참조를 `searchable.pdf`로 변경

### Phase 4: 프론트엔드

- [ ] `JobResultPage.jsx`, `SourcePanel.jsx`, `api.js`에서 `annotated_pdf` 다운로드/UI 제거 확인
- [ ] 프론트엔드 `saveUserAnnotations` 호출부는 그대로 유지 (JSON-only 반환에 맞춰 로직 정리)

### Phase 5: 테스트

- [ ] `test_pdf_user_annotator_conversion.py`: `apply_user_annotations` 자체는 유지되므로 영향 없음
- [ ] `test_jobs_source_files_annotations.py`: `annotated_pdf_files` 구조 수정
- [ ] `test_pdf_annotate_converter_run.py`: `searchable.pdf` 이름 변경 반영
- [ ] `test_jobs_result_json_annotations.py`: 경로/필드 변경 반영
- [ ] `test_coord_transform.py`: 영향 없음

### Phase 6: 검증

- [ ] `cd app/backend && .venv/bin/python -m pytest tests/ -q` 통과
- [ ] `cd app/ai-backend && npm run build` 통과
- [ ] `cd app/frontend && npm run build` 통과
- [ ] 필요시 `cd app/frontend && npm run test` 통과

## 변경 파일 목록

- `app/backend/api/jobs.py`
- `app/backend/db/models.py`
- `app/backend/db/migrations/XXX_drop_result_annotated_pdf_storage_path.sql`
- `app/backend/core/pdf_annotate_converter.py`
- `app/backend/tests/test_jobs_source_files_annotations.py`
- `app/backend/tests/test_pdf_annotate_converter_run.py`
- `app/backend/tests/test_jobs_result_json_annotations.py`

## 롤백 계획

- 작업 전 `git diff` 저장
- DB 마이그레이션은 하향 마이그레이션 SQL도 함께 작성
- 각 phase 별로 커밋하여 필요 시 `git revert` 가능
