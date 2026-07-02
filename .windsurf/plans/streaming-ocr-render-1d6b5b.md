# Streaming OCR: render and send pages as they are ready

PDF 페이지를 모두 렌더링한 뒤 한꺼번에 OCR 요청을 보내는 대신, 페이지가 렌더링되자마자 곧바로 OCR 작업에 비동기 제출하여 렌더링과 OCR이 겹쳐 실행되도록 개선합니다. 프로그레스는 "각 페이지당 2단계(렌더 + OCR)"로 2×N 등분하여 계산합니다.

## 1. Diagnosis

- 현재 `ocr_client.render_pdf()`는 `ThreadPoolExecutor(max_workers=min(len(tasks), 16))`로 병렬 렌더링을 수행합니다. 따라서 렌더링 자체는 병렬이며, 병목은 "모든 렌더링이 끝난 뒤에야 OCR이 시작"되는 점입니다.
- `render_pdf`는 `fitz` 문서를 스레드별로 독립 열기 때문에 스레드 안전합니다.
- 렌더링 워커를 16에서 64로 증가하여 더 많은 페이지를 동시에 렌더링합니다.

## 2. Changes

### 2.1 `app/backend/core/ocr_client.py`

- `render_pdf()`에 `on_page_rendered: Callable[[int, Path], None] | None = None` 파라미터를 추가합니다.
- 페이지 렌더가 완료될 때마다 `on_page_rendered(page_idx, img_path)`를 호출합니다.
- 기존 반환값(`list[Path]`)과 동작은 그대로 유지하여 하위 호환성을 보장합니다.
- `on_progress`는 별도로 유지하거나, `run_vision`에서 통합 관리하도록 조정합니다.

### 2.2 `app/backend/core/pipeline_vision.py`

- `run_vision()` 내부에서:
  1. PDF를 열어 `total_pages`를 미리 계산합니다.
  2. OCR용 `ThreadPoolExecutor`를 하나 생성합니다.
  3. `on_page_rendered` 콜백을 정의합니다. 콜백은:
     - 렌더 완료 카운트를 증가시키고 프로그레스를 갱신합니다.
     - 완료된 페이지를 OCR executor에 즉시 `submit`합니다.
  4. OCR 작업 래퍼(`process_page`)는 OCR 수행 후 완료 카운트를 증가시키고 프로그레스를 갱신합니다.
  5. 프로그레스 공식: `(rendered_count + ocr_done_count) / (2 * total_pages) * 100`.
  6. `render_pdf()`가 반환되면(모든 렌더 완료) 남은 OCR future를 모두 기다립니다.
- 기존 0~35%/35~100% 분할 코드는 제거하고 새로운 통합 프로그레스로 교체합니다.
- 스레드 간 카운터/결과 동기화를 위해 `threading.Lock`을 사용합니다.

### 2.3 `app/backend/compare_ocr.py`

- `render_pdf()` 반환값이 바뀌지 않으므로 변경 없음(하위 호환 유지).

### 2.4 `AGENTS.md`

- "OCR Progress Reporting" 섹션을 스트리밍 파이프라인에 맞게 갱신합니다.
- "Large Image Tiling" 섹션에서 `render_pdf`가 콜백을 받는 점을 언급합니다.

## 3. Verification

- `python3 -m py_compile`으로 구문 오류를 확인합니다.
- a1 배포 후 실제 PDF로 렌더링/OCR 겹침 및 프로그레스가 0%부터 상승하는지 확인합니다.

## 4. Deployment

- `git add` → `git commit` → `git push` → `bash deploy_a1.sh` 순으로 진행합니다.
