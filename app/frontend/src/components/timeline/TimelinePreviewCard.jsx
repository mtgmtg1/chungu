// [Flow: Step 1 (노드 + sourceFiles 맵 수신) -> Step 2 (노드 page에 해당하는 sourceFile 조회)
//       -> Step 3 (sourceFile/type에 따라 PDF iframe / 이미지 / 오디오 / 비디오 / 텍스트 렌더링 분기)
//       -> Step 4 (미리보기 카드 UI 반환, sourceFile 없으면 요약 텍스트 폴백)]
// React Chrono 타임라인 카드 중앙에 표시되는 자료 미리보기 카드.
// PDF, 이미지, 오디오, 비디오, 텍스트/파일, 그리고 요약 텍스트 폴백을 한 카드 안에서 처리한다.

import { useTranslation } from "react-i18next";
import {
  FileText,
  ImageIcon,
  Volume2,
  Film,
  FileDown,
  Loader2,
  AlertCircle,
} from "lucide-react";

/**
 * 노드가 가리키는 페이지 번호를 반환한다. 숫자가 아니면 1을 기본값으로 사용한다.
 *
 * @param {Object} node - e-Discovery graph 노드
 * @returns {number} 1-based 페이지 번호
 */
function getNodePage(node) {
  const page = node?.data?.page;
  return typeof page === "number" && page > 0 ? page : 1;
}

/**
 * 노드에서 요약/라벨 텍스트를 안전하게 추출한다.
 *
 * @param {Object} node - e-Discovery graph 노드
 * @returns {string} 요약 또는 라벨 텍스트
 */
function getNodeSummary(node) {
  return node?.data?.summary || node?.data?.label || node?.id || "";
}

/**
 * page 번호에 맞는 sourceFile을 찾는다.
 * 정확히 일치하는 page_num이 없으면 PDF/문서 타입을 우선으로 폴백한다.
 *
 * @param {Object} node - e-Discovery graph 노드
 * @param {Object} previewData - { sourceFiles: Array<{}> } 형태의 미리보기 메타데이터
 * @returns {Object|null} sourceFile 객체 또는 null
 */
function findSourceFile(node, previewData) {
  if (!previewData?.sourceFiles?.length) return null;
  const page = getNodePage(node);
  const files = previewData.sourceFiles;

  const exact = files.find((f) => f.page_num === page);
  if (exact) return exact;

  const docFallback = files.find((f) => ["pdf", "docx", "hwp"].includes(f.type));
  if (docFallback) return docFallback;

  return files[0] || null;
}

/**
 * TimelinePreviewCard — React Chrono 카드 중앙에 렌더링되는 자료 미리보기 카드.
 *
 * @param {Object} props
 * @param {Object} props.node - e-Discovery graph 노드
 * @param {Object} [props.previewData] - sourceFiles가 포함된 미리보기 메타데이터
 */
export default function TimelinePreviewCard({ node, previewData }) {
  const { t } = useTranslation();
  const sourceFile = findSourceFile(node, previewData);
  const page = getNodePage(node);
  const summary = getNodeSummary(node);

  const type = sourceFile?.type;
  // HTTPS 사이트에서 HTTP 리소스를 로드하면 Mixed Content 에러가 발생하므로 scheme를 강제 변환한다.
  const url = (sourceFile?.preview_url || sourceFile?.url || "").replace(/^http:/, "https:");
  const name = sourceFile?.name || "";

  /**
   * [Flow: Step 1 (텍스트 콘텐츠 결정) -> Step 2 (최대 200자로 제한)
   *       -> Step 3 (줄바꿈 유지하되 앞뒤 공백 제거)]
   */
  const textSnippet = (() => {
    const raw = sourceFile?.result_markdown || summary;
    if (!raw) return "";
    return raw.trim().slice(0, 200).replace(/\n+/g, " ");
  })();

  // [Flow: sourceFile 로딩 중이면 스켈레톤 표시]
  if (!previewData) {
    return (
      <div className="flex flex-col h-full w-full items-center justify-center gap-2 p-3 text-on-surface-variant bg-surface-container-lowest rounded border border-outline-variant">
        <Loader2 size={20} className="animate-spin text-primary" />
        <span className="text-[10px]">{t("page:result.ediscoveryPreviewLoading")}</span>
      </div>
    );
  }

  // [Flow: PDF/문서 파일은 iframe + #page 앵커로 페이지 단위 미리보기]
  if (type === "pdf" || type === "docx" || type === "hwp") {
    if (!url) {
      return (
        <PreviewPlaceholder
          icon={<FileText size={24} className="text-tertiary" />}
          label={name || t("page:result.ediscoveryDocument")}
          summary={summary}
        />
      );
    }
    const src = type === "pdf" ? `${url}#page=${page}` : url;
    return (
      <div className="flex flex-col h-full w-full bg-surface-container-lowest rounded border border-outline-variant overflow-hidden">
        <div className="flex items-center gap-1.5 px-2 py-1 border-b border-outline-variant bg-surface-container-low text-[10px] text-on-surface-variant">
          <FileText size={12} />
          <span className="truncate">{name || t("page:result.ediscoveryDocument")}</span>
          <span className="ml-auto text-[10px]">p.{page}</span>
        </div>
        <iframe
          src={src}
          title={name}
          className="flex-1 w-full min-h-0 bg-white"
          loading="lazy"
        />
      </div>
    );
  }

  // [Flow: 이미지 파일은 img 태그로 원본 이미지 미리보기]
  if (type === "image") {
    const imageUrl = sourceFile?.url || url;
    if (!imageUrl) {
      return (
        <PreviewPlaceholder
          icon={<ImageIcon size={24} className="text-primary" />}
          label={name || t("page:result.ediscoveryImage")}
          summary={summary}
        />
      );
    }
    return (
      <div className="flex flex-col h-full w-full bg-surface-container-lowest rounded border border-outline-variant overflow-hidden">
        <div className="flex items-center gap-1.5 px-2 py-1 border-b border-outline-variant bg-surface-container-low text-[10px] text-on-surface-variant">
          <ImageIcon size={12} />
          <span className="truncate">{name || t("page:result.ediscoveryImage")}</span>
          <span className="ml-auto text-[10px]">p.{page}</span>
        </div>
        <img
          src={imageUrl}
          alt={summary}
          className="flex-1 w-full min-h-0 object-contain bg-black/5"
          loading="lazy"
        />
      </div>
    );
  }

  // [Flow: 비디오 파일은 native video 태그로 재생]
  if (type === "video") {
    if (!url) {
      return (
        <PreviewPlaceholder
          icon={<Film size={24} className="text-tertiary" />}
          label={name || t("page:result.ediscoveryVideo")}
          summary={summary}
        />
      );
    }
    return (
      <div className="flex flex-col h-full w-full bg-surface-container-lowest rounded border border-outline-variant overflow-hidden">
        <div className="flex items-center gap-1.5 px-2 py-1 border-b border-outline-variant bg-surface-container-low text-[10px] text-on-surface-variant">
          <Film size={12} />
          <span className="truncate">{name || t("page:result.ediscoveryVideo")}</span>
        </div>
        <video
          src={url}
          controls
          className="flex-1 w-full min-h-0 bg-black rounded-b"
          preload="metadata"
        />
      </div>
    );
  }

  // [Flow: 오디오 파일은 native audio 태그 + 텍스트 추출(날짜/요약)로 구성]
  if (type === "audio") {
    if (!url) {
      return (
        <PreviewPlaceholder
          icon={<Volume2 size={24} className="text-secondary" />}
          label={name || t("page:result.ediscoveryAudio")}
          summary={summary}
        />
      );
    }
    return (
      <div className="flex flex-col h-full w-full bg-surface-container-lowest rounded border border-outline-variant overflow-hidden p-2 gap-2">
        <div className="flex items-center gap-1.5 text-[10px] text-on-surface-variant">
          <Volume2 size={12} />
          <span className="truncate">{name || t("page:result.ediscoveryAudio")}</span>
        </div>
        <audio src={url} controls className="w-full" preload="metadata" />
        {textSnippet && (
          <p className="text-[10px] text-on-surface-variant line-clamp-3 bg-surface-container-low rounded p-1.5">
            {textSnippet}
          </p>
        )}
      </div>
    );
  }

  // [Flow: file/텍스트 파일은 텍스트 스니펫 폴백, 없으면 다운로드 링크]
  if (type === "file" || textSnippet) {
    return (
      <div className="flex flex-col h-full w-full bg-surface-container-lowest rounded border border-outline-variant overflow-hidden p-2 gap-2">
        <div className="flex items-center gap-1.5 text-[10px] text-on-surface-variant">
          <FileDown size={12} />
          <span className="truncate">{name || t("page:result.ediscoveryText")}</span>
        </div>
        {textSnippet ? (
          <p className="text-[10px] text-on-surface line-clamp-6 bg-surface-container-low rounded p-1.5 overflow-auto">
            {textSnippet}
          </p>
        ) : (
          <a
            href={url}
            download={name}
            className="mt-auto flex items-center justify-center gap-1 px-2 py-1 bg-primary text-white text-[10px] rounded hover:opacity-90 transition-opacity"
          >
            <FileDown size={12} />
            {t("common:download")}
          </a>
        )}
      </div>
    );
  }

  // [Flow: sourceFile이 없거나 타입을 알 수 없으면 요약 텍스트 카드로 폴백]
  return (
    <PreviewPlaceholder
      icon={<AlertCircle size={24} className="text-outline" />}
      label={t("page:result.ediscoveryNoPreview")}
      summary={summary}
    />
  );
}

/**
 * PreviewPlaceholder — 미디어를 렌더링할 수 없을 때 사용하는 아이콘 + 요약 텍스트 카드.
 *
 * @param {Object} props
 * @param {React.ReactNode} props.icon - 상단 아이콘
 * @param {string} props.label - 파일/유형 라벨
 * @param {string} props.summary - 노드 요약
 */
function PreviewPlaceholder({ icon, label, summary }) {
  return (
    <div className="flex flex-col h-full w-full items-center justify-center gap-2 p-3 text-center bg-surface-container-lowest rounded border border-outline-variant overflow-hidden">
      {icon}
      <p className="text-[10px] font-medium text-on-surface line-clamp-1">{label}</p>
      {summary && (
        <p className="text-[10px] text-on-surface-variant line-clamp-3">{summary}</p>
      )}
    </div>
  );
}
