// [Flow: Step 1 (페이지 진입) -> Step 2 (i18n으로 다국어 푸터 렌더링) -> Step 3 (저작권·법률 링크 표시)]
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

/**
 * 모든 페이지에서 공통으로 사용하는 글로벌 푸터 컴포넌트
 * 저작권 정보, 서비스 이용약관, 개인정보처리방침, 환불 정책, API 문서, 관리자 링크 포함
 * @returns {JSX.Element} 푸터 영역
 */
export default function GlobalFooter() {
  const { t } = useTranslation();

  return (
    <footer className="w-full py-8 border-t border-outline-variant/20" data-oid="global-footer">
      <div className="max-w-container-max mx-auto px-gutter flex flex-col md:flex-row justify-between items-center gap-4 text-label-sm text-outline" data-oid="global-footer-inner">
        <div className="flex items-center gap-4" data-oid="global-footer-copyright">
          <p data-oid="global-footer-copy-text">{t("page:upload.copyright")}</p>
        </div>
        <div className="flex items-center gap-6" data-oid="global-footer-links">
          <Link
            to="/terms"
            className="hover:text-primary transition-colors"
            data-oid="global-footer-terms">
            {t("common:footer.terms")}
          </Link>
          <Link
            to="/privacy"
            className="hover:text-primary transition-colors"
            data-oid="global-footer-privacy">
            {t("common:footer.privacy")}
          </Link>
          <Link
            to="/refund-policy"
            className="hover:text-primary transition-colors"
            data-oid="global-footer-refund">
            {t("common:footer.refundPolicy")}
          </Link>
          <a
            href="/docs"
            className="hover:text-primary transition-colors"
            data-oid="global-footer-docs">
            {t("page:upload.api")}
          </a>
          <a
            href="/admin"
            className="hover:text-primary transition-colors"
            data-oid="global-footer-admin">
            {t("page:upload.admin")}
          </a>
        </div>
      </div>
    </footer>
  );
}
