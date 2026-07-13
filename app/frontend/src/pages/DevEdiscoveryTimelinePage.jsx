// [Flow: Step 1 (개발 mock 활성화) -> Step 2 (EdiscoveryTimelinePanel에 샘플 Job 전달)
//       -> Step 3 (React Chrono 3.x 수직 타임라인 UI를 전체 화면에서 디버깅)]
// e-Discovery Timeline Panel을 별도로 개발/디버깅하기 위한 개발 전용 페이지.
// import.meta.env.DEV일 때만 라우팅되며 production 빌드에는 포함되지 않는다.

import { useEffect } from "react";
import EdiscoveryTimelinePanel from "../components/timeline/EdiscoveryTimelinePanel.jsx";
import { SAMPLE_JOB } from "../dev/ediscoverySampleData.js";
import { enableDevMock } from "../api.js";

/**
 * DevEdiscoveryTimelinePage — e-Discovery Timeline Panel을 전체 화면에서 디버깅하는 개발 페이지.
 */
export default function DevEdiscoveryTimelinePage() {
  // 개발 환경에서 API mock 활성화
  useEffect(() => {
    enableDevMock(true);
  }, []);

  return (
    <div className="h-screen w-screen flex flex-col" data-oid="dev-ediscovery-timeline-page">
      {/* 개발 전용 안내 배너 */}
      <div className="flex items-center gap-2 px-4 py-2 bg-amber-50 border-b border-amber-200 text-amber-800 text-xs flex-shrink-0">
        <span className="font-bold">[DEV]</span>
        <span>e-Discovery Timeline Panel 단독 디버깅 페이지</span>
      </div>

      {/* 타임라인 패널 전체 영역 */}
      <div className="flex-1 min-h-0">
        <EdiscoveryTimelinePanel
          jobId={SAMPLE_JOB.job_id}
          job={SAMPLE_JOB}
          onNodeClick={() => {}}
          onPreview={() => {}}
        />
      </div>
    </div>
  );
}
