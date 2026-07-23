// [Flow: Step 1 (dev bypass 자동 로그인) -> Step 2 (PagedResultViewer와 동일한 Panel 설정 직접 렌더링)
//       -> Step 3 (패널 토글 버튼으로 좌·우 패널 expand/collapse) -> Step 4 (패널 ref의 getSize/isCollapsed + DOM 너비 측정)
//       -> Step 5 (모든 상태를 텍스트 로그로 출력하여 비전 없이도 패널 상태 파악)]
// 마크다운 페이지의 패널 보이기/숨기기 버튼이 패널을 완전히 숨기지 못하는 문제를 진단하는 디버깅 전용 페이지.
// 로컬 데브모드에서 로그인 없이 작동하며, 패널의 실제 크기(%), collapsed 여부, DOM 픽셀 너비를 로그로 출력한다.
import { useCallback, useEffect, useRef, useState } from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { api } from "../api.js";
import PagedResultViewer from "../components/PagedResultViewer.jsx";

// [Flow: 로그 엔트리 — 타임스탬프, 레벨, 카테고리, 메시지, 상세 데이터]
function makeLog(level, category, message, data) {
  return {
    time: new Date().toLocaleTimeString("ko-KR", { hour12: false }) + "." + String(Date.now() % 1000).padStart(3, "0"),
    level,
    category,
    message,
    data: data !== undefined ? data : null,
  };
}

// [Flow: Step 1 (dev/login 호출로 bypass 토큰 획득) -> Step 2 (localStorage 저장) -> Step 3 (성공/실패 로그)]
async function ensureDevLogin(addLog) {
  addLog("info", "auth", "dev bypass 로그인 시도");
  try {
    const resp = await fetch(`${window.location.origin}/api/dev/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
    if (!resp.ok) {
      const text = await resp.text();
      addLog("error", "auth", `dev login 실패: ${resp.status}`, text);
      return false;
    }
    const data = await resp.json();
    localStorage.setItem("dev_access_token", data.access_token);
    localStorage.setItem("dev_refresh_token", data.refresh_token);
    localStorage.setItem("dev_user", JSON.stringify(data.user));
    localStorage.setItem("dev_bypass_mode", "apikey");
    addLog("info", "auth", `dev login 성공: ${data.user?.email}`, { userId: data.user?.id });
    return true;
  } catch (e) {
    addLog("error", "auth", `dev login 예외: ${e.message}`);
    return false;
  }
}

// localStorage 패널 상태 키 (JobResultPage.jsx와 동일)
const PANEL_STATE_STORAGE_KEY = "proof:panelState";

function readPanelState() {
  try {
    const raw = localStorage.getItem(PANEL_STATE_STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export default function DebugPanelTogglePage() {
  const [logs, setLogs] = useState([]);
  // [Flow: 패널 토글 상태 — JobResultPage와 동일하게 localStorage에서 초기값 로드]
  const [leftPanelOpen, setLeftPanelOpen] = useState(() => {
    const s = readPanelState();
    return s ? s.sidebarOpen !== false : true;
  });
  const [rightPanelOpen, setRightPanelOpen] = useState(() => {
    const s = readPanelState();
    return s ? s.rightPanelOpen !== false : true;
  });
  // [Flow: 패널 ref — getSize()/isCollapsed()로 실제 패널 상태 캡처]
  const leftPanelRef = useRef(null);
  const rightPanelRef = useRef(null);
  // [Flow: DOM 요소 ref — getBoundingClientRect().width로 실제 픽셀 너비 측정]
  const containerRef = useRef(null);
  // [Flow: 실제 PagedResultViewer 컨테이너 ref — 별도 측정]
  const actualViewerRef = useRef(null);
  const logEndRef = useRef(null);
  // [Flow: 패널 상태 스냅샷 — 주기적으로 갱신하여 화면에 표시]
  const [snapshot, setSnapshot] = useState({
    leftSize: null,
    leftCollapsed: null,
    leftDomWidth: null,
    rightSize: null,
    rightCollapsed: null,
    rightDomWidth: null,
    containerWidth: null,
    storedState: null,
    // [Flow: 실제 PagedResultViewer 내부 패널 DOM 너비]
    actualLeftWidth: null,
    actualRightWidth: null,
    actualLeftStyle: null,
    actualRightStyle: null,
  });

  const addLog = useCallback((level, category, message, data) => {
    setLogs((prev) => [...prev, makeLog(level, category, message, data)]);
  }, []);

  // [Flow: 로그 패널 자동 스크롤]
  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  // [Flow: Step 1 (페이지 마운트 시 dev bypass 로그인)]
  useEffect(() => {
    (async () => {
      await ensureDevLogin(addLog);
      addLog("info", "init", "디버그 페이지 초기화", {
        leftPanelOpen,
        rightPanelOpen,
        storedState: readPanelState(),
      });
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // [Flow: Step 1 (leftPanelOpen 변경) -> Step 2 (패널 ref expand/collapse 호출) -> Step 3 (로그)]
  useEffect(() => {
    if (!leftPanelRef.current) return;
    addLog("info", "left-toggle", `leftPanelOpen=${leftPanelOpen} → ${leftPanelOpen ? "expand()" : "collapse()"}`);
    if (leftPanelOpen) {
      leftPanelRef.current.expand();
    } else {
      leftPanelRef.current.collapse();
    }
  }, [leftPanelOpen, addLog]);

  // [Flow: Step 1 (rightPanelOpen 변경) -> Step 2 (패널 ref expand/collapse 호출) -> Step 3 (로그)]
  useEffect(() => {
    if (!rightPanelRef.current) return;
    addLog("info", "right-toggle", `rightPanelOpen=${rightPanelOpen} → ${rightPanelOpen ? "expand()" : "collapse()"}`);
    if (rightPanelOpen) {
      rightPanelRef.current.expand();
    } else {
      rightPanelRef.current.collapse();
    }
  }, [rightPanelOpen, addLog]);

  // [Flow: localStorage에 패널 상태 저장 — JobResultPage와 동일 로직]
  useEffect(() => {
    try {
      localStorage.setItem(
        PANEL_STATE_STORAGE_KEY,
        JSON.stringify({ sidebarOpen: leftPanelOpen, rightPanelOpen })
      );
      addLog("info", "storage", `localStorage 저장: ${PANEL_STATE_STORAGE_KEY}`, {
        sidebarOpen: leftPanelOpen,
        rightPanelOpen,
      });
    } catch {
      addLog("warn", "storage", "localStorage 저장 실패 (quota?)");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [leftPanelOpen, rightPanelOpen]);

  // [Flow: Step 1 (200ms 간격으로 패널 상태 스냅샷 캡처)
  //       -> Step 2 (getSize()/isCollapsed()로 패널 ref 상태)
  //       -> Step 3 (DOM 요소 getBoundingClientRect로 실제 픽셀 너비)
  //       -> Step 4 (스냅샷 상태 갱신하여 화면에 표시)]
  useEffect(() => {
    const capture = () => {
      const container = containerRef.current;
      const containerWidth = container?.getBoundingClientRect().width || null;
      // data-panel-side 속성으로 좌/우 패널 DOM 요소 찾기
      const leftDom = container?.querySelector('[data-panel-side="left"]');
      const rightDom = container?.querySelector('[data-panel-side="right"]');
      const leftDomWidth = leftDom?.getBoundingClientRect().width || null;
      const rightDomWidth = rightDom?.getBoundingClientRect().width || null;

      const leftSize = leftPanelRef.current?.getSize?.() ?? null;
      const leftCollapsed = leftPanelRef.current?.isCollapsed?.() ?? null;
      const rightSize = rightPanelRef.current?.getSize?.() ?? null;
      const rightCollapsed = rightPanelRef.current?.isCollapsed?.() ?? null;

      // [Flow: 실제 PagedResultViewer 내부 패널 DOM 측정 — 별도 컨테이너에서 검색]
      const actualContainer = actualViewerRef.current;
      const actualLeft = actualContainer?.querySelector('[data-panel-side="left"]');
      const actualRight = actualContainer?.querySelector('[data-panel-side="right"]');

      setSnapshot({
        leftSize,
        leftCollapsed,
        leftDomWidth,
        rightSize,
        rightCollapsed,
        rightDomWidth,
        containerWidth,
        storedState: readPanelState(),
        actualLeftWidth: actualLeft?.getBoundingClientRect().width || null,
        actualRightWidth: actualRight?.getBoundingClientRect().width || null,
        actualLeftStyle: actualLeft?.getAttribute("style"),
        actualRightStyle: actualRight?.getAttribute("style"),
      });
    };
    // 최초 1회 + 200ms 간격 폴링
    capture();
    const interval = setInterval(capture, 200);
    return () => clearInterval(interval);
  }, []);

  // [Flow: 스냅샷 변화 시 로그 — 패널 크기가 0이 아닌데 collapsed=true인 경우 등 이상 상태 감지]
  const prevSnapshotRef = useRef(null);
  useEffect(() => {
    const prev = prevSnapshotRef.current;
    if (!prev) {
      prevSnapshotRef.current = { ...snapshot };
      return;
    }
    // 유의미한 변화가 있을 때만 로그 출력 (노이즈 방지)
    const changed =
      prev.leftSize !== snapshot.leftSize ||
      prev.rightSize !== snapshot.rightSize ||
      prev.leftCollapsed !== snapshot.leftCollapsed ||
      prev.rightCollapsed !== snapshot.rightCollapsed;
    if (!changed) return;

    addLog("debug", "snapshot", "패널 상태 변화", {
      left: { size: snapshot.leftSize, collapsed: snapshot.leftCollapsed, domW: snapshot.leftDomWidth },
      right: { size: snapshot.rightSize, collapsed: snapshot.rightCollapsed, domW: snapshot.rightDomWidth },
      containerW: snapshot.containerWidth,
    });
    prevSnapshotRef.current = { ...snapshot };
  }, [snapshot, addLog]);

  const toggleLeft = () => setLeftPanelOpen((v) => !v);
  const toggleRight = () => setRightPanelOpen((v) => !v);
  const resetStorage = () => {
    localStorage.removeItem(PANEL_STATE_STORAGE_KEY);
    addLog("warn", "storage", `${PANEL_STATE_STORAGE_KEY} 삭제 (초기화)`);
    setLeftPanelOpen(true);
    setRightPanelOpen(true);
  };

  // [Flow: 로그 레벨별 색상]
  const levelColor = (lvl) => ({
    info: "text-blue-700",
    warn: "text-amber-700",
    error: "text-red-700",
    debug: "text-gray-600",
  }[lvl] || "text-gray-700");

  return (
    <div className="h-screen flex flex-col bg-gray-50">
      {/* 헤더 — 패널 토글 버튼 + 현재 상태 요약 */}
      <div className="flex-shrink-0 bg-white border-b border-gray-200 px-4 py-3">
        <h1 className="text-lg font-bold text-gray-900 mb-2">패널 토글 디버그 페이지</h1>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={toggleLeft}
            className={`px-3 py-2 rounded-lg font-medium text-sm border transition-colors ${
              leftPanelOpen
                ? "bg-blue-100 text-blue-800 border-blue-300"
                : "bg-gray-100 text-gray-600 border-gray-300"
            }`}
          >
            좌 패널: {leftPanelOpen ? "열림" : "닫힘"}
          </button>
          <button
            onClick={toggleRight}
            className={`px-3 py-2 rounded-lg font-medium text-sm border transition-colors ${
              rightPanelOpen
                ? "bg-blue-100 text-blue-800 border-blue-300"
                : "bg-gray-100 text-gray-600 border-gray-300"
            }`}
          >
            우 패널: {rightPanelOpen ? "열림" : "닫힘"}
          </button>
          <button
            onClick={resetStorage}
            className="px-3 py-2 rounded-lg font-medium text-sm border bg-amber-100 text-amber-800 border-amber-300 hover:bg-amber-200 transition-colors"
          >
            localStorage 초기화
          </button>
        </div>
        {/* 실시간 스냅샷 요약 — 비전 없이도 패널 상태를 즉시 파악 */}
        <div className="mt-3 grid grid-cols-2 gap-2 text-xs font-mono">
          <div className="bg-gray-100 rounded p-2">
            <div className="font-bold text-gray-700 mb-1">좌 패널 (leftPanelRef)</div>
            <div>getSize(): <span className="font-bold text-blue-700">{snapshot.leftSize ?? "N/A"}</span>%</div>
            <div>isCollapsed(): <span className="font-bold">{String(snapshot.leftCollapsed ?? "N/A")}</span></div>
            <div>DOM 너비: <span className="font-bold text-green-700">{snapshot.leftDomWidth ?? "N/A"}</span>px</div>
          </div>
          <div className="bg-gray-100 rounded p-2">
            <div className="font-bold text-gray-700 mb-1">우 패널 (rightPanelRef)</div>
            <div>getSize(): <span className="font-bold text-blue-700">{snapshot.rightSize ?? "N/A"}</span>%</div>
            <div>isCollapsed(): <span className="font-bold">{String(snapshot.rightCollapsed ?? "N/A")}</span></div>
            <div>DOM 너비: <span className="font-bold text-green-700">{snapshot.rightDomWidth ?? "N/A"}</span>px</div>
          </div>
          <div className="bg-gray-100 rounded p-2 col-span-2">
            <div className="font-bold text-gray-700 mb-1">컨테이너 & localStorage</div>
            <div>컨테이너 너비: {snapshot.containerWidth ?? "N/A"}px</div>
            <div>localStorage: {JSON.stringify(snapshot.storedState)}</div>
          </div>
        </div>
      </div>

      {/* 패널 테스트 영역 — PagedResultViewer.jsx와 동일한 Panel 설정 */}
      <div ref={containerRef} className="flex-1 flex flex-col overflow-hidden min-h-0">
        <PanelGroup direction="horizontal" className="flex-1 overflow-hidden">
          <Panel
            ref={leftPanelRef}
            defaultSize={45}
            minSize={25}
            maxSize={rightPanelOpen ? 70 : 100}
            collapsible
            collapsedSize={0}
            className="overflow-hidden bg-blue-50 border-r border-blue-200"
            data-panel-side="left"
          >
            <div className="p-4 h-full overflow-auto">
              <h2 className="font-bold text-blue-900 mb-2">좌 패널 (원본 영역)</h2>
              <p className="text-sm text-gray-700">이 패널은 PagedResultViewer의 좌 패널과 동일한 설정을 사용합니다.</p>
              <ul className="text-xs text-gray-500 mt-2 space-y-1">
                <li>defaultSize=45, minSize=25</li>
                <li>maxSize={rightPanelOpen ? 70 : 100} (동적)</li>
                <li>collapsible, collapsedSize=0</li>
              </ul>
            </div>
          </Panel>
          <PanelResizeHandle className="w-1 bg-gray-300 hover:bg-blue-400 transition-colors" />
          <Panel
            ref={rightPanelRef}
            defaultSize={55}
            minSize={30}
            maxSize={leftPanelOpen ? 75 : 100}
            collapsible
            collapsedSize={0}
            className="flex flex-col bg-green-50 overflow-hidden"
            data-panel-side="right"
          >
            <div className="p-4 h-full overflow-auto">
              <h2 className="font-bold text-green-900 mb-2">우 패널 (마크다운 영역)</h2>
              <p className="text-sm text-gray-700">이 패널은 PagedResultViewer의 우 패널과 동일한 설정을 사용합니다.</p>
              <ul className="text-xs text-gray-500 mt-2 space-y-1">
                <li>defaultSize=55, minSize=30</li>
                <li>maxSize={leftPanelOpen ? 75 : 100} (동적)</li>
                <li>collapsible, collapsedSize=0</li>
              </ul>
            </div>
          </Panel>
        </PanelGroup>
      </div>

      {/* 실제 PagedResultViewer 테스트 영역 — 실제 컴포넌트를 렌더링하여 패널 동작 비교 */}
      <div className="flex-shrink-0 bg-purple-50 border-t-2 border-purple-300 px-4 py-2">
        <h3 className="text-sm font-bold text-purple-900 mb-1">실제 PagedResultViewer 컴포넌트 테스트</h3>
        <div className="text-xs text-purple-700 mb-2 font-mono">
          actualLeftWidth: {snapshot.actualLeftWidth ?? "N/A"}px |
          actualRightWidth: {snapshot.actualRightWidth ?? "N/A"}px
        </div>
        <div className="text-xs text-purple-600 mb-1 font-mono break-all">
          left style: {snapshot.actualLeftStyle || "N/A"}
        </div>
        <div className="text-xs text-purple-600 mb-2 font-mono break-all">
          right style: {snapshot.actualRightStyle || "N/A"}
        </div>
      </div>
      <div ref={actualViewerRef} className="flex-1 flex flex-col overflow-hidden min-h-0 border-t border-purple-200">
        <PagedResultViewer
          jobId="debug-dummy-job"
          pages={[{ page_num: 1 }]}
          sourceFiles={[]}
          sourceUrl={null}
          sourceType="pdf"
          imageUrls={[]}
          onSaveAnnotations={() => {}}
          onUpload={() => {}}
          leftPanelOpen={leftPanelOpen}
          rightPanelOpen={rightPanelOpen}
        />
      </div>

      {/* 로그 패널 — 모든 패널 상태 변화를 텍스트로 출력 */}
      <div className="flex-shrink-0 h-64 bg-gray-900 text-gray-100 overflow-auto p-3 font-mono text-xs">
        <div className="text-gray-400 mb-2">=== 로그 (최신 하단) ===</div>
        {logs.length === 0 && <div className="text-gray-500">로그 없음</div>}
        {logs.map((log, i) => (
          <div key={i} className="mb-1">
            <span className="text-gray-500">{log.time}</span>{" "}
            <span className={`font-bold ${levelColor(log.level)}`}>[{log.level.toUpperCase()}]</span>{" "}
            <span className="text-yellow-300">[{log.category}]</span>{" "}
            <span>{log.message}</span>
            {log.data && (
              <span className="text-gray-400"> {JSON.stringify(log.data)}</span>
            )}
          </div>
        ))}
        <div ref={logEndRef} />
      </div>
    </div>
  );
}
