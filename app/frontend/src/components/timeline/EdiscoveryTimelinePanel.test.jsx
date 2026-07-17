// [Flow: Step 1 (가짜 e-Discovery graph 노드 + sourceFiles 생성)
//       -> Step 2 (buildChronoItem 호출) -> Step 3 (media prop 생성 여부 및 타입 검증)]
// EdiscoveryTimelinePanel의 buildChronoItem이 sourceFiles 타입에 따라 올바른 React Chrono media prop을 생성하는지 검증.

import { describe, it, expect } from "vitest";
import { buildChronoItem } from "./EdiscoveryTimelinePanel.jsx";

/** 테스트용 i18n translate 함수. */
const t = (key) => key;

/**
 * 테스트용 e-Discovery 노드를 생성한다.
 *
 * @param {string} id - 노드 ID
 * @param {string} type - 노드 타입
 * @param {string} entity - entity 값
 * @param {number} page - 페이지 번호
 * @param {string} label - 라벨
 * @returns {Object} e-Discovery graph 노드
 */
function baseNode(id, type, entity, page, label = id) {
  return {
    id,
    type,
    data: { label, page, entity, summary: `${label} summary` },
  };
}

describe("buildChronoItem", () => {
  it("image sourceFile이면 IMAGE media prop을 생성한다", () => {
    const node = baseNode("img-1", "evidence", "third_party", 1, "image evidence");
    const sourceFiles = [{ page_num: 1, type: "image", url: "https://example.com/img.jpg", name: "img.jpg" }];
    const item = buildChronoItem(node, sourceFiles, t);
    expect(item.media).toEqual({ type: "IMAGE", source: { url: "https://example.com/img.jpg" }, name: "img.jpg" });
  });

  it("video sourceFile이면 VIDEO media prop을 생성한다", () => {
    const node = baseNode("vid-1", "evidence", "third_party", 2, "video evidence");
    const sourceFiles = [{ page_num: 2, type: "video", url: "https://example.com/vid.mp4", name: "vid.mp4" }];
    const item = buildChronoItem(node, sourceFiles, t);
    expect(item.media).toEqual({
      type: "VIDEO",
      source: { url: "https://example.com/vid.mp4", type: "mp4" },
      name: "vid.mp4",
    });
  });

  it("pdf sourceFile이면 PDF 썸네일 media prop을 생성한다", () => {
    const node = baseNode("pdf-1", "evidence", "third_party", 3, "pdf evidence");
    const sourceFiles = [{ page_num: 3, type: "pdf", url: "https://example.com/doc.pdf", name: "doc.pdf" }];
    const item = buildChronoItem(node, sourceFiles, t);
    expect(item.media).toEqual({ type: "IMAGE", source: { url: "/assets/pdf-thumbnail.svg" }, name: "doc.pdf" });
  });

  it("audio sourceFile이면 오디오 썸네일 media prop을 생성한다", () => {
    const node = baseNode("aud-1", "evidence", "third_party", 4, "audio evidence");
    const sourceFiles = [{ page_num: 4, type: "audio", url: "https://example.com/aud.mp3", name: "aud.mp3" }];
    const item = buildChronoItem(node, sourceFiles, t);
    expect(item.media).toEqual({ type: "IMAGE", source: { url: "/assets/audio-thumbnail.svg" }, name: "aud.mp3" });
  });

  it("sourceFiles가 없으면 media prop이 없다", () => {
    const node = baseNode("empty-1", "issue", "issue", 5, "empty issue");
    const item = buildChronoItem(node, [], t);
    expect(item.media).toBeUndefined();
  });

  it("HTTP URL이면 HTTPS로 강제 변환하여 Mixed Content를 방지한다", () => {
    const node = baseNode("img-http", "evidence", "third_party", 6, "http image");
    const sourceFiles = [{ page_num: 6, type: "image", url: "http://example.com/img.jpg", name: "img.jpg" }];
    const item = buildChronoItem(node, sourceFiles, t);
    expect(item.media.source.url).toBe("https://example.com/img.jpg");
  });

  it("isEditing이 true이면 media prop을 생성하지 않는다", () => {
    const node = baseNode("img-edit", "evidence", "third_party", 7, "image editing");
    const sourceFiles = [{ page_num: 7, type: "image", url: "https://example.com/img.jpg", name: "img.jpg" }];
    const item = buildChronoItem(node, sourceFiles, t, true);
    expect(item.media).toBeUndefined();
  });
});
