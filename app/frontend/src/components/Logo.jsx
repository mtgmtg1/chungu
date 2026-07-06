// [Flow: Step 1 (크기 prop 해석) -> Step 2 (공통 로고 이미지 렌더링) -> Step 3 (링크 래핑 여부 적용)]
import { Link } from "react-router-dom";

/**
 * PROOF 앱의 공식 로고를 렌더링하는 재사용 컴포넌트.
 * 네비게이션, 사이드바, 랜딩 페이지 등 주요 브랜드 노출 위치에서 사용.
 *
 * @param {string} [className] - 추가 Tailwind 클래스 (크기/여백 등 미세 조정)
 * @param {string} [height]    - 이미지 높이 (기본값 "40px"). 너비는 가로비(1.83:1)에 맞춰 자동 산출.
 * @param {boolean} [toHome]   - true면 로고를 클릭했을 때 루트("/")로 이동하는 Link로 래핑 (기본값 true)
 * @param {string} [imgClassName] - <img> 요소에 전달할 추가 클래스
 * @returns {JSX.Element} 로고 요소
 */
export default function Logo({ className = "", height = "40px", toHome = true, imgClassName = "" }) {
  // 공통 로고 이미지 마크업 — public/proof-logo.png 사용 (Vite가 루트 경로로 서빙)
  const logoImg = (
    <img
      src="/proof-logo.png"
      alt="PROOF"
      style={{ height, width: "auto" }}
      className={`object-contain select-none ${imgClassName}`}
      draggable={false}
    />
  );

  // 링크 래핑이 불필요한 경우(예: 이미 Link 내부에 중첩) bare 이미지 반환
  if (!toHome) return <div className={className}>{logoImg}</div>;

  return (
    <Link to="/" className={`inline-flex items-center ${className}`}>
      {logoImg}
    </Link>
  );
}
