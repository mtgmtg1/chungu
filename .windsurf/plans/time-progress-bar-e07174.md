# Time-based progress bar (capped at 84%)

PDF OCR 작업에서 실제 진행률이 늦게 보고되어 프로그레스 바가 멈춘 것처럼 느껴지는 문제를 해결하기 위해, 경과 시간 기반의 추정 진행률을 추가합니다. 시간 진행률은 84%까지만 상승하고, 실제 진행률이 시간 진행률을 넘어서거나 84%에 도달하면 실제 진행률로 표시합니다.

## 1. Logic

- `timePct = min(84, round((elapsedSeconds / totalPages) * 100))`
- `displayPct = actualPct >= 84 ? actualPct : max(actualPct, timePct)`
- 경과 시간은 `job.created_at` 기준으로 계산합니다.
- 1초마다 프론트엔드를 리렌더링하여 시간 진행률이 자연스럽게 증가합니다.

## 2. Changes

### 2.1 `app/frontend/src/utils/progress.js` (new)

- `getActualProgress(job)` — 실제 done/total 기반 퍼센트
- `getTimeProgress(job, maxTimePct = 84)` — 시간 기반 추정 퍼센트, 84%封顶
- `getDisplayProgress(job, maxTimePct = 84)` — max(actual, time), 84% 이상은 실제값

### 2.2 `app/frontend/src/pages/JobsPage.jsx`

- 1초 타이머 추가 (`useEffect` + `setInterval`)
- 데스크톱/모바일 progress bar 계산을 `getDisplayProgress(j)`로 교체
- 상세 진행 텍스트(예: "5 / 100 pages")는 실제 값 유지

### 2.3 `app/frontend/src/pages/JobResultPage.jsx`

- 1초 타이머 추가
- `pct` 계산을 `getDisplayProgress(job)`로 교체
- `PoetryProgress`의 bar와 퍼센트는 합산값, `progressText`는 실제 done/total 유지

### 2.4 `AGENTS.md`

- OCR Progress Reporting 섹션에 시간진행바(84% cap) 개념 추가

## 3. Verification

- `npm run build`로 빌드 오류 확인
- a1 배포 후 PDF 업로드하여 프로그레스 바가 0%부터 초당 상승하는지 확인

## 4. Deployment

- `git add` → `git commit` → `git push` → `bash deploy_a1.sh`
