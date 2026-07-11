// [Flow: Step 1 (matchMedia 쿼리 문자열 수신) -> Step 2 (초기 상태 동기 설정)
//       -> Step 3 (resize 이벤트 대신 matchMedia change 리스너 등록 — debounce 불필요)
//       -> Step 4 (언마운트 시 리스너 제거) -> Step 5 (boolean 매칭 결과 반환)]
import { useEffect, useState } from "react";

/**
 * CSS 미디어 쿼리 결과를 React 상태로 반환하는 훅.
 * matchMedia API를 사용하므로 resize 이벤트 폴링보다 성능이 우수하며,
 * 브라우저가 미디어 쿼리 변경 시점을 최적화하여 콜백을 호출한다.
 *
 * @param {string} query - matchMedia에 전달할 CSS 미디어 쿼리 문자열 (예: "(max-width: 767px)")
 * @returns {boolean} 쿼리 매칭 여부 (SSR 환경이거나 window가 없으면 false)
 *
 * 사용 예:
 *   const isMobile = useMediaQuery("(max-width: 767px)");
 *   const isTablet = useMediaQuery("(min-width: 768px) and (max-width: 1023px)");
 */
export function useMediaQuery(query) {
  // [Flow: SSR 안전 — window가 없는 환경(빌드 타임 등)에서는 false 반환]
  const getInitialMatch = () => {
    if (typeof window === "undefined" || !window.matchMedia) return false;
    return window.matchMedia(query).matches;
  };

  const [matches, setMatches] = useState(getInitialMatch);

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;

    const mediaQueryList = window.matchMedia(query);
    // [Flow: 컴포넌트 마운트 시점에 최신 매칭 상태로 동기화 — SSR hydration 불일치 방지]
    setMatches(mediaQueryList.matches);

    const handleChange = (event) => setMatches(event.matches);

    // addEventListener를 지원하는 최신 브라우저 경로
    if (mediaQueryList.addEventListener) {
      mediaQueryList.addEventListener("change", handleChange);
      return () => mediaQueryList.removeEventListener("change", handleChange);
    }

    // 구형 Safari fallback — addListener/removeListener 사용
    mediaQueryList.addListener(handleChange);
    return () => mediaQueryList.removeListener(handleChange);
  }, [query]);

  return matches;
}

/**
 * 모바일 화면(768px 미만) 여부를 반환하는 편의 훅.
 * Tailwind의 md 브레이크포인트(768px)와 정확히 일치하도록 767px 기준.
 *
 * @returns {boolean} 모바일 화면 여부
 */
export function useIsMobile() {
  return useMediaQuery("(max-width: 767px)");
}
