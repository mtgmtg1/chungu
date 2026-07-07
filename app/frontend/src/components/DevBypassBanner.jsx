// [Flow: Step 1 (devBypassMode 값 확인) -> Step 2 (backend/mock 모드에 맞는 배너 렌더링)]
/** 개발 모드일 때 상단에 표시되는 안내 배너입니다. */
export default function DevBypassBanner({ mode }) {
  if (mode === "backend") {
    return (
      <div
        className="bg-blue-100 text-blue-800 text-xs px-4 py-1 text-center"
        data-oid="dev-bypass-banner"
      >
        [DEV] /api/dev/login 개발 인증 bypass로 로그인 중
      </div>
    );
  }

  if (mode === "apikey") {
    return (
      <div
        className="bg-green-100 text-green-800 text-xs px-4 py-1 text-center"
        data-oid="dev-bypass-banner"
      >
        [DEV] API key로 로컬 백엔드에 연결 중
      </div>
    );
  }

  if (mode !== "mock") return null;

  return (
    <div
      className="bg-amber-100 text-amber-800 text-xs px-4 py-1 text-center"
      data-oid="dev-bypass-banner"
    >
      [DEV] 백엔드 없이 mock 사용자로 UI 표시 중
    </div>
  );
}
