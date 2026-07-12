// [Flow: Step 1 (e-Discovery 그래프 노드에서 entity 집합 추출) -> Step 2 (주체별 group 생성)
//       -> Step 3 (anomaly edge를 source/target별로 색인) -> Step 4 (각 노드를 timeline item으로 변환)
//       -> Step 5 (날짜 누락 시 페이지 기반 가상 시점 보정) -> Step 6 (groups/items/visibleRange 반환)]
// backend pipeline_ediscovery.py assemble_graph 출력 스키마를 react-calendar-timeline용
// groups/items 구조로 변환하는 순수 유틸리티.

import moment from "moment";

/** 단일 시점 이벤트의 기본 지속 기간 — 1일 (밀리초). */
const DEFAULT_ITEM_DURATION_MS = 24 * 60 * 60 * 1000;

/** 주체(entity)의 화면 표시 순서. */
const SWIMLANE_ORDER = ["plaintiff", "defendant", "third_party", "issue"];

/** 노드 타입별 시각적 색상 토큰. */
const ENTITY_COLORS = {
  issue: { bg: "#fef2f2", border: "#ef4444", text: "#991b1b" },
  plaintiff: { bg: "#eff6ff", border: "#3b82f6", text: "#1e40af" },
  defendant: { bg: "#fffbeb", border: "#f59e0b", text: "#92400e" },
  evidence: { bg: "#ecfdf5", border: "#10b981", text: "#065f46" },
  third_party: { bg: "#faf5ff", border: "#a855f7", text: "#6b21a8" },
};

/**
 * 노드 타입에 맞는 CSS 클래스를 반환한다.
 *
 * @param {string} type - 노드 타입 (issue | plaintiff | defendant | evidence)
 * @returns {string} 타입별 클래스 문자열
 */
function getItemClassName(type) {
  return `ediscovery-timeline-item ediscovery-timeline-item--${type}`;
}

/**
 * 노드 타입에 맞는 인라인 스타일 객체를 반환한다.
 *
 * @param {string} type - 노드 타입
 * @returns {Object} React CSSProperties 객체
 */
function getItemStyle(type) {
  const colors = ENTITY_COLORS[type] || ENTITY_COLORS.evidence;
  return {
    backgroundColor: colors.bg,
    borderColor: colors.border,
    color: colors.text,
    borderWidth: 2,
    borderStyle: "solid",
    borderRadius: 6,
    fontSize: 12,
  };
}

/**
 * e-Discovery 그래프 노드에서 등장하는 주체(entity)별 group 목록을 생성한다.
 * swimlane 컨테이너 노드는 제외하며, 등장하지 않은 주체의 group은 생성하지 않는다.
 *
 * @param {Array<Object>} nodes - ediscovery_graphs.nodes
 * @returns {Array<Object>} react-calendar-timeline groups 배열
 */
export function buildTimelineGroups(nodes) {
  const present = new Set(
    nodes
      .filter((n) => n.type !== "swimlane")
      .map((n) => n.data?.entity || n.type)
      .filter((entity) => SWIMLANE_ORDER.includes(entity))
  );

  return SWIMLANE_ORDER.filter((entity) => present.has(entity)).map((entity) => ({
    id: entity,
    title: entity,
    rightTitle: "",
    stackItems: false,
  }));
}

/**
 * anomaly edge를 source/target 아이템 ID별로 색인한다.
 *
 * @param {Array<Object>} edges - ediscovery_graphs.edges
 * @returns {Map<string, Object>} item id -> { edgeIds, reasons }
 */
function buildAnomalyMap(edges) {
  const map = new Map();
  (edges || [])
    .filter((e) => e.type === "anomaly")
    .forEach((e) => {
      [e.source, e.target].forEach((id) => {
        if (!id) return;
        if (!map.has(id)) {
          map.set(id, { edgeIds: [], reasons: [] });
        }
        const entry = map.get(id);
        entry.edgeIds.push(e.id);
        if (e.data?.conflict_reason) {
          entry.reasons.push(e.data.conflict_reason);
        }
      });
    });
  return map;
}

/**
 * e-Discovery 노드와 엣지를 react-calendar-timeline용 items 배열로 변환한다.
 * - date_iso가 있으면 해당 날짜를 start_time으로 사용.
 * - date_iso가 없으면 페이지 번호를 기준으로 가상 시점을 배정해 시간순을 유지.
 * - anomaly edge에 연결된 아이템에는 anomaly 메타데이터를 주입.
 *
 * @param {Array<Object>} nodes - ediscovery_graphs.nodes
 * @param {Array<Object>} edges - ediscovery_graphs.edges
 * @returns {Array<Object>} react-calendar-timeline items 배열
 */
export function buildTimelineItems(nodes, edges = []) {
  const anomalyMap = buildAnomalyMap(edges);
  const eventNodes = nodes.filter((n) => n.type !== "swimlane");

  const pages = eventNodes.map((n) => n.data?.page).filter((p) => typeof p === "number");
  const minPage = pages.length ? Math.min(...pages) : 1;
  const maxPage = pages.length ? Math.max(...pages) : 1;
  const pageRange = Math.max(maxPage - minPage, 1);

  const now = Date.now();

  return eventNodes.map((n, idx) => {
    const type = n.type;
    const entity = n.data?.entity || type;
    const label = n.data?.label || n.id;
    const dateIso = n.data?.date || n.date_iso;
    const page = typeof n.data?.page === "number" ? n.data.page : idx + 1;

    let start;
    if (dateIso) {
      const parsed = moment(dateIso);
      start = parsed.isValid() ? parsed.valueOf() : null;
    }
    if (!start) {
      // 날짜 누락 시 페이지 번호로 가상 시점 생성
      const normalized = (page - minPage) / pageRange;
      start = now + normalized * DEFAULT_ITEM_DURATION_MS * eventNodes.length;
    }

    const end = start + DEFAULT_ITEM_DURATION_MS;
    const anomaly = anomalyMap.get(n.id);

    return {
      id: n.id,
      group: entity,
      title: label,
      start_time: start,
      end_time: end,
      canMove: true,
      canResize: "right",
      canChangeGroup: true,
      itemProps: {
        "data-type": type,
        "data-entity": entity,
        "data-issue": n.data?.issue || "",
      },
      className: getItemClassName(type),
      style: getItemStyle(type),
      data: {
        ...n.data,
        type,
        anomalyEdgeIds: anomaly?.edgeIds || [],
        anomalyReasons: anomaly?.reasons || [],
      },
    };
  });
}

/**
 * items의 시간 범위를 기준으로 타임라인 초기 가시 범위를 계산한다.
 * 좌우에 10% 여백을 추가해 모든 아이템이 한눈에 들어오도록 한다.
 *
 * @param {Array<Object>} items - react-calendar-timeline items
 * @returns {{start: number, end: number}} visibleTimeStart/End에 사용할 타임스탬프 쌍
 */
export function getTimelineVisibleRange(items) {
  if (!items.length) {
    const now = Date.now();
    return {
      start: now - 7 * DEFAULT_ITEM_DURATION_MS,
      end: now + 7 * DEFAULT_ITEM_DURATION_MS,
    };
  }

  const times = items.flatMap((i) => [i.start_time, i.end_time]);
  const min = Math.min(...times);
  const max = Math.max(...times);
  const padding = (max - min) * 0.1 || DEFAULT_ITEM_DURATION_MS;

  return { start: min - padding, end: max + padding };
}

/**
 * e-Discovery 그래프 노드를 재판정 레이아웃용으로 분류한다.
 * - plaintiff 편: entity === "plaintiff" 인 노드 (주장 + 유리한 증거/증인)
 * - defendant 편: entity === "defendant" 인 노드 (주장 + 유리한 증거/증인)
 * - third_party: entity === "third_party" 인 노드 (증인, 감정인 등)
 * - issues: type === "issue" 인 노드
 * 각 편 내에서 type 기준으로 claims(plaintiff/defendant 타입)와 evidence(evidence 타입)로 세분화.
 *
 * @param {Array<Object>} nodes - ediscovery_graphs.nodes
 * @returns {{plaintiff: {claims: Array, evidence: Array}, defendant: {claims: Array, evidence: Array}, thirdParty: Array, issues: Array}}
 */
export function categorizeNodesBySide(nodes) {
  const eventNodes = nodes.filter((n) => n.type !== "swimlane");

  const result = {
    plaintiff: { claims: [], evidence: [] },
    defendant: { claims: [], evidence: [] },
    thirdParty: [],
    issues: [],
  };

  eventNodes.forEach((n) => {
    const entity = n.data?.entity || n.type;
    const dimmed = n.data?.dimmed;

    if (n.type === "issue") {
      result.issues.push({ ...n, data: { ...n.data, dimmed } });
      return;
    }

    if (entity === "plaintiff") {
      if (n.type === "evidence") {
        result.plaintiff.evidence.push({ ...n, data: { ...n.data, dimmed } });
      } else {
        result.plaintiff.claims.push({ ...n, data: { ...n.data, dimmed } });
      }
      return;
    }

    if (entity === "defendant") {
      if (n.type === "evidence") {
        result.defendant.evidence.push({ ...n, data: { ...n.data, dimmed } });
      } else {
        result.defendant.claims.push({ ...n, data: { ...n.data, dimmed } });
      }
      return;
    }

    if (entity === "third_party") {
      result.thirdParty.push({ ...n, data: { ...n.data, dimmed } });
      return;
    }

    // 분류되지 않은 노드는 third_party에 포함
    result.thirdParty.push({ ...n, data: { ...n.data, dimmed } });
  });

  // 각 그룹을 시간순(date_iso → page) 정렬
  const sortByDate = (a, b) => {
    const da = a.data?.date || "";
    const db = b.data?.date || "";
    if (da && db) return da.localeCompare(db);
    if (da) return -1;
    if (db) return 1;
    return (a.data?.page || 0) - (b.data?.page || 0);
  };

  result.plaintiff.claims.sort(sortByDate);
  result.plaintiff.evidence.sort(sortByDate);
  result.defendant.claims.sort(sortByDate);
  result.defendant.evidence.sort(sortByDate);
  result.thirdParty.sort(sortByDate);
  result.issues.sort(sortByDate);

  return result;
}

/**
 * 선택된 쟁점 집합을 기준으로 아이템의 디밍(dimming) 플래그를 갱신한다.
 * issue 노드는 자신의 label이, 그 외 노드는 data.issue 필드가 선택 집합에 없으면 dimmed.
 *
 * @param {Array<Object>} items - 타임라인 items
 * @param {Set<string>} selectedIssues - 선택된 쟁점 라벨 집합
 * @returns {Array<Object>} dimmed 플래그가 추가된 새 items 배열
 */
export function applyIssueDimming(items, selectedIssues) {
  if (!selectedIssues || selectedIssues.size === 0) {
    return items.map((item) => ({ ...item, data: { ...item.data, dimmed: false } }));
  }

  return items.map((item) => {
    const type = item.data?.type;
    let match = false;
    if (type === "issue") {
      match = selectedIssues.has(item.data?.label || item.data?.issue || "");
    } else {
      match = selectedIssues.has(item.data?.issue || "");
    }
    return { ...item, data: { ...item.data, dimmed: !match } };
  });
}
