# Paddle 준비 항목 보완 플랜

`proof.teamcat.app`의 `/terms`, `/privacy` 페이지를 실제로 노출하고 환불 정책 링크를 추가한 뒤 a1 서버에 배포하며, Paddle 심사용 테스트 계정을 생성하는 실행 플랜입니다.

## 1. 문제 요약

- 라이브 사이트에서 `/terms`, `/privacy`가 빈 페이지로 렌더링됨(React root에 내용 없음).
- 소스 코드에는 `LegalTermsPage.jsx`, `LegalPrivacyPage.jsx`, `common.json`의 3개 언어 번역이 모두 존재함 → 최신 빌드가 배포되지 않은 상태로 보임.
- 환불 정책은 `/terms` 5항에 포함되어 있으나, 별도 링크/페이지가 없음.
- 랜딩 페이지 푸터에 법적 링크가 없음(로그인 후 사이드바 레이아웃에는 이미 있음).
- `/payment`는 로그인 필요.

## 2. 변경 범위

### 2.1 `/terms`에 환불 정책 앵커 추가

- `app/frontend/src/pages/LegalTermsPage.jsx`의 5번째 `<section>`에 `id="refund-policy"` 추가.
- 목적: `/terms#refund-policy`로 직접 연결 가능하도록 하여 별도 페이지 없이도 Paddle 심사 요건 충족.

### 2.2 사이드바 레이아웃 푸터에 환불 정책 링크 추가

- `app/frontend/src/components/SidebarLayout.jsx`의 푸터 링크 그룹에 `Link` 추가.
- 경로: `/terms#refund-policy`
- i18n 키: `footer.refundPolicy`를 `common.json`의 en/ko/ja에 추가.

### 2.3 랜딩 페이지 푸터에 법적 링크 추가

- `app/frontend/src/pages/UploadPage.jsx`의 푸터 링크 그룹에 추가.
- 항목: Terms of Service, Privacy Policy, Refund Policy, API Docs, Contact Support.
- i18n 키: `page:upload.terms`, `page:upload.privacy`, `page:upload.refundPolicy` 등을 `page.json`의 en/ko/ja에 추가(또는 `common.json`의 `footer.*` 키 재사용).

### 2.4 i18n 번역 추가

- `app/frontend/src/locales/{en,ko,ja}/common.json`에 `footer.refundPolicy` 추가.
- `app/frontend/src/locales/{en,ko,ja}/page.json`에 랜딩 푸터용 키 추가(또는 common.json footer 키 재사용 시 생략).

### 2.5 빌드 및 a1 배포

- `cd app/frontend && npm run build`로 `dist/` 생성.
- `deploy_a1.sh` 실행 또는 수동 rsync + docker compose up.
- 배포 후 `https://proof.teamcat.app/terms`, `/privacy`가 3개 언어로 정상 노출되는지 브라우저 확인.

### 2.6 Paddle 심사용 테스트 계정 생성

- Supabase Auth에 `paddle-review@proof.teamcat.app` 또는 유사한 이메일로 계정 생성.
- 초기 크레딧 충전(예: 10 USD) — DB `users.points_balance` 직접 수정 또는 결제 테스트 크레딧 제공.
- 로그인 정보를 Paddle 심사팀에 안전하게 제공할 수 있는 형태로 정리.

### 2.7 재검증

- `/terms`, `/privacy`, `/terms#refund-policy` 브라우저 렌더링 확인.
- 랜딩 페이지 푸터 링크 확인.
- 로그인 후 `/payment` 페이지의 Paddle checkout UI 확인.
- 테스트 계정으로 실제 결제 흐름(금액 충전)이 정상 작동하는지 확인.

## 3. 예상 작업 순서

1. i18n 키 추가(en/ko/ja common.json, page.json).
2. `LegalTermsPage.jsx`에 `id="refund-policy"` 추가.
3. `SidebarLayout.jsx`에 환불 정책 링크 추가.
4. `UploadPage.jsx` 푸터에 법적 링크 추가.
5. 프론트엔드 빌드.
6. `deploy_a1.sh`로 배포.
7. 브라우저로 `/terms`, `/privacy`, `/` 확인.
8. Supabase Auth 테스트 계정 생성 및 크레딧 설정.
9. `/payment` 및 Paddle checkout 흐름 확인.
10. QA 리포트 업데이트 및 완료 메시지.

## 4. 리스크 및 주의사항

- `deploy_a1.sh`는 전체 `app/`을 동기화하고 docker compose를 재시작하므로, 현재 작업 중인 docs 변경사항도 함께 배포됨. 배포 전에 원하지 않는 변경은 stash 또는 분리할 것.
- Paddle 심사용 계정은 실제 결제 테스트 시 실제 카드가 필요할 수 있음. Paddle sandbox/test 카드 정보를 별도로 준비할 것.
- `/terms`와 `/privacy`가 빈 상태로 보이는 것이 단순히 배포 문제가 아니라 React 앱 마운트 문제일 수도 있으므로, 배포 후 즉시 확인 필수.

## 5. 파일 변경 예상 목록

- `app/frontend/src/pages/LegalTermsPage.jsx`
- `app/frontend/src/components/SidebarLayout.jsx`
- `app/frontend/src/pages/UploadPage.jsx`
- `app/frontend/src/locales/en/common.json`
- `app/frontend/src/locales/ko/common.json`
- `app/frontend/src/locales/ja/common.json`
- `app/frontend/src/locales/en/page.json`
- `app/frontend/src/locales/ko/page.json`
- `app/frontend/src/locales/ja/page.json`
- `app/frontend/dist/` (빌드 산출물)
- `.gstack/qa-reports/qa-report-proof-teamcat-app-2026-07-03.md` (검증 후 업데이트)

## 6. 완료 기준

- `/terms`와 `/privacy`에서 실제 약관/개인정보 텍스트가 3개 언어로 보임.
- `/terms#refund-policy`로 이동 시 환불 정책 섹션이 보임.
- 랜딩 페이지 푸터에 Terms / Privacy / Refund Policy 링크가 보임.
- a1 서버에 배포 완료.
- Paddle 심사용 계정이 생성되어 `/payment`와 Paddle checkout 흐름 확인 가능.

---

**플랜 확인 후 승인해 주시면 코드 수정과 배포를 시작하겠습니다.**
