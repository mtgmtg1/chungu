// [Flow: Step 1 (Nodiom, remark, diff-match-patch, Fuse.js 임포트)
//       -> Step 2 (마크다운 분할/파일 선택/헬딩 검색/섹션 추출/퍼지 교체/chunk 함수 정의)
//       -> Step 3 (buildMarkdownTools 에서 사용할 순수 헬퍼 함수 집합 노출)]
// 마크다운 에디터용 AI 도구에서 공통으로 사용하는 순수 함수 모듈.
// FastAPI 연동은 proof-api.ts 에 위임하고, 이 파일은 문자열/AST/퍼지 매칭만 담당한다.

import { makePatches, applyPatches, match, makeDiff } from '@sanity/diff-match-patch';
import { Nodiom, type OutlineNode } from '@synexiom-labs/nodiom';
import Fuse from 'fuse.js';
import { remark } from 'remark';
import remarkGfm from 'remark-gfm';
import { selectAll } from 'unist-util-select';
import type { AuthHeaders } from './auth.js';
import * as proofApi from './proof-api.js';

// [Flow: 한 파일 chunk 기본 크기 정의]
export const DEFAULT_CHUNK_LIMIT = 4000;

// [Flow: <!-- Page N --> 또는 <!-- 파일 N --> 형식 마커를 분할에 사용]
const FILE_MARKER_RE = /<!--\s*(?:Page|파일)\s+\d+\s*-->/gi;

// [Flow: heading query 에서 leading # 과 공백을 제거]
const HEADING_PREFIX_RE = /^#+\s*/;

// [Flow: 퍼지 교체 시 앞뒤 컨텍스트 길이]
const REPLACE_CONTEXT_MARGIN = 32;

// [Flow: 선택 파일을 식별할 때 사용하는 컨텍스트]
export interface MarkdownFileContext {
  jobId: string;
  authHeaders?: AuthHeaders;
  selectedFileIndex?: number;
  currentPage?: number;
}

// [Flow: chunk 읽기 결과]
export interface MarkdownChunk {
  chunk: string;
  start: number;
  end: number;
  nextCursor?: number;
  previousCursor?: number;
  hasMore: boolean;
}

// [Flow: 헬딩 outline 항목]
export interface HeadingInfo {
  depth: number;
  heading: string;
  fullPath: string;
  selector: string;
  fullSelector: string;
}

// [Flow: 퍼지 교체 결과]
export interface ReplaceResult {
  markdown: string;
  success: boolean;
  applied: boolean[];
}

// [Flow: getSectionMarkdown 의 반환 타입]
export type SectionResult =
  | { content: string; headingInfo: HeadingInfo }
  | { error: string; suggestions: string[] };

// [Flow: jobId/authHeaders 로 /preview 조회 -> 전체 결합 markdown 반환]
export async function fetchMarkdown(
  jobId: string,
  authHeaders?: AuthHeaders,
): Promise<string> {
  return proofApi.getMarkdown(jobId, authHeaders);
}

// [Flow: 결합 markdown 을 파일 마커 기준으로 분할 -> 파일별 markdown 배열 반환]
export function splitMarkdownByFileMarkers(markdown: string): string[] {
  return markdown
    .split(FILE_MARKER_RE)
    .map(part => part.trimStart())
    .filter(part => part.length > 0);
}

// [Flow: explicit page_no, selectedFileIndex, currentPage 우선순위로 0-based 파일 인덱스 반환]
export function resolveFileIndex(
  totalFiles: number,
  requestedPageNo?: number,
  selectedFileIndex?: number,
  currentPage?: number,
): number {
  if (totalFiles <= 1) {
    return 0;
  }

  const clampIndex = (value: number) => Math.max(0, Math.min(value, totalFiles - 1));

  if (typeof requestedPageNo === 'number' && requestedPageNo >= 1) {
    return clampIndex(requestedPageNo - 1);
  }

  if (typeof selectedFileIndex === 'number' && selectedFileIndex >= 0) {
    return clampIndex(selectedFileIndex);
  }

  if (typeof currentPage === 'number' && currentPage >= 1) {
    return clampIndex(currentPage - 1);
  }

  return 0;
}

// [Flow: 결합 markdown + 파일 인덱스 -> 해당 파일 markdown 추출]
export function extractFileMarkdown(markdown: string, fileIndex: number): string {
  const parts = splitMarkdownByFileMarkers(markdown);
  if (parts.length === 0) {
    return markdown;
  }
  if (parts.length === 1) {
    return parts[0];
  }

  const safeIndex = Math.max(0, Math.min(fileIndex, parts.length - 1));
  return parts[safeIndex];
}

// [Flow: markdown string -> Nodiom 문서 객체 생성]
export function createNodiomDoc(markdown: string): Nodiom {
  return Nodiom.fromString(markdown);
}

// [Flow: Nodiom tree() -> 평탄화된 heading 목록 반환]
export function getHeadingsFromDoc(doc: Nodiom): HeadingInfo[] {
  const outline = doc.tree();
  const headings: HeadingInfo[] = [];

  function walk(nodes: OutlineNode[], ancestors: OutlineNode[]) {
    for (const node of nodes) {
      const path = [...ancestors, node];
      const localSelector = `${'#'.repeat(node.depth)} ${node.heading}`;
      const fullSelector = path.map(n => `${'#'.repeat(n.depth)} ${n.heading}`).join(' > ');

      headings.push({
        depth: node.depth,
        heading: node.heading,
        fullPath: path.map(n => n.heading).join(' > '),
        selector: localSelector,
        fullSelector,
      });

      walk(node.children, path);
    }
  }

  walk(outline, []);
  return headings;
}

// [Flow: Fuse.js 로 heading 목록에서 가장 유사한 heading 검색]
export function findBestHeadingMatch(
  query: string,
  headings: HeadingInfo[],
  threshold = 0.4,
): HeadingInfo | undefined {
  if (!headings.length || !query.trim()) {
    return undefined;
  }

  const fuse = new Fuse(headings, {
    keys: ['heading'],
    threshold,
    includeScore: true,
    isCaseSensitive: false,
  });

  const results = fuse.search(query.trim());
  return results.length > 0 ? results[0].item : undefined;
}

// [Flow: outline tree 에서 target heading 의 조상 경로를 복원]
export function findHeadingPath(
  outline: OutlineNode[],
  targetHeading: string,
  parentHeading?: string,
): HeadingInfo[][] {
  const normalizedTarget = normalizeHeadingText(targetHeading);
  const normalizedParent = parentHeading ? normalizeHeadingText(parentHeading) : undefined;
  const foundPaths: HeadingInfo[][] = [];

  function toHeadingInfo(path: OutlineNode[]): HeadingInfo[] {
    return path.map((node, index) => {
      const localSelector = `${'#'.repeat(node.depth)} ${node.heading}`;
      const fullSelector = path
        .slice(0, index + 1)
        .map(n => `${'#'.repeat(n.depth)} ${n.heading}`)
        .join(' > ');

      return {
        depth: node.depth,
        heading: node.heading,
        fullPath: path.slice(0, index + 1).map(n => n.heading).join(' > '),
        selector: localSelector,
        fullSelector,
      };
    });
  }

  function dfs(nodes: OutlineNode[], ancestors: OutlineNode[]) {
    for (const node of nodes) {
      const path = [...ancestors, node];
      const isTarget = normalizeHeadingText(node.heading) === normalizedTarget;

      if (isTarget) {
        const matchesParent = normalizedParent
          ? ancestors.some(a => normalizeHeadingText(a.heading) === normalizedParent)
          : true;

        if (matchesParent) {
          foundPaths.push(toHeadingInfo(path));
        }
      }

      dfs(node.children, path);
    }
  }

  dfs(outline, []);
  return foundPaths;
}

// [Flow: heading text(+parent_heading) -> Nodiom selector -> 섹션 markdown 반환]
export function getSectionMarkdown(
  doc: Nodiom,
  headingQuery: string,
  parentHeading?: string,
): SectionResult {
  const outline = doc.tree();
  const normalizedQuery = normalizeHeadingText(headingQuery);

  const exactPaths = findHeadingPath(outline, headingQuery, parentHeading);
  if (exactPaths.length === 1) {
    const path = exactPaths[0];
    return readSectionAtPath(doc, path);
  }

  if (exactPaths.length > 1) {
    return {
      error: `Heading "${headingQuery}" is ambiguous. Please provide parent_heading to disambiguate.`,
      suggestions: exactPaths.map(path => path.map(h => h.heading).join(' > ')),
    };
  }

  const headings = getHeadingsFromDoc(doc);
  const fuzzyMatch = findBestHeadingMatch(headingQuery, headings, 0.4);

  if (fuzzyMatch) {
    const fuzzyPaths = findHeadingPath(outline, fuzzyMatch.heading, parentHeading);
    if (fuzzyPaths.length === 1) {
      return readSectionAtPath(doc, fuzzyPaths[0]);
    }

    if (fuzzyPaths.length > 1) {
      return {
        error: `Fuzzy-matched heading "${fuzzyMatch.heading}" is ambiguous. Please provide parent_heading.`,
        suggestions: fuzzyPaths.map(path => path.map(h => h.heading).join(' > ')),
      };
    }
  }

  const suggestions = headings.slice(0, 5).map(h => h.fullPath);
  return {
    error: `No heading found for "${headingQuery}".`,
    suggestions,
  };
}

// [Flow: remark AST -> GFM table 노드 추출 -> markdown 직렬화]
export function findTablesInMarkdown(
  markdown: string,
  tableIndex?: number,
  headingQuery?: string,
  parentHeading?: string,
): { table?: string; tables: string[]; error?: string } {
  let sourceMarkdown = markdown;

  if (headingQuery) {
    const doc = createNodiomDoc(markdown);
    const sectionResult = getSectionMarkdown(doc, headingQuery, parentHeading);
    if ('error' in sectionResult) {
      return { tables: [], error: sectionResult.error };
    }
    sourceMarkdown = sectionResult.content;
  }

  const processor = remark().use(remarkGfm);
  const tree = processor.parse(sourceMarkdown) as any;
  const tableNodes = selectAll('table', tree) as any[];

  const tables = tableNodes.map(node =>
    processor.stringify({ type: 'root', children: [node] } as any).trim(),
  );

  const table = typeof tableIndex === 'number' ? tables[tableIndex] : undefined;
  return { table, tables };
}

// [Flow: diff-match-patch match() 로 old_text 위치 확인
//       -> makeDiff() 로 실제 문서 내 매칭 길이 산정
//       -> 앞뒤 컨텍스트를 포함한 patch 생성 -> applyPatches() 로 안전 교체]
export function replaceTextFuzzy(
  markdown: string,
  oldText: string,
  newText: string,
): ReplaceResult {
  if (!oldText.trim()) {
    return { markdown, success: false, applied: [] };
  }

  const start = match(markdown, oldText, 0);
  if (start === -1) {
    return { markdown, success: false, applied: [] };
  }

  const windowSize = oldText.length * 3 + 64;
  const docWindow = markdown.slice(start, start + windowSize);
  const matchedLength = computeMatchedLength(oldText, docWindow);

  const prefix = markdown.slice(Math.max(0, start - REPLACE_CONTEXT_MARGIN), start);
  const oldSpan = markdown.slice(start, start + matchedLength);
  const suffix = markdown.slice(start + matchedLength, start + matchedLength + REPLACE_CONTEXT_MARGIN);

  const patches = makePatches(prefix + oldSpan + suffix, prefix + newText + suffix);
  const [result, applied] = applyPatches(patches, markdown);
  const success = applied.length > 0 && applied.every(Boolean) && result !== markdown;

  return { markdown: result, success, applied };
}

// [Flow: position(beginning/end/heading) 에 new_text 삽입]
export function insertTextAt(
  markdown: string,
  position: string,
  newText: string,
  doc?: Nodiom,
): { markdown: string; success: boolean; error?: string } {
  if (!position || newText === undefined) {
    return { markdown, success: false, error: 'position and new_text are required' };
  }

  const trimmedPosition = position.trim().toLowerCase();

  if (trimmedPosition === 'beginning') {
    return { markdown: `${newText}\n\n${markdown}`, success: true };
  }

  if (trimmedPosition === 'end' || trimmedPosition === 'cursor') {
    return { markdown: `${markdown}\n\n${newText}`, success: true };
  }

  const workingDoc = doc || createNodiomDoc(markdown);
  const sectionResult = getSectionMarkdown(workingDoc, position);

  if ('error' in sectionResult) {
    return { markdown, success: false, error: sectionResult.error };
  }

  try {
    workingDoc.append(sectionResult.headingInfo.fullSelector, newText);
    return { markdown: workingDoc.toString(), success: true };
  } catch (e) {
    return {
      markdown,
      success: false,
      error: e instanceof Error ? e.message : 'Failed to insert at heading',
    };
  }
}

// [Flow: cursor 기준 next/previous/first chunk 반환]
export function readChunk(
  markdown: string,
  cursor: number | 'first',
  limit: number,
  direction: 'next' | 'previous',
): MarkdownChunk {
  const safeLimit = Math.max(1, limit || DEFAULT_CHUNK_LIMIT);
  const total = markdown.length;

  if (direction === 'next') {
    const start = cursor === 'first' ? 0 : Math.max(0, Number(cursor) || 0);
    const end = Math.min(total, start + safeLimit);
    return {
      chunk: markdown.slice(start, end),
      start,
      end,
      nextCursor: end,
      hasMore: end < total,
    };
  }

  const end = cursor === 'first' ? Math.min(total, safeLimit) : Math.min(total, Number(cursor) || total);
  const start = Math.max(0, end - safeLimit);
  return {
    chunk: markdown.slice(start, end),
    start,
    end,
    previousCursor: start,
    hasMore: start > 0,
  };
}

// [Flow: Nodiom selector path -> doc.read() 실행 및 HeadingInfo 반환]
function readSectionAtPath(doc: Nodiom, path: HeadingInfo[]): { content: string; headingInfo: HeadingInfo } {
  const selector = path.map(h => h.selector).join(' > ');
  const content = doc.read(selector);
  const headingInfo = path[path.length - 1];
  if (!headingInfo) {
    throw new Error('Empty heading path');
  }
  return { content, headingInfo };
}

// [Flow: heading 텍스트 정규화 -> leading # 제거 및 소문자/공백 정리]
function normalizeHeadingText(text: string): string {
  return text.replace(HEADING_PREFIX_RE, '').trim().toLowerCase();
}

// [Flow: makeDiff 결과를 탐색 -> oldText 가 모두 소진될 때 문서에서 매칭된 문자 길이 반환]
function computeMatchedLength(oldText: string, documentFromStart: string): number {
  const diffs = makeDiff(oldText, documentFromStart);
  let oldConsumed = 0;
  let docConsumed = 0;
  const target = oldText.length;

  for (const [op, text] of diffs) {
    const len = text.length;

    if (op === 1) {
      // insert: document 에만 존재
      docConsumed += len;
      continue;
    }

    if (op === -1) {
      // delete: oldText 에만 존재
      if (oldConsumed + len >= target) {
        return docConsumed;
      }
      oldConsumed += len;
      continue;
    }

    // equal: 양쪽 모두 소진
    if (oldConsumed + len >= target) {
      docConsumed += target - oldConsumed;
      return docConsumed;
    }

    oldConsumed += len;
    docConsumed += len;
  }

  return docConsumed;
}
