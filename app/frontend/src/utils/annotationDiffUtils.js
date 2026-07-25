// [Flow: Step 1 (이전 주석 목록과 현재 export 비교) -> Step 2 (ID 차집합 계산) -> Step 3 (삭제된 ID 배열 반환)]

/**
 * EmbedPDF AnnotationTransferItem 에서 주석 ID 를 추출한다.
 * 백엔드 _annotation_id (api/jobs/_shared.py) 와 동일한 규칙을 사용한다.
 *
 * @param {*} item - 주석 항목 ({annotation: {id, ...}} 또는 {id, ...})
 * @returns {string} 추출된 ID (없으면 빈 문자열)
 */
export function extractAnnotationId(item) {
  if (!item || typeof item !== "object") return "";
  if ("annotation" in item && item.annotation && typeof item.annotation === "object") {
    return item.annotation.id ?? "";
  }
  return item.id ?? "";
}

/**
 * [Flow: Step 1 (이전 주석 ID 집합 구성) -> Step 2 (현재 주석 ID 집합 구성)
 *       -> Step 3 (차집합 = 이전에 있었으나 현재 없는 ID) -> Step 4 (removals 배열 반환)]
 *
 * 이전에 로드된 주석 목록(previousItems) 에서 현재 export(currentItems) 에
 * 존재하지 않는 주석 ID들을 반환한다. 백엔드 save_user_annotations 의
 * accumulative merge 가 ID 기반으로 보존하므로, 삭제된 주석을 명시적으로
 * removals 로 전달해야 영구 삭제된다.
 *
 * @param {Array|null} previousItems - 이전에 로드된 주석 목록 (selectedAnnotationsJson)
 * @param {Array|null} currentItems - 현재 PdfViewer.exportAnnotations() 결과
 * @returns {string[]} 삭제된 주석 ID 배열
 */
export function computeRemovedAnnotationIds(previousItems, currentItems) {
  if (!Array.isArray(previousItems) || previousItems.length === 0) return [];
  const previousIds = new Set(
    previousItems.map(extractAnnotationId).filter((id) => Boolean(id))
  );
  if (!Array.isArray(currentItems)) return Array.from(previousIds);
  const currentIds = new Set(
    currentItems.map(extractAnnotationId).filter((id) => Boolean(id))
  );
  const removed = [];
  for (const id of previousIds) {
    if (!currentIds.has(id)) removed.push(id);
  }
  return removed;
}
