# Flow Panel 구현 계획 — 마크다운 → React Flow 논리 흐름 시각화

> 결과페이지(JobResultPage)에 마크다운 문서의 헤딩 구조를 React Flow로 시각화하는 **플로우 패널**을 추가하고, 기존 탭 버튼을 **드롭다운 메뉴**로 교체하여 Markdown / Excel / Flow 뷰를 전환할 수 있도록 함.

## MCP 조사 결과 (context7 + deepwiki)

### React Flow v12 (`@xyflow/react`)

| 항목 | 확보한 정보 |
|------|------------|
| 패키지명 | `@xyflow/react` (구 `reactflow` → v12부터 변경) |
| CSS import | `import '@xyflow/react/dist/style.css'` |
| Provider | `<ReactFlowProvider>`로 감싸야 hooks 사용 가능 |
| 상태 관리 | `useNodesState(initialNodes)` → `[nodes, setNodes, onNodesChange]` |
| 커스텀 노드 | `nodeTypes = { custom: MyNode }`, 노드 컴포넌트는 `NodeProps<T>` 수신, `<Handle>` 컴포넌트 |
| 커스텀 엣지 | `edgeTypes` 매핑, `BaseEdge` + `getBezierPath` / `getSmoothStepPath` |
| 엣지 스타일링 | `style: { stroke, strokeDasharray }`, `className`, `animated: true` |
| 엣지 툴팁 | `<EdgeLabelRenderer>` 포털로 HTML 툴팁 렌더링 |
| 노드 클릭 | `onNodeClick: (event, node) => void` |
| fitView | `fitView` prop 또는 `useReactFlow().fitView({ padding, duration, nodes })` |
| proOptions | `proOptions={{ hideAttribution: true }}` |
| 내장 컴포넌트 | `<Background>`, `<Controls>`, `<MiniMap>` |

### elkjs

| 항목 | 확보한 정보 |
|------|------------|
| import 경로 | `import ELK from 'elkjs/lib/elk.bundled.js'` (브라우저 번들) |
| 생성자 | `const elk = new ELK()` 또는 `new ELK({ defaultLayoutOptions })` |
| JSON 그래프 형식 | `{ id, layoutOptions, children: [{ id, width, height }], edges: [{ id, sources: [], targets: [] }] }` |
| layout() | `elk.layout(graph)` → `Promise<ElkNode>`, 결과 `children`에 `x`, `y` 포함 |
| 레이아웃 옵션 | `elk.algorithm: 'layered'`, `elk.direction: 'DOWN'`, `elk.spacing.nodeNode`, `elk.layered.spacing.nodeNodeBetweenLayers` |
| 리소스 정리 | `elk.terminateWorker()` (Web Worker 사용 시) |

### marked

| 항목 | 확보한 정보 |
|------|------------|
| lexer API | `marked.lexer(markdownString)` → `TokensList` (배열) |
| heading 토큰 | `{ type: 'heading', raw, depth: 1-6, text, tokens: [] }` |
| paragraph 토큰 | `{ type: 'paragraph', raw, text, tokens: [] }` |
| code 토큰 | `{ type: 'code', raw, text, lang, codeBlockStyle }` |
| 기타 토큰 | `space`, `blockquote`, `list`, `listitem`, `hr`, `html`, `table`, `text` |

---

## Phase 1: 의존성 설치 + 인프라

- [x] 1.1 npm 패키지 설치 (`@xyflow/react`, `elkjs`, `uuid`)
- [x] 1.2 CSS import (`app/frontend/src/index.css`)
- [x] 1.3 i18n 키 추가 (`app/frontend/src/locales/{ko,en,ja}/page.json`)

## Phase 2: 마크다운 → Flow 파서 (순방향 파이프라인)

- [x] 2.1 `app/frontend/src/utils/markdownToFlow.js` — `marked.lexer()` 기반 헤딩 → 노드/에지 변환
- [x] 2.2 `app/frontend/src/utils/elkLayout.js` — `elkjs/lib/elk.bundled.js` layered 레이아웃 계산

## Phase 3: FlowViewer 컴포넌트

- [x] 3.1 `app/frontend/src/components/FlowViewer.jsx` — 메인 컴포넌트
  - `HeadingNode` 커스텀 노드 (제목 + H레벨 배지 + 내용 미리보기)
  - `HierarchyEdge` 커스텀 엣지 (실선, 부모-자식)
  - `DependencyEdge` 커스텀 엣지 (점선 + `EdgeLabelRenderer` 툴팁)
  - `ReactFlowProvider` + `useNodesState` / `useEdgesState`
  - `<Background>`, `<Controls>`, `<MiniMap>`, `proOptions={{ hideAttribution: true }}`

## Phase 4: 드롭다운 뷰 전환기

- [x] 4.1 `JobResultPage.jsx` — 탭 버튼 → 드롭다운 교체 (기존 `openDropdown`/`closeDropdown` 재사용)
- [x] 4.2 `previewMode` state에 `"flow"` 추가
- [x] 4.3 `renderRightContent()`에 flow 분기 추가
- [x] 4.4 `FlowViewer` import + `Workflow` / `ChevronDown` 아이콘 import

## Phase 5: AI 의존성 추론 파이프라인 (백엔드)

- [x] 5.1 `app/ai-backend/src/tools/flow.ts` — `extract_flow_structure` + `infer_flow_dependencies` 도구 2개
- [x] 5.2 `app/ai-backend/src/chat/route.ts` — `buildFlowTools` 등록 + 시스템 프롬프트 업데이트
- [ ] 5.3 `FlowViewer.jsx`에 "AI 의존성 분석" 버튼 추가 (점선 에지 + reason 툴팁) — 향후 확장

## Phase 6: 양방향 동기화 (향후 확장)

- [ ] 6.1 가드레일: 순환 참조 탐지 (DFS), 다중 부모 검증
- [ ] 6.2 트리 복원: 위상 정렬 + DFS로 content 배열 재조립
- [ ] 6.3 드래그 앤 드롭 리팩토링: 노드 순서 변경, 섹션 병합, 에지 재연결
- [ ] 6.4 실시간 동기화: Flow 변경 시 마크다운 에디터에 `editor.commands.setContent()`로 백신

---

## 파일 변경 요약

| 파일 | 작업 | 설명 |
|------|------|------|
| `app/frontend/package.json` | 수정 | `@xyflow/react`, `elkjs`, `uuid` 추가 |
| `app/frontend/src/index.css` | 수정 | `@import "@xyflow/react/dist/style.css"` 추가 |
| `app/frontend/src/utils/markdownToFlow.js` | **신규** | `marked.lexer()` 기반 헤딩 → 노드/에지 파서 |
| `app/frontend/src/utils/elkLayout.js` | **신규** | `elkjs/lib/elk.bundled.js` 레이아웃 계산 |
| `app/frontend/src/components/FlowViewer.jsx` | **신규** | React Flow 캔버스 + 커스텀 노드/엣지 |
| `app/frontend/src/pages/JobResultPage.jsx` | 수정 | 탭 → 드롭다운 교체, `previewMode`에 `"flow"` 추가 |
| `app/frontend/src/locales/{ko,en,ja}/page.json` | 수정 | flow 관련 i18n 키 추가 |
| `app/ai-backend/src/tools/flow.ts` | **신규** | AI 의존성 추론 도구 2개 |
| `app/ai-backend/src/chat/route.ts` | 수정 | `buildFlowTools` 등록 + 시스템 프롬프트 |

---

## 구현 순서

```
Phase 1 (의존성 설치) ──→ Phase 2 (파서) ──→ Phase 3 (FlowViewer) ──→ Phase 4 (드롭다운)
                                                                    │
                                                                    ▼
                                                              Phase 5 (AI 의존성)
                                                                    │
                                                                    ▼
                                                              Phase 6 (양방향 동기화, 향후)
```

## 검증 항목

- [x] npm build 성공 (frontend vite build ✓)
- [x] AI 백엔드 타입체크 성공 (tsc --noEmit ✓)
- [ ] 마크다운 뷰 → 플로우 뷰 전환 동작 (수동 확인 필요)
- [ ] 헤딩이 노드로 표시되고 계층 구조가 에지로 연결됨 (수동 확인 필요)
- [ ] elkjs 자동 레이아웃으로 노드가 겹치지 않음 (수동 확인 필요)
- [ ] 드롭다운이 기존 다운로드 드롭다운과 일관된 UX (수동 확인 필요)
