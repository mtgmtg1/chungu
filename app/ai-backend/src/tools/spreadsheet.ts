// [Flow: Step 1 (context에서 job_id, authHeaders 추출) -> Step 2 (임시 스프레드시트 상태 관리)
//       -> Step 3 (시트/셀/행/저장 도구 생성) -> Step 4 (도구 객체 반환)]
// 엑셀 조작용 서버 사이드 도구. SheetJS(xlsx)를 사용해 메모리에서 워크북을 수정하고,
// apply_changes에서 FastAPI로 저장한다.
import { tool } from 'ai';
import { z } from 'zod';
import type { AuthHeaders } from '../lib/auth.js';
import * as proofApi from '../lib/proof-api.js';

interface SpreadsheetContext {
  jobId?: string;
  job_id?: string;
  authHeaders?: AuthHeaders;
  [key: string]: unknown;
}

interface CellChange {
  sheet_index: number;
  row: number;
  col: number;
  value: string | number;
}

interface RowChange {
  sheet_index: number;
  row: number;
  action: 'add' | 'delete';
  data?: Array<string | number>;
}

/**
 * [Flow: Step 1 (context 파싱) -> Step 2 (변경 버퍼 초기화) -> Step 3 (도구 반환)]
 *
 * @param context 에이전트 컨텍스트
 * @returns 스프레드시트 조작 도구 맵
 */
export function buildSpreadsheetTools(context: SpreadsheetContext) {
  const jobId = String(context.jobId || context.job_id || '');
  const authHeaders = context.authHeaders || {};

  const cellChanges: CellChange[] = [];
  const rowChanges: RowChange[] = [];

  return {
    get_sheet: tool({
      description: '지정한 시트의 데이터를 반환한다.',
      inputSchema: z.object({
        sheet_index: z.number().describe('0-based 시트 인덱스'),
      }),
      execute: async ({ sheet_index }) => {
        const url = await _getXlsxUrl(jobId, authHeaders);
        const sheet = await _loadSheet(url, sheet_index);
        // [Flow: 출력 크기 제한 — 50→20행으로 축소하여 토큰 소비 절약]
        return { sheet_index, rows: sheet.rows.slice(0, 20) };
      },
    }),

    update_cell: tool({
      description: '지정한 셀의 값을 변경한다.',
      inputSchema: z.object({
        sheet_index: z.number().describe('0-based 시트 인덱스'),
        row: z.number().describe('0-based 행 인덱스'),
        col: z.number().describe('0-based 열 인덱스'),
        value: z.union([z.string(), z.number()]).describe('새 값'),
      }),
      execute: async ({ sheet_index, row, col, value }) => {
        cellChanges.push({ sheet_index, row, col, value });
        return { ok: true, sheet_index, row, col, value };
      },
    }),

    add_row: tool({
      description: '지정한 시트에 행을 추가한다.',
      inputSchema: z.object({
        sheet_index: z.number().describe('0-based 시트 인덱스'),
        row_index: z.number().describe('삽입할 0-based 위치. -1이면 마지막'),
        data: z.array(z.union([z.string(), z.number()])).describe('행 데이터'),
      }),
      execute: async ({ sheet_index, row_index, data }) => {
        rowChanges.push({ sheet_index, row: row_index, action: 'add', data });
        return { ok: true, sheet_index, row_index };
      },
    }),

    delete_row: tool({
      description: '지정한 시트의 행을 삭제한다.',
      inputSchema: z.object({
        sheet_index: z.number().describe('0-based 시트 인덱스'),
        row_index: z.number().describe('삭제할 0-based 행 인덱스'),
      }),
      execute: async ({ sheet_index, row_index }) => {
        rowChanges.push({ sheet_index, row: row_index, action: 'delete' });
        return { ok: true, sheet_index, row_index };
      },
    }),

    apply_changes: tool({
      description: '현재까지의 스프레드시트 변경을 FastAPI에 저장한다.',
      inputSchema: z.object({}),
      execute: async () => {
        if (cellChanges.length === 0 && rowChanges.length === 0) {
          return { saved: false, reason: 'No pending changes' };
        }
        const url = await _getXlsxUrl(jobId, authHeaders);
        const blob = await _applyChanges(url, cellChanges, rowChanges);
        await proofApi.saveXlsx(jobId, blob, 'edited.xlsx', authHeaders);
        return { saved: true, cell_count: cellChanges.length, row_count: rowChanges.length };
      },
    }),
  };
}

/**
 * [Flow: Step 1 (job_id로 FastAPI /download?type=xlsx_basic 조회) -> Step 2 (download_url 추출)
 *       -> Step 3 (반환)]
 *
 * @param jobId Job ID
 * @param authHeaders 인증 헤더
 * @returns XLSX 다운로드 URL
 */
async function _getXlsxUrl(jobId: string, authHeaders: AuthHeaders): Promise<string> {
  const res = await proofApi.request<{ download_url?: string }>(
    `/api/jobs/${jobId}/download?type=xlsx_basic`,
    'GET',
    undefined,
    authHeaders,
  );
  if (typeof res.download_url === 'string') return res.download_url;
  throw new Error('No xlsx download URL found for job');
}

/**
 * [Flow: Step 1 (XLSX URL과 시트 인덱스 수신) -> Step 2 (fetch로 arrayBuffer 로드)
 *       -> Step 3 (SheetJS로 파싱) -> Step 4 (시트 데이터 반환)]
 *
 * @param url XLSX URL
 * @param sheetIndex 0-based 시트 인덱스
 * @returns 시트 데이터
 */
async function _loadSheet(url: string, sheetIndex: number): Promise<{ rows: Array<Array<string | number>> }> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to download xlsx: ${res.status}`);
  const arrayBuffer = await res.arrayBuffer();
  // SheetJS는 동적 import
  const XLSX = await import('xlsx');
  const workbook = XLSX.read(arrayBuffer, { type: 'array' });
  const sheetName = workbook.SheetNames[sheetIndex] || workbook.SheetNames[0];
  const worksheet = workbook.Sheets[sheetName];
  const rows = XLSX.utils.sheet_to_json(worksheet, { header: 1 }) as Array<Array<string | number>>;
  return { rows };
}

/**
 * [Flow: Step 1 (원본 XLSX URL과 변경 내역 수신) -> Step 2 (SheetJS로 워크북 로드)
 *       -> Step 3 (셀/행 변경 적용) -> Step 4 (Blob으로 반환)]
 *
 * @param url 원본 XLSX URL
 * @param cellChanges 셀 변경 목록
 * @param rowChanges 행 변경 목록
 * @returns 수정된 XLSX Blob
 */
async function _applyChanges(
  url: string,
  cellChanges: CellChange[],
  rowChanges: RowChange[],
): Promise<Blob> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to download xlsx: ${res.status}`);
  const arrayBuffer = await res.arrayBuffer();
  const XLSX = await import('xlsx');
  const workbook = XLSX.read(arrayBuffer, { type: 'array' });

  for (const change of cellChanges) {
    const sheetName = workbook.SheetNames[change.sheet_index] || workbook.SheetNames[0];
    const worksheet = workbook.Sheets[sheetName];
    const cellRef = XLSX.utils.encode_cell({ r: change.row, c: change.col });
    worksheet[cellRef] = { t: typeof change.value === 'number' ? 'n' : 's', v: change.value };
  }

  for (const change of rowChanges) {
    const sheetName = workbook.SheetNames[change.sheet_index] || workbook.SheetNames[0];
    const worksheet = workbook.Sheets[sheetName];
    if (change.action === 'add') {
      const newRow = (change.data || []).map((v) => ({ t: typeof v === 'number' ? 'n' : 's', v }));
      XLSX.utils.sheet_add_aoa(worksheet, [newRow], { origin: change.row });
    } else if (change.action === 'delete') {
      // SheetJS는 행 삭제가 복잡하므로, 빈 값으로 마킹 후 처리
      const range = XLSX.utils.decode_range(worksheet['!ref'] || 'A1');
      for (let c = range.s.c; c <= range.e.c; c++) {
        const cellRef = XLSX.utils.encode_cell({ r: change.row, c });
        if (worksheet[cellRef]) delete worksheet[cellRef];
      }
    }
  }

  const output = XLSX.write(workbook, { bookType: 'xlsx', type: 'array' });
  return new Blob([output], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
}
