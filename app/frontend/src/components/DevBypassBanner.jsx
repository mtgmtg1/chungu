// [Flow: Step 1 (devBypassMode가 mock인지 확인) -> Step 2 (고정 배너 렌더링)]
/** 개발 mock 모드일 때 상단에 표시되는 안내 배너입니다. */
export default function DevBypassBanner({ mode }) {
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
