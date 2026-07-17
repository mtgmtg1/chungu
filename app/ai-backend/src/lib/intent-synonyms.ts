// [Flow: Step 1 (사용자 발화 수신) -> Step 2 (카테고리별 키워드 매칭 및 점수 계산)
//       -> Step 3 (임계값을 넘은 카테고리의 정적 힌트 문자열 반환) -> Step 4 (빈 문자열 폴백)]
// 에이전트 채팅에서 '마크다운 에디터', '샌드박스' 같은 전문 용어를 모르는 사용자의
// 일상 언어를 기술 카테고리로 연결하기 위한 경량 의도 정규화 모듈.
// 사용자 입력 그대로를 시스템 프롬프트에 포함하지 않고, 미리 정의된 안내 문구만 반환한다.

/**
 * [Flow: Step 1 (카테고리 이름, 강/약 키워드, 힌트 정의) -> Step 2 (가중치/임계값 저장)
 *       -> Step 3 (scoreCategory에서 사용)]
 *
 * @property category 의도 식별자 (예: markdown, sandbox)
 * @property strongKeywords 강한 신호로 처리할 키워드 목록
 * @property weakKeywords 보조 신호로 처리할 키워드 목록
 * @property hint system prompt에 주입할 정적 안내 문구
 * @property strongWeight 강한 키워드 기본 가중치
 * @property weakWeight 약한 키워드 기본 가중치
 * @property threshold 해당 의도로 판단하는 최소 점수
 */
export interface IntentCategory {
  category: string;
  strongKeywords: string[];
  weakKeywords?: string[];
  hint: string;
  strongWeight?: number;
  weakWeight?: number;
  threshold?: number;
}

/**
 * [Flow: Step 1 (기본 의도 카테고리 정의) -> Step 2 (가중치/임계값 할당)
 *       -> Step 3 (buildIntentHint에서 조회)]
 *
 * 마크다운 에디터와 샌드박스에 대한 사용자 친화 표현을 사전에 매핑한다.
 * 한국어 키워드는 조사가 붙어도 인식할 수 있도록 부분 문자열 매칭을 사용하고,
 * 영어 키워드는 단어 경계를 고려하여 매칭한다.
 */
export const INTENT_CATEGORIES: IntentCategory[] = [
  {
    category: 'markdown',
    strongKeywords: [
      '마크다운',
      '보고서',
      '메모',
      '메모장',
      '글쓰기',
      '작성',
      '편집',
      '수정',
      '정리',
      '요약',
      '에디터',
      'editor',
      '문서화',
    ],
    weakKeywords: ['글', '문서', '내용', '섹션', '제목', '목차', '표', '단락'],
    hint:
      'If the user is asking about writing, editing, organizing, or formatting a report, document, memo, or text (Korean terms: 보고서, 메모, 글쓰기, 편집, 수정, 정리, 요약), treat the request as targeting the markdown editor tools: get_section, get_table, replace_selection, insert_at, apply_edits.',
    strongWeight: 3,
    weakWeight: 1,
    threshold: 3,
  },
  {
    category: 'sandbox',
    strongKeywords: [
      '샌드박스',
      '코드',
      '파이썬',
      'python',
      '스크립트',
      'script',
      '프로그램',
      '실행',
      '돌리',
      '테스트',
      '디버깅',
      '컴파일',
      'pip',
      'npm',
      'git',
      '셸',
      '터미널',
      'bash',
      'shell',
      '명령어',
      '계산',
    ],
    weakKeywords: ['코딩', '자동화', '변환', '처리', '만들기', '생성'],
    hint:
      'If the user is asking about running code, Python, scripts, programs, calculations, or testing in an isolated environment (Korean terms: 샌드박스, 코드, 파이썬, 스크립트, 프로그램, 실행, 돌리, 테스트, 계산), treat the request as targeting the sandbox tools: create_sandbox, execute_in_sandbox, read_sandbox_file, etc. Always call create_sandbox first if no sandbox exists.',
    strongWeight: 3,
    weakWeight: 1,
    threshold: 3,
  },
];

/**
 * [Flow: Step 1 (정규화된 텍스트와 키워드 수신) -> Step 2 (키워드 종류에 따라 매칭)
 *       -> Step 3 (매칭 여부 반환)]
 *
 * 영어 키워드는 단어 경계(\b)를 사용해 description 같은 단어 내부 매칭을 방지하고,
 * 한국어 키워드는 조사/어미가 붙은 형태도 잡기 위해 부분 문자열 매칭을 사용한다.
 *
 * @param normalizedText 소문자/구두점 정리된 사용자 발화
 * @param keyword 매칭할 키워드
 * @returns 매칭되면 true
 */
function isKeywordMatched(normalizedText: string, keyword: string): boolean {
  const isAsciiOnly = /^[a-zA-Z0-9_-]+$/.test(keyword);

  if (isAsciiOnly) {
    const escaped = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(`(?<![a-zA-Z0-9])${escaped}(?![a-zA-Z0-9])`, 'i');
    return regex.test(normalizedText);
  }

  return normalizedText.includes(keyword.toLowerCase());
}

/**
 * [Flow: Step 1 (카테고리와 정규화 텍스트 수신) -> Step 2 (강/약 키워드 각각 매칭)
 *       -> Step 3 (가중치 합산) -> Step 4 (점수 반환)]
 *
 * @param category 의도 카테고리
 * @param normalizedText 정규화된 사용자 발화
 * @returns 계산된 의도 점수
 */
function scoreCategory(category: IntentCategory, normalizedText: string): number {
  const strongWeight = category.strongWeight ?? 3;
  const weakWeight = category.weakWeight ?? 1;

  const strongMatches = category.strongKeywords.filter((keyword) =>
    isKeywordMatched(normalizedText, keyword),
  ).length;

  const weakMatches = (category.weakKeywords ?? []).filter((keyword) =>
    isKeywordMatched(normalizedText, keyword),
  ).length;

  return strongMatches * strongWeight + weakMatches * weakWeight;
}

/**
 * [Flow: Step 1 (사용자 발화 수신) -> Step 2 (소문자/구두점 정규화)
 *       -> Step 3 (카테고리별 점수 산출) -> Step 4 (임계값 이상 카테고리 필터)
 *       -> Step 5 (힌트 문자열 조합) -> Step 6 (빈 문자열이면 폴백)]
 *
 * @param userMessage 마지막 사용자 메시지 텍스트
 * @returns system prompt에 추가할 정적 힌트 문자열 (해당 의도가 없으면 빈 문자열)
 */
export function buildIntentHint(userMessage: string | undefined): string {
  if (!userMessage) return '';

  const normalizedText = userMessage
    .toLowerCase()
    .replace(/[\p{P}\p{S}]/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();

  if (!normalizedText) return '';

  const scored = INTENT_CATEGORIES.map((category) => ({
    category,
    score: scoreCategory(category, normalizedText),
  }));

  const hints = scored
    .filter(({ category, score }) => score >= (category.threshold ?? 3))
    .map(({ category }) => category.hint);

  if (hints.length === 0) return '';

  return 'User intent hint: ' + hints.join(' ') + '\n';
}
