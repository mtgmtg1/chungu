# 마크다운 읽기/편집 AI 도구 구현 플랜

## 배경

`app/ai-backend/src/tools/markdown.ts`는 현재 `get_section`, `get_table`만 존재하며, raw string split/regex 기반으로 동작합니다. `get_markdown`과 같은 범용 읽기 도구가 없고, `replace_selection`은 exact match라 formatter re-flow 등에 취약합니다.

이 플랜은 `Nodiom` + `Fuse.js` + `@sanity/diff-match-patch` + `remark`를 조합하여 `currentPage`/`selectedFileIndex`를 반영한 파일 기반 읽기/편집 도구를 추가하는 것을 목표로 합니다.

---

## 체크리스트

- [x] 1. 의존성 추가 및 `package.json` test 스크립트 설정
- [x] 2. `markdown-utils.ts` 헬퍼 함수 설계
- [x] 3. `markdown.test.ts` 작성 → Red 상태 확인
- [x] 4. `buildMarkdownTools` 리팩토링 (새 tool 정의)
- [x] 5. `chat/route.ts` system prompt tool 목록 갱신
- [x] 6. `npm run test` / `npm run build` 통과 검증
- [x] 7. AI 백엔드 빌드 및 a1 배포

---

## 1. 의존성 및 스크립트

`app/ai-backend/package.json` 수정:

```json
{
  "scripts": {
    "test": "node --import tsx --test src/**/*.test.ts"
  },
  "dependencies": {
    "@sanity/diff-match-patch": "^3.2.0",
    "@synexiom-labs/nodiom": "^0.x",
    "fuse.js": "^7.0.0",
    "remark": "^15.0.0",
    "remark-gfm": "^4.0.0",
    "unist-util-visit": "^5.0.0",
    "unist-util-select": "^5.1.0",
    "mdast-util-to-markdown": "^2.1.0",
    "@types/mdast": "^5.0.0"
  }
}
```

---

## 2. 파일 변경 예상

### 신규

- `app/ai-backend/src/lib/markdown-utils.ts`
- `app/ai-backend/src/tools/markdown.test.ts`

### 수정

- `app/ai-backend/src/tools/markdown.ts`
- `app/ai-backend/src/chat/route.ts`
- `app/ai-backend/package.json`

---

## 3. `markdown-utils.ts` 핵심 함수

| 함수 | 역할 |
|---|---|
| `fetchMarkdown(jobId, authHeaders)` | `/preview`에서 전체 markdown 가져오기 |
| `splitMarkdownByFileMarkers(markdown)` | `<!-- Page N -->` / `<!-- 파일 N -->` 분할 |
| `resolveFileIndex(context, requestedPageNo, totalFiles)` | `selectedFileIndex` → 1-based `pageNum` |
| `extractFileMarkdown(combinedMarkdown, fileIndex)` | 선택 파일 본문만 추출 |
| `createNodiomDoc(fileMarkdown)` | `Nodiom.fromString()` 래퍼 |
| `getHeadingsFromDoc(doc)` | `doc.tree()`를 평탄화하여 outline 반환 |
| `findBestHeadingMatch(query, headings, threshold)` | `Fuse.js` fuzzy heading 검색 |
| `buildNodiomSelector(headingMatch, parentHeading?)` | `# H1 > ## H2` selector 생성 |
| `getSectionMarkdown(doc, selector)` | `doc.read(selector)` 래퍼 |
| `findTablesInMarkdown(fileMarkdown, tableIndex?, heading?)` | `remark` AST로 table 추출 |
| `replaceTextFuzzy(markdown, oldText, newText)` | `@sanity/diff-match-patch` fuzzy 교체 |
| `insertTextAt(fileMarkdown, position, newText, doc)` | `beginning`/`end`/heading |
| `readChunk(fileMarkdown, cursor, limit, direction)` | `first`/`next`/`previous` chunk |
| `saveFileMarkdown(jobId, fileIndex, markdown, authHeaders)` | `pageNum = fileIndex + 1`로 저장 |

---

## 4. `buildMarkdownTools` 도구 명세

| 도구 | 입력 | 출력 |
|---|---|---|
| `get_markdown` | `page_no?: number` | 선택된 파일의 전체 markdown |
| `get_page` | `page_no?: number` | 특정 페이지/파일 markdown |
| `get_headings` | `page_no?: number` | `{depth, heading}[]` outline |
| `get_section` | `heading`, `parent_heading?`, `page_no?` | 섹션 markdown + `resolved_heading` |
| `get_table` | `table_index`, `heading?`, `page_no?` | N번째 표 markdown |
| `read_first_chunk` | `limit?: number` (기본 4000) | `chunk`, `next_cursor`, `has_more` |
| `read_next_chunk` | `cursor`, `limit?` | `chunk`, `next_cursor`, `has_more` |
| `read_previous_chunk` | `cursor`, `limit?` | `chunk`, `previous_cursor`, `has_more` |
| `replace_text` | `old_text`, `new_text`, `page_no?` | `success`, `new_preview?` |
| `insert_text` | `position`, `new_text`, `page_no?` | `success` |
| `apply_edits` | — | `saved`, `file_index` |

---

## 5. `chat/route.ts` system prompt 수정

markdown editor 카테고리 설명을 다음으로 교체:

```text
2. Markdown editor / report & document editor (when active_editor is markdown):
   - Users may describe this as: 보고서, 문서, 글쓰기, 메모, 메모장, 보고서 작성, 문서 정리, 요약, 마크다운, 에디터.
   - Tools: get_markdown, get_page, get_headings, get_section, get_table, read_first_chunk, read_next_chunk, read_previous_chunk, replace_text, insert_text, apply_edits
   - Guidelines:
     - Always use get_headings first to see the document outline.
     - For reading, prefer get_page or get_markdown (selected_file_index is used by default).
     - For large files, use read_first_chunk / read_next_chunk instead of get_markdown.
     - For editing, use replace_text with old_text/new_text (fuzzy matching).
     - For insertion, use insert_text with position='beginning' | 'end' | heading text.
     - Call apply_edits only when you are ready to save changes.
```

---

## 6. 테스트 케이스

`app/ai-backend/src/tools/markdown.test.ts`:

- `splitMarkdownByFileMarkers` with `<!-- Page N -->` / `<!-- 파일 N -->`
- `resolveFileIndex` with `selectedFileIndex` / `currentPage` / explicit `page_no`
- `extractFileMarkdown` boundary and single-file fallback
- `getHeadingsFromDoc` nested depth flattening
- `findBestHeadingMatch` exact, typo-tolerant, below-threshold fail
- `getSectionMarkdown` exact selector + fuzzy fallback + `parent_heading` disambiguation
- `findTablesInMarkdown` two GFM tables with `table_index=1`
- `replaceTextFuzzy` exact, whitespace drift, partial typo, no-match fail
- `readChunk` first/next/previous/boundary/empty
- `applyEdits` calls `proofApi.saveMarkdown` with `pageNum = fileIndex + 1`

---

## 7. 검증

```bash
cd app/ai-backend
npm install
npm run test
npm run lint
npm run build
```

---

## 8. 리스크 및 주의사항

- `Nodiom` v0.x이므로 root-level `table[0]` 같은 미지원 경우 `remark` AST로 보완.
- `remark`/`Nodiom`은 markdown formatting을 약간 정규화할 수 있음.
- `saveMarkdown`의 `pageNum`은 1-based 파일 번호 (`selectedFileIndex + 1`).

---

**이 플랜 파일을 따라 구현을 진행합니다.**
