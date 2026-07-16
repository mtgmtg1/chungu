// Temporary reproduction test for timeline card editing and layout issues.
import { describe, it, expect, vi, beforeAll } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
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
});
