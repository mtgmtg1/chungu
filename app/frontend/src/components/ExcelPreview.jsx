// [Flow: Step 1 (signed URL로 xlsx 다운로드) -> Step 2 (SheetJS로 모든 시트 파싱) -> Step 3 (상단 시트 탭 렌더링) -> Step 4 (선택된 시트를 2D 배열로 변환) -> Step 5 (헤더/행 테이블 렌더링)]
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import * as XLSX from "xlsx";

export default function ExcelPreview({ downloadUrl }) {
  const { t } = useTranslation();
  const [sheets, setSheets] = useState([]);
  const [activeIndex, setActiveIndex] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!downloadUrl) return;
    let cancelled = false;

    async function load() {
      try {
        const res = await fetch(downloadUrl);
        if (!res.ok) throw new Error(`다운로드 실패: ${res.status}`);
        const ab = await res.arrayBuffer();
        const workbook = XLSX.read(ab, { type: "array" });
        const parsedSheets = workbook.SheetNames.map((name) => {
          const sheet = workbook.Sheets[name];
          const data = XLSX.utils.sheet_to_json(sheet, { header: 1, defval: "" });
          return { name, rows: data };
        });
        if (!cancelled) {
          setSheets(parsedSheets);
          setActiveIndex(0);
        }
      } catch (e) {
        if (!cancelled) setError(e.message || "엑셀 미리보기 로드 실패");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    return () => { cancelled = true; };
  }, [downloadUrl]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-on-surface-variant">
        <Loader2 className="animate-spin mr-2" size={20} />
        {t("page:result.excelLoading")}
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full text-red-600 px-4 text-center">
        {error || t("page:result.excelLoadError")}
      </div>
    );
  }

  if (sheets.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-on-surface-variant">
        {t("page:result.excelEmpty")}
      </div>
    );
  }

  const activeSheet = sheets[activeIndex] || sheets[0];
  const rows = activeSheet.rows;
  const headers = rows[0] || [];
  const bodyRows = rows.slice(1);
  const showTabs = sheets.length > 1;

  return (
    <div className="h-full flex flex-col overflow-hidden bg-white">
      {showTabs &&
      <div className="flex items-center gap-1 px-4 pt-3 pb-1 border-b border-outline-variant flex-shrink-0 overflow-x-auto" data-oid="sheet-tabs">
        {sheets.map((sheet, idx) => (
          <button
          key={sheet.name}
          onClick={() => setActiveIndex(idx)}
          className={`px-3 py-1.5 rounded-t-lg text-sm font-medium whitespace-nowrap transition-colors ${
          idx === activeIndex ?
          "bg-primary text-white" :
          "text-on-surface hover:bg-surface-container-high"}`
          }
          data-oid={`sheet-tab-${sheet.name}`}>
            {sheet.name}
          </button>
        ))}
      </div>
      }

      <div className="flex-1 overflow-auto p-4">
        <div className="inline-block min-w-full border border-outline-variant rounded-lg overflow-hidden">
          <table className="min-w-full text-sm text-left">
            <thead className="bg-surface-container-high text-on-surface font-bold sticky top-0 z-10">
              <tr>
                {headers.map((h, idx) => (
                  <th key={idx} className="px-3 py-2 border-b border-outline-variant whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {bodyRows.map((row, ridx) => (
                <tr key={ridx} className="hover:bg-surface-container-low/50">
                  {row.map((cell, cidx) => (
                    <td key={cidx} className="px-3 py-2 border-b border-outline-variant/50 text-on-surface">
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
