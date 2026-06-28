// [Flow: Step 1 (시 데이터 배열) -> Step 2 (슬라이드 인덱스 순환) -> Step 3 (로딩바 + 시 슬라이드 렌더링)]
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

const POEMS = [
  {
    title: "별 헤는 밤",
    author: "윤동주",
    lines: [
      "계절이 지나가는 하늘에는",
      "가을로 가득 차 있습니다.",
      "나는 아무 걱정도 없이",
      "가을 속의 별들을 다 헬 듯합니다.",
      "",
      "마음속에 하나둘 박히는 별들",
      "이제 다 헤어졌습니다.",
    ],
  },
  {
    title: "서시",
    author: "윤동주",
    lines: [
      "죽는 날까지 하늘을 우러러",
      "한 점 부끄럼이 없기를,",
      "잎새에 이는 바람에도",
      "나는 괴로워했다.",
      "",
      "별을 노래하는 마음으로",
      "모든 죽어가는 것을 사랑해야지",
      "그리고 나한테 주어진 길을",
      "걸어가야겠다.",
    ],
  },
  {
    title: "눈",
    author: "김수영",
    lines: [
      "눈은 살아 있다.",
      "떨어진 눈은 살아 있다.",
      "마당 위에 떨어진 눈은 살아 있다.",
      "",
      "기침을 하자.",
      "젊은 시인이여 기침을 하자.",
      "눈 위에 대고 기침을 하자.",
    ],
  },
  {
    title: "꽃",
    author: "김춘수",
    lines: [
      "내가 그의 이름을 불러주기 전에는",
      "그는 다만",
      "하나의 몸짓에 지나지 않았다.",
      "",
      "내가 그의 이름을 불러주었을 때",
      "그는 나에게로 와서",
      "꽃이 되었다.",
    ],
  },
  {
    title: "모란이 피기까지",
    author: "김영랑",
    lines: [
      "모란이 피기까지는",
      "아직 나는 한참 더 있어야 하리",
      "",
      "이제 모란은 피지 않으리",
      "모란이 피기까지는",
      "나는 이곳에 남아 있으리",
    ],
  },
  {
    title: "산유화",
    author: "이육사",
    lines: [
      "흰 보약수 같은",
      "산유화가",
      "바람에 흔들리며",
      "",
      "한들한들",
      "그 모양이",
      "더욱 슬프도다.",
    ],
  },
  {
    title: "청포도",
    author: "이육사",
    lines: [
      "내 고장 칠월은",
      "청포도가 익어가는 시절",
      "",
      "내 마음 구석구석",
      "청포도가 익어가는 시절",
      "내 마음 구석구석",
    ],
  },
  {
    title: "쉽게 쓰여진 시",
    author: "신동엽",
    lines: [
      "쉽게 쓰여진 아름다운 시",
      "그것은",
      "쉽게 쓰여진 것이 아니다",
      "",
      "불면의 밤을 견디며",
      "쉽게 쓰여진 것이 아니다",
    ],
  },
];

const SLIDE_INTERVAL = 5000;

export default function PoetryProgress({ pct, statusLabel, progressText }) {
  const { t } = useTranslation();
  const [slideIdx, setSlideIdx] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setSlideIdx((prev) => (prev + 1) % POEMS.length);
    }, SLIDE_INTERVAL);
    return () => clearInterval(timer);
  }, []);

  const poem = POEMS[slideIdx];

  return (
    <div
      className="flex-1 flex flex-col items-center justify-center p-6 bg-gradient-to-b from-surface to-surface-container"
      data-oid="poetry-progress"
    >
      {/* 시 슬라이드 */}
      <div
        className="max-w-lg w-full text-center mb-8 transition-opacity duration-1000"
        key={slideIdx}
        data-oid="poem-slide"
      >
        <h3
          className="text-lg font-semibold text-on-surface mb-1"
          data-oid="poem-title"
        >
          {poem.title}
        </h3>
        <p
          className="text-sm text-on-surface-variant mb-4"
          data-oid="poem-author"
        >
          — {poem.author}
        </p>
        <div
          className="space-y-1"
          data-oid="poem-lines"
        >
          {poem.lines.map((line, i) => (
            <p
              key={i}
              className={`text-base ${line === "" ? "h-4" : "text-on-surface-variant"} ${line === "" ? "" : "font-light"}`}
              data-oid={`poem-line-${i}`}
            >
              {line || "\u00A0"}
            </p>
          ))}
        </div>
      </div>

      {/* 로딩바 */}
      <div
        className="w-full max-w-md"
        data-oid="loading-bar"
      >
        <div
          className="flex items-center justify-between mb-2"
          data-oid="loading-header"
        >
          <span
            className="text-sm font-medium text-on-surface"
            data-oid="status-label"
          >
            {statusLabel}
          </span>
          <span
            className="text-sm text-on-surface-variant"
            data-oid="pct-label"
          >
            {pct}%
          </span>
        </div>
        <div
          className="h-2 bg-surface-container-high rounded-full overflow-hidden"
          data-oid="bar-track"
        >
          <div
            className="h-full bg-primary transition-all duration-500 ease-out"
            style={{ width: `${pct}%` }}
            data-oid="bar-fill"
          />
        </div>
        {progressText && (
          <p
            className="text-sm text-on-surface-variant mt-2 text-center"
            data-oid="progress-text"
          >
            {progressText}
          </p>
        )}
        <p
          className="text-xs text-on-surface-variant mt-4 text-center"
          data-oid="leave-notice"
        >
          {t("page:result.leaveNotice")}
        </p>
      </div>
    </div>
  );
}
