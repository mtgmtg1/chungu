import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import SourcePanel from "./SourcePanel.jsx";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key) => key }),
}));

vi.mock("../hooks/useMediaQuery.js", () => ({
  useIsMobile: () => false,
}));

vi.mock("../api.js", () => ({
  api: {},
}));

vi.mock("./PdfViewer.jsx", () => ({
  default: function MockPdfViewer({ url }) {
    return <div data-testid="pdf-viewer" data-url={url} />;
  },
}));

vi.mock("./MediaPlayer.jsx", () => ({
  default: function MockMediaPlayer() {
    return <div data-testid="media-player" />;
  },
}));

vi.mock("./AnnotationListPanel.jsx", () => ({
  default: function MockAnnotationListPanel() {
    return null;
  },
}));

vi.mock("react-resizable-panels", () => ({
  PanelGroup: ({ children }) => <>{children}</>,
  Panel: ({ children }) => <>{children}</>,
  PanelResizeHandle: () => null,
}));

const basePptxFile = {
  name: "slides.pptx",
  type: "pptx",
  url: "https://example.com/slides.pptx",
  preview_url: "https://example.com/slides.pdf",
  storage_path: "jobs/slides.pptx",
  bucket: "jobs",
  page_num: 1,
  source_index: 0,
  source_kind: "original",
  status: "done",
};

describe("SourcePanel pptx 미리보기", () => {
  it("pptx sourceFiles가 있으면 PdfViewer를 preview_url로 렌더링한다", () => {
    render(<SourcePanel sourceFiles={[basePptxFile]} />);

    const viewer = screen.getByTestId("pdf-viewer");
    expect(viewer).toBeInTheDocument();
    expect(viewer).toHaveAttribute("data-url", basePptxFile.preview_url);
  });

  it("preview_url이 없으면 url을 PdfViewer에 전달한다", () => {
    const file = { ...basePptxFile, preview_url: undefined };
    render(<SourcePanel sourceFiles={[file]} />);

    const viewer = screen.getByTestId("pdf-viewer");
    expect(viewer).toHaveAttribute("data-url", file.url);
  });

  it("sourceType이 pptx이고 sourceUrl이 있으면 PdfViewer를 렌더링한다", () => {
    render(<SourcePanel sourceFiles={[]} sourceUrl="https://example.com/slides.pdf" sourceType="pptx" />);

    const viewer = screen.getByTestId("pdf-viewer");
    expect(viewer).toBeInTheDocument();
    expect(viewer).toHaveAttribute("data-url", "https://example.com/slides.pdf");
  });
});
