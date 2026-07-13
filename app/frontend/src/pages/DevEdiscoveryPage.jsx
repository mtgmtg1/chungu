// [Flow: Step 1 (개발 mock 활성화) -> Step 2 (샘플 Job으로 EDiscoveryViewer 렌더링)
//       -> Step 3 (Graph 탭: 스윔레인 타임라인 + 모순 엣지) -> Step 4 (Mapper 탭: 요건사실 퍼즐 DnD)
//       -> Step 5 (언마운트 시 mock 비활성화)]
// 로컬 개발 모드에서 백엔드 없이 e-Discovery UI를 샘플 데이터로 미리보기하는 개발 전용 페이지.
// import.meta.env.DEV일 때만 라우팅되므로 production 빌드에는 포함되지 않는다.
import { useEffect, Component } from "react";
import EDiscoveryViewer from "../components/EDiscoveryViewer.jsx";
import { enableDevMock } from "../api.js";
import { SAMPLE_JOB } from "../dev/ediscoverySampleData.js";

class QAErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null, info: null };
  }
  componentDidCatch(error, info) {
    // eslint-disable-next-line no-console
    console.error("QA_ERROR_BOUNDARY:", error, info);
    this.setState({ error, info });
  }
  render() {
    if (this.state.error) {
      return (
        <div className="p-4 text-red-600 whitespace-pre-wrap">
          <h1 className="font-bold">Render Error</h1>
          <p>{this.state.error.message}</p>
          <p>{this.state.error.stack}</p>
        </div>
      );
    }
    return this.props.children;
  }
}

/**
 * DevEdiscoveryPage — e-Discovery UI 개발 미리보기 페이지.
 * 마운트 시 dev mock을 활성화해 legal-elements/mappings API 호출을 가로채고,
 * 샘플 Job 데이터로 EDiscoveryViewer(Graph + Mapper 탭)를 렌더링한다.
 */
export default function DevEdiscoveryPage() {
  // 개발 환경에서는 전역 mock이 활성화되어 있으므로 별도 cleanup 없이 유지한다.
  useEffect(() => {
    enableDevMock(true);
  }, []);

  return (
    <div className="h-screen w-screen flex flex-col" data-oid="dev-ediscovery-page">
      {/* 개발 전용 안내 배너 */}
      <div className="flex items-center gap-2 px-4 py-2 bg-amber-50 border-b border-amber-200 text-amber-800 text-xs flex-shrink-0">
        <span className="font-bold">[DEV]</span>
        <span>
          e-Discovery UI 샘플 데이터 미리보기 — 사기죄 사건 예시. Timeline 탭(수평 시간축)과 Mapper
          탭(요건사실 퍼즐)을 전환할 수 있습니다.
        </span>
      </div>
      {/* e-Discovery 뷰어 — 전체 영역 차지 */}
      <div className="flex-1 min-h-0">
        <QAErrorBoundary>
          <EDiscoveryViewer
            jobId={SAMPLE_JOB.job_id}
            job={SAMPLE_JOB}
            onNodeClick={() => {}}
            onJobRefresh={() => Promise.resolve()}
          />
        </QAErrorBoundary>
      </div>
    </div>
  );
}
