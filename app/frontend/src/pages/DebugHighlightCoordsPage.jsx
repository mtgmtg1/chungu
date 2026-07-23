// [Flow: Step 1 (dev bypass 자동 로그인) -> Step 2 (job/query/page 입력) -> Step 3 (백엔드 debug/highlight-coords 호출)
//       -> Step 4 (PNG 이미지 + 좌표 오버레이 렌더링: search_for=빨강, text_blocks=파랑, ocr=초록, spans=노랑)
//       -> Step 5 (각 단계 로그 캡처 + 어긋남 분석 결과 출력)]
// 스캔 PDF searchable 텍스트 레이어의 하이라이트 좌표 어긋남을 시각적으로 진단하는 디버깅 전용 페이지.
import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api.js";

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

// [Flow: 두 bbox(device-space)가 얼마나 어긋나는지 계산 — dx, dy(중심점 기준)]
function computeOffset(a, b) {
  if (!a || !b) return null;
  const acx = (a[0] + a[2]) / 2;
  const acy = (a[1] + a[3]) / 2;
  const bcx = (b[0] + b[2]) / 2;
  const bcy = (b[1] + b[3]) / 2;
  return { dx: Math.round((acx - bcx) * 100) / 100, dy: Math.round((acy - bcy) * 100) / 100 };
}

// [Flow: search_for rect와 가장 가까운 text_block/ocr_element를 매칭하여 어긋남 추정]
function analyzeMismatch(result) {
  const findings = [];
  if (!result) return findings;
  const { search_for_rects: sfr, text_blocks: tbs, ocr_elements: ocrs, is_likely_scan } = result;
  findings.push({
    type: "info",
    msg: `스캔 PDF 추정: ${is_likely_scan ? "예 (텍스트 레이어 거의 없음)" : "아니오 (텍스트 레이어 존재)"}`,
  });
  findings.push({
    type: "info",
    msg: `search_for 매치: ${sfr?.length || 0}건 / text_blocks: ${tbs?.length || 0}개 / ocr_elements: ${ocrs?.length || 0}개`,
  });
  if (!sfr || sfr.length === 0) {
    findings.push({ type: "warn", msg: "search_for가 0건 — query가 텍스트 레이어에 없거나 텍스트 레이어 자체가 비어있음" });
    return findings;
  }
  // 각 search_for rect에 대해 가장 가까운 text_block 찾기
  for (let i = 0; i < sfr.length; i++) {
    const sf = sfr[i];
    let best = null;
    let bestDist = Infinity;
    for (const tb of tbs || []) {
      if (!tb.text) continue;
      const off = computeOffset(sf.device, tb.device);
      if (!off) continue;
      const dist = Math.hypot(off.dx, off.dy);
      if (dist < bestDist) {
        bestDist = dist;
        best = { tb, off, dist };
      }
    }
    if (best && best.dist < 200) {
      const severity = best.dist < 5 ? "ok" : best.dist < 30 ? "warn" : "error";
      findings.push({
        type: severity,
        msg: `search_for[${i}] '${sf.text.slice(0, 30)}' ↔ text_block '${best.tb.text.slice(0, 30)}' → dx=${best.off.dx}, dy=${best.off.dy} (dist=${Math.round(best.dist)})`,
      });
    } else if (ocrs && ocrs.length > 0) {
      // OCR element와 비교
      let bestOcr = null;
      let bestOcrDist = Infinity;
      for (const oc of ocrs) {
        const off = computeOffset(sf.device, oc.device);
        if (!off) continue;
        const dist = Math.hypot(off.dx, off.dy);
        if (dist < bestOcrDist) {
          bestOcrDist = dist;
          bestOcr = { oc, off, dist };
        }
      }
      if (bestOcr) {
        const severity = bestOcr.dist < 5 ? "ok" : bestOcr.dist < 30 ? "warn" : "error";
        findings.push({
          type: severity,
          msg: `search_for[${i}] '${sf.text.slice(0, 30)}' ↔ ocr_element '${bestOcr.oc.text.slice(0, 30)}' → dx=${bestOcr.off.dx}, dy=${bestOcr.off.dy} (dist=${Math.round(bestOcr.dist)})`,
        });
      }
    } else {
      findings.push({
        type: "warn",
        msg: `search_for[${i}] '${sf.text.slice(0, 30)}' 매칭되는 text_block/ocr_element 없음 (가장 가까운 블록까지 dist=${Math.round(bestDist)})`,
      });
    }
  }
  return findings;
}

const LAYER_COLORS = {
  search_for: "#ff3b30",
  text_blocks: "#007aff",
  ocr_elements: "#34c759",
  detailed_spans: "#ffcc00",
};

export default function DebugHighlightCoordsPage() {
  const [searchParams] = useSearchParams();
  const [logs, setLogs] = useState([]);
  const [jobId, setJobId] = useState(searchParams.get("jobId") || "");
  const [query, setQuery] = useState(searchParams.get("query") || "");
  const [pageNo, setPageNo] = useState(parseInt(searchParams.get("page") || "1", 10));
  const [dpi, setDpi] = useState(150);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [layers, setLayers] = useState({
    search_for: true,
    text_blocks: true,
    ocr_elements: true,
    detailed_spans: false,
  });
  const [findings, setFindings] = useState([]);
  const logEndRef = useRef(null);

  const addLog = useCallback((level, category, message, data) => {
    setLogs((prev) => [...prev, makeLog(level, category, message, data)]);
  }, []);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  // [Flow: Step 1 (페이지 마운트 시 dev bypass 로그인)]
  useEffect(() => {
    ensureDevLogin(addLog);
  }, [addLog]);

  // [Flow: Step 1 (백엔드 debug/highlight-coords 호출) -> Step 2 (결과 저장 + 분석) -> Step 3 (로그)]
  async function runDebug() {
    if (!jobId || !query) return;
    setLoading(true);
    setResult(null);
    setFindings([]);
    addLog("info", "api", `GET /api/jobs/${jobId}/debug/highlight-coords`, { query, page_no: pageNo, dpi });
    try {
      const data = await api.debugHighlightCoords(jobId, { query, page_no: pageNo, dpi });
      setResult(data);
      addLog("info", "api", `응답 수신`, {
        page_rect: data.page_rect,
        image: `${data.image_width}x${data.image_height}`,
        search_for: data.search_for_rects?.length,
        text_blocks: data.text_blocks?.length,
        ocr_elements: data.ocr_elements?.length,
        is_likely_scan: data.is_likely_scan,
        full_text_length: data.full_text_length,
      });
      const f = analyzeMismatch(data);
      setFindings(f);
      for (const finding of f) {
        addLog(finding.type === "ok" ? "info" : finding.type === "warn" ? "warn" : "error", "analysis", finding.msg);
      }
    } catch (e) {
      addLog("error", "api", `호출 실패: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }

  function toggleLayer(name) {
    setLayers((prev) => ({ ...prev, [name]: !prev[name] }));
  }

  const imgSrc = result ? `data:image/png;base64,${result.image_base64}` : null;
  const W = result?.image_width || 0;
  const H = result?.image_height || 0;

  return (
    <div style={{ padding: 16, fontFamily: "monospace", fontSize: 13, color: "#222" }}>
      <h1 style={{ fontSize: 18, margin: "0 0 12px" }}>Debug: 하이라이트 좌표 어긋남 진단 (스캔 PDF)</h1>
      <p style={{ fontSize: 12, color: "#666", margin: "0 0 12px" }}>
        로그인 우회 자동 적용. job ID + 검색어 + 페이지 입력 후 실행하면 searchable PDF 페이지 이미지 위에
        search_for(빨강), text_blocks(파랑), ocr_elements(초록), detailed_spans(노랑) 좌표를 오버레이한다.
      </p>

      {/* 입력 폼 */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
        <input
          placeholder="job ID"
          value={jobId}
          onChange={(e) => setJobId(e.target.value)}
          style={{ flex: "1 1 240px", padding: 6, border: "1px solid #ccc" }}
        />
        <input
          placeholder="검색어 (query)"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ flex: "1 1 200px", padding: 6, border: "1px solid #ccc" }}
        />
        <input
          type="number"
          placeholder="page"
          value={pageNo}
          onChange={(e) => setPageNo(parseInt(e.target.value || "1", 10))}
          style={{ width: 70, padding: 6, border: "1px solid #ccc" }}
        />
        <input
          type="number"
          placeholder="dpi"
          value={dpi}
          onChange={(e) => setDpi(parseInt(e.target.value || "150", 10))}
          style={{ width: 70, padding: 6, border: "1px solid #ccc" }}
        />
        <button
          onClick={runDebug}
          disabled={loading || !jobId || !query}
          style={{ padding: "6px 16px", background: "#007aff", color: "#fff", border: "none", borderRadius: 4 }}
        >
          {loading ? "실행 중..." : "실행"}
        </button>
      </div>

      {/* 레이어 토글 */}
      <div style={{ display: "flex", gap: 12, marginBottom: 12, fontSize: 12 }}>
        {Object.entries(LAYER_COLORS).map(([name, color]) => (
          <label key={name} style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <input type="checkbox" checked={layers[name]} onChange={() => toggleLayer(name)} />
            <span style={{ width: 12, height: 12, background: color, display: "inline-block", border: "1px solid #000" }} />
            {name}
          </label>
        ))}
      </div>

      {/* 분석 결과 요약 */}
      {findings.length > 0 && (
        <div style={{ marginBottom: 12, padding: 8, background: "#f5f5f5", border: "1px solid #ddd", borderRadius: 4 }}>
          <strong>분석 결과:</strong>
          <ul style={{ margin: "4px 0 0 16px", padding: 0 }}>
            {findings.map((f, i) => (
              <li key={i} style={{
                color: f.type === "ok" ? "#34c759" : f.type === "warn" ? "#ff9500" : f.type === "error" ? "#ff3b30" : "#666",
              }}>
                [{f.type}] {f.msg}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 자동 검증 결과 (PASS/FAIL) */}
      {result?.validation && (
        <div style={{
          marginBottom: 12, padding: 12, borderRadius: 4,
          background: result.validation.status === "pass" ? "#d4edda"
                    : result.validation.status === "fail" ? "#f8d7da"
                    : "#fff3cd",
          border: `2px solid ${
            result.validation.status === "pass" ? "#28a745"
            : result.validation.status === "fail" ? "#dc3545"
            : "#ffc107"
          }`,
        }}>
          <div style={{
            fontSize: 18, fontWeight: "bold", marginBottom: 8,
            color: result.validation.status === "pass" ? "#155724"
                 : result.validation.status === "fail" ? "#721c24"
                 : "#856404",
          }}>
            {result.validation.status === "pass" ? "✅ PASS" : result.validation.status === "fail" ? "❌ FAIL" : "⚠️ WARN"} — {result.validation.summary}
          </div>
          <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ background: "rgba(0,0,0,0.05)" }}>
                <th style={{ padding: 4, textAlign: "left", border: "1px solid #ccc" }}>검사 항목</th>
                <th style={{ padding: 4, textAlign: "center", border: "1px solid #ccc", width: 60 }}>결과</th>
                <th style={{ padding: 4, textAlign: "left", border: "1px solid #ccc" }}>상세</th>
              </tr>
            </thead>
            <tbody>
              {result.validation.checks.map((c, i) => (
                <tr key={i}>
                  <td style={{ padding: 4, border: "1px solid #ddd" }}>{c.name}</td>
                  <td style={{
                    padding: 4, border: "1px solid #ddd", textAlign: "center",
                    fontWeight: "bold",
                    color: c.status === "pass" ? "#28a745" : c.status === "fail" ? "#dc3545" : "#856404",
                  }}>
                    {c.status === "pass" ? "PASS" : c.status === "fail" ? "FAIL" : "WARN"}
                  </td>
                  <td style={{ padding: 4, border: "1px solid #ddd" }}>{c.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 이미지 + 오버레이 */}
      {imgSrc && (
        <div style={{ position: "relative", display: "inline-block", border: "1px solid #999", marginBottom: 12, maxWidth: "100%" }}>
          <img src={imgSrc} alt="page" style={{ display: "block", maxWidth: "100%", height: "auto" }} />
          <svg
            width={W}
            height={H}
            viewBox={`0 0 ${W} ${H}`}
            style={{ position: "absolute", top: 0, left: 0, width: "100%", height: "100%", pointerEvents: "none" }}
          >
            {layers.text_blocks && (result.text_blocks || []).map((b, i) => {
              const [x0, y0, x1, y1] = b.pixel;
              return (
                <g key={`tb-${i}`}>
                  <rect x={x0} y={y0} width={x1 - x0} height={y1 - y0}
                        fill={LAYER_COLORS.text_blocks} fillOpacity={0.12}
                        stroke={LAYER_COLORS.text_blocks} strokeWidth={1} />
                </g>
              );
            })}
            {layers.ocr_elements && (result.ocr_elements || []).map((b, i) => {
              const [x0, y0, x1, y1] = b.pixel;
              return (
                <g key={`ocr-${i}`}>
                  <rect x={x0} y={y0} width={x1 - x0} height={y1 - y0}
                        fill={LAYER_COLORS.ocr_elements} fillOpacity={0.1}
                        stroke={LAYER_COLORS.ocr_elements} strokeWidth={1} strokeDasharray="3 2" />
                </g>
              );
            })}
            {layers.detailed_spans && (result.detailed_spans || []).map((b, i) => {
              const [x0, y0, x1, y1] = b.pixel;
              return (
                <g key={`sp-${i}`}>
                  <rect x={x0} y={y0} width={x1 - x0} height={y1 - y0}
                        fill="none" stroke={LAYER_COLORS.detailed_spans} strokeWidth={0.5} />
                </g>
              );
            })}
            {layers.search_for && (result.search_for_rects || []).map((b, i) => {
              const [x0, y0, x1, y1] = b.pixel;
              return (
                <g key={`sf-${i}`}>
                  <rect x={x0} y={y0} width={x1 - x0} height={y1 - y0}
                        fill={LAYER_COLORS.search_for} fillOpacity={0.25}
                        stroke={LAYER_COLORS.search_for} strokeWidth={2} />
                  <text x={x0} y={y0 - 2} fill={LAYER_COLORS.search_for} fontSize={10} fontWeight="bold">
                    #{i} {b.text.slice(0, 20)}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
      )}

      {/* 상세 좌표 테이블 */}
      {result && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 12 }}>
          <CoordTable title="search_for (빨강 — 하이라이트가 찍히는 위치)" rows={result.search_for_rects} />
          <CoordTable title="text_blocks (파랑 — PDF 텍스트 레이어 실제 위치)" rows={result.text_blocks} />
          <CoordTable title="ocr_elements (초록 — OCR layout bbox)" rows={result.ocr_elements} />
          <CoordTable title="detailed_spans (노랑 — 정밀 span)" rows={result.detailed_spans} />
        </div>
      )}

      {/* 로그 패널 */}
      <div style={{ background: "#1e1e1e", color: "#d4d4d4", padding: 8, borderRadius: 4, maxHeight: 360, overflowY: "auto" }}>
        {logs.map((log, i) => (
          <div key={i} style={{ borderBottom: "1px solid #333", padding: "2px 0" }}>
            <span style={{ color: "#888" }}>{log.time}</span>{" "}
            <span style={{
              color: log.level === "error" ? "#ff3b30" : log.level === "warn" ? "#ff9500" : "#4fc3f7",
              fontWeight: "bold",
            }}>[{log.level}]</span>{" "}
            <span style={{ color: "#aaa" }}>({log.category})</span>{" "}
            <span>{log.message}</span>
            {log.data && (
              <pre style={{ color: "#9cdcfe", margin: "2px 0 4px 16px", fontSize: 11, whiteSpace: "pre-wrap" }}>
                {typeof log.data === "string" ? log.data : JSON.stringify(log.data, null, 2)}
              </pre>
            )}
          </div>
        ))}
        <div ref={logEndRef} />
      </div>
    </div>
  );
}

// [Flow: 좌표 테이블 — device/pixel bbox + text를 표 형태로 출력]
function CoordTable({ title, rows }) {
  if (!rows || rows.length === 0) {
    return (
      <div style={{ border: "1px solid #ddd", padding: 6, borderRadius: 4, fontSize: 11 }}>
        <strong>{title}</strong>
        <div style={{ color: "#999" }}>(없음)</div>
      </div>
    );
  }
  return (
    <div style={{ border: "1px solid #ddd", padding: 6, borderRadius: 4, fontSize: 11, maxHeight: 240, overflowY: "auto" }}>
      <strong>{title}</strong>
      <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 4 }}>
        <thead>
          <tr style={{ background: "#f0f0f0" }}>
            <th style={{ textAlign: "left", padding: 2 }}>#</th>
            <th style={{ textAlign: "left", padding: 2 }}>device (x0,y0,x1,y1)</th>
            <th style={{ textAlign: "left", padding: 2 }}>text</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} style={{ borderBottom: "1px solid #eee" }}>
              <td style={{ padding: 2 }}>{i}</td>
              <td style={{ padding: 2, color: "#555" }}>{r.device?.map((v) => v.toFixed(1)).join(", ")}</td>
              <td style={{ padding: 2 }}>{(r.text || "").slice(0, 40)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
