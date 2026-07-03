// [Flow: Step 1 (개발 mock 사용자 정의) -> Step 2 (AuthContext에서 세션/사용자 객체로 사용)]
/** 개발 모드에서 백엔드 없이 UI를 볼 때 사용하는 mock 사용자입니다. */
export const MOCK_DEV_USER = {
  id: "dev-user-001",
  email: "dev@proof.local",
  user_metadata: { language: "ko" },
  role: "authenticated",
  app_metadata: { is_admin: true },
  aud: "authenticated",
};

/** 개발 mock 세션입니다. access_token은 api.js에서 mock 모드를 감지하는 데 사용됩니다. */
export const MOCK_DEV_SESSION = {
  access_token: "dev-mock-token",
  refresh_token: "dev-mock-refresh",
  expires_in: 365 * 24 * 60 * 60,
  expires_at: Date.now() + 365 * 24 * 60 * 60 * 1000,
  token_type: "bearer",
  user: MOCK_DEV_USER,
};
