// [Flow: Step 1 (AuthContext에서 user/loading 확인) -> Step 2 (loading이면 스피너) -> Step 3 (비로그인이면 AuthPage 렌더링) -> Step 4 (로그인이면 children 렌더링)]
import { useAuth } from "../AuthContext.jsx";
import AuthPage from "../pages/AuthPage.jsx";

/**
 * 로그인이 필요한 라우트를 감싸는 보호 컴포넌트.
 * @param {Object} props
 * @param {React.ReactNode} props.children - 로그인 상태일 때 렌더링할 콘텐츠
 * @returns {React.ReactNode}
 */
export default function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen bg-background flex items-center justify-center" data-oid="protected-loading">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" data-oid="protected-spinner"></div>
      </div>
    );
  }

  if (!user) {
    return <AuthPage />;
  }

  return children;
}
