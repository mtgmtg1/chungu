// Temporary reproduction test for timeline card editing and layout issues.
import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import EdiscoveryTimelinePanel from "./EdiscoveryTimelinePanel.jsx";

beforeAll(() => {
  global.IntersectionObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

vi.mock("../../api.js", () => ({
  api: {
    saveEdiscoveryGraph: vi.fn(() => Promise.resolve({})),
  },
}));

const job = {
  id: "job-1",
  ediscovery_status: "done",
  ediscovery_graphs: {
    nodes: [
      {
        id: "node-1",
        type: "event",
        data: {
          label: "Event one",
          summary: "First summary",
          date: "2024-01-01",
          page: 1,
          entity: "plaintiff",
        },
      },
      {
        id: "node-2",
        type: "event",
        data: {
          label: "Event two",
          summary: "Second summary",
          date: "2024-01-02",
          page: 2,
          entity: "defendant",
        },
      },
    ],
    edges: [],
  },
};

const sourceFiles = [
  { page_num: 1, type: "pdf", url: "https://example.com/doc.pdf", name: "doc.pdf" },
];

describe("EdiscoveryTimelinePanel reproduction", () => {
  it("renders node content and allows editing label", async () => {
    const handleNodeClick = vi.fn();
    render(
      <EdiscoveryTimelinePanel
        jobId="job-1"
        job={job}
        sourceFiles={sourceFiles}
        onNodeClick={handleNodeClick}
      />
    );

    // wait for Chrono to render
    await waitFor(() => {
      expect(screen.getByText("Event one")).toBeInTheDocument();
    });

    // click the edit button in the custom card content
    const editBtn = screen.getAllByText("수정")[0];
    fireEvent.click(editBtn);

    // editing mode: input with the current label appears after remount
    const input = await waitFor(() => screen.getByDisplayValue("Event one"));

    // type in the label input
    fireEvent.change(input, { target: { value: "Updated one" } });

    await waitFor(() => {
      expect(input).toHaveValue("Updated one");
    });
  });

  it("완료를 눌러 수정한 이후에도 카드가 처음과 동일하게 보여야 한다", async () => {
    const handleNodeClick = vi.fn();
    const { container } = render(
      <EdiscoveryTimelinePanel
        jobId="job-1"
        job={job}
        sourceFiles={sourceFiles}
        onNodeClick={handleNodeClick}
      />
    );

    // Chrono 렌더링 대기
    await waitFor(() => {
      expect(container.querySelector('[data-oid="card-editor-read-node-1"]')).toBeInTheDocument();
    });

    const initialCard = container.querySelector('[data-oid="card-editor-read-node-1"]');
    const initialQueries = within(initialCard);

    // 초기 상태 기록
    expect(initialQueries.getByText("Event one")).toBeInTheDocument();
    expect(initialQueries.getByText("First summary")).toBeInTheDocument();
    expect(initialQueries.getByText("2024-01-01")).toBeInTheDocument();
    expect(initialQueries.getByText("원고")).toBeInTheDocument();

    // 첫 번째 카드 수정 버튼 클릭
    const editBtn = initialQueries.getByText("수정");
    fireEvent.click(editBtn);

    // 편집 모드 진입 확인
    const editCard = await waitFor(() =>
      container.querySelector('[data-oid="card-editor-edit-node-1"]')
    );
    expect(editCard).toBeInTheDocument();

    // 아무 변경 없이 완료 클릭
    const editQueries = within(editCard);
    const doneBtn = editQueries.getByText("완료");
    fireEvent.click(doneBtn);

    // 완료 후에도 초기 카드 내용이 그대로 보여야 함
    const finalCard = await waitFor(() =>
      container.querySelector('[data-oid="card-editor-read-node-1"]')
    );
    const finalQueries = within(finalCard);
    expect(finalQueries.getByText("Event one")).toBeInTheDocument();
    expect(finalQueries.getByText("First summary")).toBeInTheDocument();
    expect(finalQueries.getByText("2024-01-01")).toBeInTheDocument();
    expect(finalQueries.getByText("원고")).toBeInTheDocument();
  });

  it("entity가 없는 노드도 수정 후 일관된 entity 뱃지를 보여야 한다", async () => {
    const jobWithMissingEntity = {
      ...job,
      ediscovery_graphs: {
        ...job.ediscovery_graphs,
        nodes: [
          {
            id: "node-3",
            type: "event",
            data: {
              label: "Event three",
              summary: "Third summary",
              date: "2024-01-03",
              page: 3,
            },
          },
        ],
      },
    };

    const handleNodeClick = vi.fn();
    const { container } = render(
      <EdiscoveryTimelinePanel
        jobId="job-1"
        job={jobWithMissingEntity}
        sourceFiles={sourceFiles}
        onNodeClick={handleNodeClick}
      />
    );

    await waitFor(() => {
      expect(container.querySelector('[data-oid="card-editor-read-node-3"]')).toBeInTheDocument();
    });

    const initialCard = container.querySelector('[data-oid="card-editor-read-node-3"]');
    const initialQueries = within(initialCard);
    expect(initialQueries.getByText("Event three")).toBeInTheDocument();
    expect(initialQueries.getByText("제3자")).toBeInTheDocument();

    const editBtn = initialQueries.getByText("수정");
    fireEvent.click(editBtn);

    const editCard = await waitFor(() =>
      container.querySelector('[data-oid="card-editor-edit-node-3"]')
    );
    const editQueries = within(editCard);
    const doneBtn = editQueries.getByText("완료");
    fireEvent.click(doneBtn);

    const finalCard = await waitFor(() =>
      container.querySelector('[data-oid="card-editor-read-node-3"]')
    );
    const finalQueries = within(finalCard);
    expect(finalQueries.getByText("Event three")).toBeInTheDocument();
    expect(finalQueries.getByText("제3자")).toBeInTheDocument();
  });

  it("페이지 기반 노드(date 없음)의 요약이 40자 이내로 잘려서 렌더링된다", async () => {
    const jobWithPageNode = {
      ...job,
      ediscovery_graphs: {
        ...job.ediscovery_graphs,
        nodes: [
          {
            id: "node-page-only",
            type: "event",
            data: {
              label: "Page Only Event",
              summary: "이 요약문은 매우 길어서 40글자를 초과하게 작성되었습니다. 40글자가 넘어가면 뒤에는 중략 표시로 잘려서 나와야 합니다.",
              page: 4,
            },
          },
        ],
      },
    };

    const { container } = render(
      <EdiscoveryTimelinePanel
        jobId="job-1"
        job={jobWithPageNode}
        sourceFiles={sourceFiles}
        onNodeClick={() => {}}
      />
    );

    // 우측 패널 렌더링 대기
    const pageCard = await waitFor(() =>
      container.querySelector('[data-oid="card-editor-read-node-page-only"]')
    );
    expect(pageCard).toBeInTheDocument();

    const expectedSummary = "이 요약문은 매우 길어서 40글자를 초과하게 작성되었습니다. 40글자가 ...";
    expect(pageCard.textContent).toContain(expectedSummary);
  });
});
