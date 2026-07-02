// [Flow: Step 1 (downloadUrl로 XLSX fetch) -> Step 2 (LuckyExcel로 Luckysheet 데이터로 변환) -> Step 3 (luckysheet.create로 초기화) -> Step 4 (사용자 편집) -> Step 5 (SheetJS로 XLSX 반출) -> Step 6 (저장 또는 다운로드)]
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2, Download, Save, RotateCcw } from "lucide-react";
import * as XLSX from "xlsx";
import { api } from "../api.js";

export default function SpreadsheetEditor({ downloadUrl, jobId, fileName }) {
  const { t } = useTranslation();
  const containerRef = useRef(null);
  const luckysheetRef = useRef(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState("");
  const [initialOptions, setInitialOptions] = useState(null);
  const [libsLoaded, setLibsLoaded] = useState(false);

  // 스크립트 태그로 외부 JS 로드 (UMD/CJS 모듈용)
  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const existing = document.querySelector(`script[src="${src}"]`);
      if (existing) { resolve(); return; }
      const script = document.createElement("script");
      script.src = src;
      script.onload = resolve;
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }

  // Luckysheet 라이브러리 동적 로드
  useEffect(() => {
    let mounted = true;

    async function init() {
      try {
        // jQuery를 먼저 로드하여 전역에 노출 (Luckysheet는 $에 의존)
        if (!window.jQuery) {
          const jqueryModule = await import("jquery");
          window.jQuery = jqueryModule.default || jqueryModule;
          window.$ = window.jQuery;
        }
        // Vite + ESM 환경에서 CommonJS 기반 luckysheet를 동적으로 import
        await import("luckysheet/dist/plugins/css/pluginsCss.css");
        await import("luckysheet/dist/css/luckysheet.css");
        await import("luckysheet/dist/assets/iconfont/iconfont.css");
        // plugin.js, luckysheet.umd.js, luckyexcel.umd.js 모두 스크립트 태그로 로드
        // 전역 jQuery를 공유하여 plugin.js의 mousewheel 등 확장이 luckysheet에 적용됨
        const pluginUrl = (await import("luckysheet/dist/plugins/js/plugin.js?url")).default;
        await loadScript(pluginUrl);
        const luckysheetUrl = (await import("luckysheet/dist/luckysheet.umd.js?url")).default;
        await loadScript(luckysheetUrl);
        const luckyExcelUrl = (await import("luckyexcel/dist/luckyexcel.umd.js?url")).default;
        await loadScript(luckyExcelUrl);
        if (!mounted) return;
        const luckysheet = window.luckysheet;
        luckysheetRef.current = luckysheet;
        setLibsLoaded(true);
      } catch (e) {
        if (mounted) setError(e.message || t("page:result.spreadsheetInitError"));
      } finally {
        if (mounted) setLoading(false);
      }
    }

    init();
    return () => {
      mounted = false;
      if (luckysheetRef.current && typeof luckysheetRef.current.destroy === "function") {
        luckysheetRef.current.destroy();
      }
    };
  }, []);

  // 라이브러리 로드 완료 후 downloadUrl이 있으면 loadExcel 호출
  // downloadUrl 변경 시 데이터 다시 로드
  useEffect(() => {
    if (!libsLoaded || !downloadUrl) return;
    if (typeof luckysheetRef.current.destroy === "function") {
      luckysheetRef.current.destroy();
    }
    loadExcel(luckysheetRef.current);
  }, [downloadUrl, libsLoaded]);

  // [Flow: Step 1 (편집본 URL 시도) -> Step 2 (있으면 편집본 사용, 없으면 원본 사용) -> Step 3 (LuckyExcel 변환) -> Step 4 (luckysheet.create)]
  async function loadExcel(luckysheet) {
    if (!downloadUrl) return;
    setLoading(true);
    setError("");
    try {
      // window.LuckyExcel (UMD 스크립트로 로드됨)
      const LuckyExcel = window.LuckyExcel;
      if (!LuckyExcel) throw new Error("LuckyExcel not loaded");

      // 저장된 편집본이 있는지 확인
      let effectiveUrl = downloadUrl;
      try {
        const editedRes = await api.editedXlsxUrl(jobId);
        if (editedRes?.download_url) {
          effectiveUrl = editedRes.download_url;
        }
      } catch {
        // 편집본이 없으면 원본 사용 (404 정상)
      }

      const res = await fetch(effectiveUrl);
      if (!res.ok) throw new Error(`다운로드 실패: ${res.status}`);
      const arrayBuffer = await res.arrayBuffer();
      const file = new File([arrayBuffer], fileName || "result.xlsx", {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
      });
      const transform = LuckyExcel.transformExcelToLucky;

      transform(file, (exportJson) => {
        if (!exportJson || !exportJson.sheets) {
          setError(t("page:result.spreadsheetParseError"));
          setLoading(false);
          return;
        }
        const options = {
          container: "luckysheet-container",
          showinfobar: false,
          showtoolbar: true,
          showsheetbar: true,
          showstatisticBar: true,
          allowEdit: true,
          enableAddRow: true,
          enableAddBackTop: true,
          data: exportJson.sheets
        };
        setInitialOptions(options);
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            luckysheet.create(options);
            setLoading(false);
          });
        });
      });
    } catch (e) {
      setError(e.message || t("page:result.spreadsheetLoadError"));
      setLoading(false);
    }
  }

  function getLuckysheetData() {
    const luckysheet = luckysheetRef.current;
    if (!luckysheet || !containerRef.current) return null;
    return luckysheet.getAllSheets();
  }

  function exportToBlob() {
    const data = getLuckysheetData();
    if (!data) return null;
    const wb = luckysheetDataToWorkbook(data);
    const arrayBuffer = XLSX.write(wb, { bookType: "xlsx", type: "array" });
    return new Blob([arrayBuffer], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
  }

  function handleDownload() {
    const blob = exportToBlob();
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = fileName || "edited.xlsx";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  async function handleSave() {
    const blob = exportToBlob();
    if (!blob) return;
    setSaving(true);
    setSaveMessage("");
    setError("");
    try {
      await api.saveEditedXlsx(jobId, blob, fileName || "edited.xlsx");
      setSaveMessage(t("page:result.saved"));
      setTimeout(() => setSaveMessage(""), 2000);
    } catch (e) {
      setError(e.message || t("page:result.spreadsheetSaveError"));
    } finally {
      setSaving(false);
    }
  }

  function handleReset() {
    if (!luckysheetRef.current || !initialOptions) return;
    luckysheetRef.current.create(initialOptions);
  }

  function luckysheetDataToWorkbook(sheets) {
    const wb = XLSX.utils.book_new();
    for (const sheet of sheets) {
      const ws = luckysheetToWorksheet(sheet);
      XLSX.utils.book_append_sheet(wb, ws, sheet.name || "Sheet");
    }
    return wb;
  }

  function luckysheetToWorksheet(sheet) {
    // [Flow: Step 1 (data 2차원 배열에서 최대 행/열 추출) -> Step 2 (셀 값을 SheetJS 형식으로 변환) -> Step 3 (병합/열너비/행높이 적용) -> Step 4 (worksheet 반환)]
    const sheetData = sheet.data || [];
    let maxRow = sheetData.length - 1;
    let maxCol = 0;
    for (let r = 0; r < sheetData.length; r++) {
      if (sheetData[r]) maxCol = Math.max(maxCol, sheetData[r].length - 1);
    }
    if (maxRow < 0) maxRow = 0;
    if (maxCol < 0) maxCol = 0;

    const data = Array.from({ length: maxRow + 1 }, () => Array(maxCol + 1).fill(""));
    for (let r = 0; r < sheetData.length; r++) {
      const row = sheetData[r];
      if (!row) continue;
      for (let c = 0; c < row.length; c++) {
        data[r][c] = extractCellValue(row[c]);
      }
    }

    const ws = XLSX.utils.aoa_to_sheet(data);

    const merges = [];
    const mergeConfig = sheet.config?.merge || {};
    for (const key of Object.keys(mergeConfig)) {
      const m = mergeConfig[key];
      merges.push({ s: { r: m.r, c: m.c }, e: { r: m.r + m.rs - 1, c: m.c + m.cs - 1 } });
    }
    if (merges.length) ws['!merges'] = merges;

    const colWidths = [];
    const columnlen = sheet.config?.columnlen || {};
    for (let c = 0; c <= maxCol; c++) {
      colWidths.push({ wpx: columnlen[c] || 80 });
    }
    ws['!cols'] = colWidths;

    const rowHeights = [];
    const rowlen = sheet.config?.rowlen || {};
    for (let r = 0; r <= maxRow; r++) {
      rowHeights.push({ hpx: rowlen[r] || 20 });
    }
    ws['!rows'] = rowHeights;

    return ws;
  }

  function extractCellValue(v) {
    if (v === null || v === undefined) return "";
    if (typeof v === "object") {
      if (v.f) return { f: v.f };
      return v.m ?? v.v ?? "";
    }
    return v;
  }

  return (
    <div className="h-full flex flex-col overflow-hidden bg-white">
      <div className="flex items-center justify-between px-4 py-2 border-b border-outline-variant flex-shrink-0" data-oid="spreadsheet-toolbar">
        <div className="flex items-center gap-2">
          <button
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-primary text-white rounded-lg text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-colors"
          data-oid="spreadsheet-save-btn">
            {saving ? <Loader2 className="animate-spin" size={16} /> : <Save size={16} />}
            {t("page:result.save")}
          </button>

          <button
          onClick={handleDownload}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-surface-container-high text-on-surface rounded-lg text-sm font-medium hover:bg-surface-container-high/80 transition-colors border border-outline-variant"
          data-oid="spreadsheet-download-btn">
            <Download size={16} />
            {t("page:result.download")}
          </button>

          <button
          onClick={handleReset}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-surface-container-high text-on-surface rounded-lg text-sm font-medium hover:bg-surface-container-high/80 transition-colors border border-outline-variant"
          data-oid="spreadsheet-reset-btn">
            <RotateCcw size={16} />
            {t("page:result.reset")}
          </button>
        </div>

        {saveMessage &&
        <span className="text-sm text-green-600 font-medium" data-oid="spreadsheet-save-msg">
          {saveMessage}
        </span>
        }
      </div>

      {error &&
      <div className="px-4 py-2 text-sm text-red-600 bg-red-50 flex-shrink-0" data-oid="spreadsheet-error">
        {error}
      </div>
      }

      <div className="relative flex-1 overflow-hidden">
        {loading &&
        <div className="absolute inset-0 flex items-center justify-center bg-white z-10" data-oid="spreadsheet-loading">
          <Loader2 className="animate-spin mr-2" size={20} />
          {t("page:result.excelLoading")}
        </div>
        }
        <div ref={containerRef} id="luckysheet-container" className="w-full h-full" style={{ margin: 0, padding: 0, position: "absolute", width: "100%", height: "100%", left: 0, top: 0 }} data-oid="luckysheet-container" />
      </div>
    </div>
  );
}
