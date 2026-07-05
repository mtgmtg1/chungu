#!/usr/bin/env python3
# [Flow: Step 1 (사용자 컬럼/지시 입력) -> Step 2 (vision/hybrid 프롬프트 동적 생성)]
# 기존 9컬럼 고정 프롬프트를 사용자 정의 컬럼 기반으로 일반화.

DEFAULT_COLUMNS = [
    "연번", "구분", "계좌번호", "거래일자",
    "출금금액(원)", "입금금액(원)", "거래기록사항", "이체메모", "계정",
]


def build_vision_prompt(columns: list[str], extra: str = "") -> str:
    """이미지를 직접 보고 레이아웃을 보존한 마크다운으로 추출하라는 프롬프트."""
    cols = ", ".join(columns)
    base = (
        "이 페이지를 마크다운으로 변환하세요. "
        "절대로 표 형식으로 강제하지 마세요. 원문서의 시각적 레이아웃(제목, 단락, 항목, 공백, 표 위치, 글꼴 크기, 굵기, 들여쓰기, 열 구분, 정렬)을 최대한 그대로 보존하세요. "
        "페이지에 있는 모든 텍스트, 숫자, 날짜, 서명, 도장, 각주, 머리글, 바닥글, 페이지 번호, 로고, 배경 텍스트까지 누락 없이 추출하세요. "
        "표가 일부 있는 경우에도 그 일부만 표로 만들고, 원문서의 레이아웃을 따르는 자연스러운 마크다운으로 출력하세요. "
        "절대로 내용을 요약하거나 생략하지 마세요. 추론이나 해석은 추가하지 마세요. "
        "설명, 머리말, 마무리 문구는 절대 넣지 마세요. "
        "빈 셀은 공백으로 두고, 숫자와 콤마는 원본 그대로 쓰세요. "
        f"아래 컬럼({cols})은 참고용이며, 필요한 경우에만 해당 구조를 활용하세요."
    )
    return f"{base}\n추가 지시: {extra}" if extra.strip() else base


def build_text_prompt(columns: list[str], ocr_text: str, extra: str = "") -> str:
    """OCR 원문을 CSV로 구조화하라는 프롬프트."""
    header = ",".join(columns)
    instr = (
        "아래는 한 PDF 페이지의 OCR 원문입니다. "
        f"이를 {len(columns)}개 컬럼의 CSV로 변환하세요.\n"
        "규칙:\n"
        f"- CSV 헤더는: {header}\n"
        "- 설명, 마크다운, 코드 블록은 절대 출력하지 마세요. CSV 데이터만 출력하세요.\n"
        "- 각 행은 한 줄의 CSV 레코드입니다.\n"
        "- 금액의 콤마는 유지하세요.\n"
        "- 빈 셀은 비워두세요.\n"
        "- OCR 오류가 있으면 가능한 한 바로잡으세요.\n"
        "- 데이터가 없으면 헤더만 출력하세요.\n"
    )
    if extra.strip():
        instr += f"- 추가 지시: {extra}\n"
    return f"{instr}\nOCR 원문:\n{ocr_text}"


def build_media_prompt(columns: list[str], extra: str = "") -> str:
    """이미지에서 내용을 추출하는 프롬프트."""
    cols = ", ".join(columns) if columns else "내용"
    base = (
        "제공된 이미지를 분석하고, 원문서의 시각적 레이아웃을 최대한 그대로 보존한 마크다운으로 출력하세요. "
        "일부가 표라면 그 부분만 표로 만들고 절대로 전체를 표 형식으로 강제하지 마세요. "
        "이미지의 모든 텍스트, 숫자, 날짜, 서명, 도장, 각주, 머리글, 바닥글, 페이지 번호, 로고를 누락 없이 추출하세요. "
        "절대로 내용을 요약하거나 생략하지 마세요. 추론이나 해석은 추가하지 마세요. "
        "설명, 머리말, 마무리 문구는 절대 넣지 마세요. "
        f"아래 컬럼({cols})은 참고용이며, 필요한 경우에만 해당 구조를 활용하세요."
    )
    return f"{base}\n추가 지시: {extra}" if extra.strip() else base


def build_paddleocr_parameter_recommendation_prompt() -> str:
    """PaddleOCR-VL 파라미터를 자동 추천하도록 Vision LLM에 보내는 프롬프트."""
    return (
        "당신은 문서 OCR 레이아웃 전문가입니다. 첨부된 페이지 이미지를 보고, "
        "해당 문서를 PaddleOCR-VL로 가장 정확하게 파싱할 수 있는 파라미터를 JSON으로 추천하세요.\n\n"
        "먼저 문서의 전반적인 유형을 다음 중 하나로 판단하세요:\n"
        "- receipt (영수증): 짧은 종이, 기울어짐/왜곡 가능, 작은 글씨, 항목과 금액 중심\n"
        "- invoice (세금계산서/송장): 표 형식, 사업자번호/금액/품목 중심\n"
        "- form (양식): 칸/박스가 많고 사용자가 기입한 필드 중심\n"
        "- paper (논문/학술지): 단락, 제목, 섹션, 수식/도표 가능\n"
        "- table_heavy (표가 많은 보고서): 페이지 대부분이 표 또는 표와 텍스트 혼합\n"
        "- image_heavy (이미지/도면 중심): 텍스트보다 이미지/도표/도면이 많음\n"
        "- business_card (명함): 작은 카드, 로고, 짧은 텍스트\n"
        "- report (일반 보고서): 자연스러운 단락과 섹션, 가끔 표/이미지\n"
        "- mixed (혼합): 위의 유형 중 하나로 명확히 분류되지 않음\n\n"
        "다음 항목에 대해 true/false 또는 숫자/문자열로만 결정하세요:\n"
        "- layout_threshold: 레이아웃 모델이 영역을 인식할 최소 신뢰도 (0.1~0.9). "
        "  영수증/명함/작은 문서는 0.35, 양식/표 중심은 0.4~0.45, 일반 보고서/논문은 0.5를 권장합니다.\n"
        "- layout_merge_bboxes_mode: 중첩된 레이아웃 박스를 병합하는 방식. "
        "  'large'(가장 큰 박스만 남김), 'small'(가장 작은 박스만 남김), 'union'(모두 유지) 중 하나.\n"
        "- use_doc_orientation_classify: 문서가 90/180/270도 기울어져 있으면 true.\n"
        "- use_doc_unwarping: 문서가 구겨지거나 곡면(스캔/촬영)이면 true.\n"
        "- use_layout_detection: 레이아웃 분석을 사용하려면 true (거의 항상 true).\n"
        "- use_ocr_for_image_block: 이미지/도표 안에 숨겨진 텍스트를 추출하려면 true.\n"
        "- format_block_content: 결과를 마크다운 형식으로 깔끔하게 정리하려면 true.\n"
        "- layout_nms: 중첩 박스가 많아 후처리가 필요하면 true.\n"
        "- layout_unclip_ratio: 레이아웃 박스 확장 비율 (0.5~2.0). 일반적으로 1.0.\n"
        "- use_chart_recognition: 차트/그래프가 많고 수치 추출이 중요하면 true.\n"
        "- use_seal_recognition: 도장 인식이 필요하면 true.\n\n"
        "반드시 아래 JSON 형식으로만 출력하고, 설명이나 코드 블록 마커(```)는 절대 넣지 마세요.\n"
        "{\n"
        '  "document_type": "report",\n'
        '  "layout_threshold": 0.5,\n'
        '  "layout_merge_bboxes_mode": "large",\n'
        '  "use_doc_orientation_classify": false,\n'
        '  "use_doc_unwarping": false,\n'
        '  "use_layout_detection": true,\n'
        '  "use_ocr_for_image_block": true,\n'
        '  "format_block_content": true,\n'
        '  "layout_nms": true,\n'
        '  "layout_unclip_ratio": 1.0,\n'
        '  "use_chart_recognition": false,\n'
        '  "use_seal_recognition": false\n'
        "}\n"
    )


def build_row_highlight_prompt(
    rows: list[list[str]],
    instruction: str,
    want_llm_comment: bool,
) -> str:
    """표의 각 행 텍스트만 보고 하이라이트/여백 주석을 붙일 행을 고르는 프롬프트.

    좌표(bbox) 추론은 절대 이 프롬프트에 맡기지 않는다 — 좌표는 OCR bbox에서 이미 확정되어 있고,
    LLM은 순수 텍스트 조건 판단만 수행한다 (Gemma-4의 bbox grounding 신뢰도가 낮다는 리서치 결과 반영).

    Args:
        rows: 행 인덱스 순서의 셀 텍스트 목록 (예: [["1", "2026-01-01", "820,000", "이체"], ...])
        instruction: 사용자가 입력한 조건 (예: "80만원 이상 이체된 줄")
        want_llm_comment: True면 각 매칭 행에 대해 짧은 근거 코멘트를 LLM이 직접 생성

    Returns:
        LLM에게 보낼 프롬프트 문자열
    """
    rows_text = "\n".join(f"{i}: {' | '.join(cell for cell in row)}" for i, row in enumerate(rows))
    comment_instr = (
        "매칭된 각 행마다 왜 선택했는지 10자 내외로 짧게 요약한 comment를 작성하세요 (예: \"82만원 이체\")."
        if want_llm_comment
        else '모든 매칭 행의 comment 값은 아래 "조건 문구"를 그대로 반복해서 넣으세요 (요약/가공하지 마세요).'
    )
    return (
        "당신은 문서 내 표를 검토하는 보조원입니다. 아래는 한 표를 행 단위로 나눈 텍스트입니다. "
        "각 행은 `행번호: 셀1 | 셀2 | ...` 형식입니다. "
        "여러 표/여러 페이지의 행이 순서대로 이어져 있을 수 있고, 각 표의 첫 행은 대개 컬럼명을 나타내는 "
        "헤더 행입니다 (예: '연번 | 구분 | 출금금액(원) | 입금금액(원) | ...'). "
        "셀 순서(컬럼 위치)가 표마다 다를 수 있으니, 조건을 판단하기 전에 가장 가까운 이전 헤더 행을 찾아 "
        "그 헤더의 컬럼명과 정확히 일치하는 컬럼의 값만 비교하세요. "
        "예를 들어 조건이 '출금금액이 X 이상'이면 헤더에서 '출금금액'이라는 이름의 컬럼만 확인하고, "
        "'입금금액' 등 이름이 다른 컬럼 값은 절대 사용하지 마세요.\n\n"
        f"--- 표 데이터 ---\n{rows_text}\n\n"
        f"--- 조건 문구 ---\n{instruction}\n\n"
        "위 조건에 해당하는 행 번호를 모두 찾으세요 (헤더 행 자체는 매칭 대상에서 제외하세요). "
        "숫자 비교가 필요하면 콤마와 원문자를 제거하고 숫자로 변환해서 판단하세요. "
        f"{comment_instr}\n"
        "조건에 맞는 행이 하나도 없으면 matches를 빈 배열로 반환하세요.\n"
        "반드시 아래 JSON 형식으로만 출력하고, 설명이나 코드 블록 마커(```)는 절대 넣지 마세요.\n"
        "{\n"
        '  "matches": [\n'
        '    {"row_index": 0, "comment": "..."}\n'
        "  ]\n"
        "}\n"
    )


def build_docling_refinement_prompt(columns: list[str], docling_markdown: str, extra: str = "") -> str:
    """Docling이 추출한 마크다운을 LLM으로 정리/재구조화하는 프롬프트."""
    cols = ", ".join(columns) if columns else "내용"
    base = (
        "아래는 Docling으로 추출한 문서의 마크다운 원문입니다. "
        "원문서의 시각적 레이아웃(제목, 단락, 항목, 공백, 표 위치, 글꼴 크기, 굵기, 들여쓰기, 열 구분, 정렬)을 최대한 그대로 보존하세요. "
        "표가 있으면 마크다운 표 형식으로 정리하고, 빈 셀은 공백으로 두세요. "
        "숫자, 날짜, 금액, 콤마는 원본 그대로 쓰세요. "
        "내용을 요약하지 말고, 추론이나 해석은 추가하지 마세요. "
        "설명, 머리말, 마무리 문구는 절대 넣지 마세요. "
        f"아래 컬럼({cols})은 참고용이며, 필요한 경우에만 해당 구조를 활용하세요.\n\n"
        "Docling 원문:\n"
        f"{docling_markdown}"
    )
    return f"{base}\n\n추가 지시: {extra}" if extra.strip() else base


def build_audio_prompt(
    extra: str = "",
    segment_start: float | None = None,
    segment_end: float | None = None,
) -> str:
    """오디오(세그먼트)를 시간/발화자/대사 형식의 마크다운 대본으로 전사하는 프롬프트."""
    if segment_start is not None and segment_end is not None:
        segment_info = (
            f"이 오디오는 원본 파일의 {_format_timestamp(segment_start)}부터 "
            f"{_format_timestamp(segment_end)}까지 구간입니다.\n"
        )
    else:
        segment_info = ""

    base = (
        f"{segment_info}오디오를 처음부터 끝까지 듣고, 아래 3개 컬럼으로 구성된 마크다운 표로만 대본을 출력하세요.\n"
        "컬럼: 시간, 발화자(또는 화자 구분), 대사\n"
        "규칙:\n"
        "- 시간은 원본 오디오 기준 HH:MM:SS 형식입니다. 말이 시작되는 시점을 적습니다.\n"
        "- 발화자를 알 수 없으면 '화자1', '화자2' 등으로 구분하거나 '알 수 없음'으로 표기하세요.\n"
        "- 대사는 실제 말한 내용을 최대한 정확하게 옮기세요.\n"
        "- 설명, 머리말, 마무리 문구, 코드 블록은 절대 넣지 마세요.\n"
        "- 결과는 컬럼을 '|'로 구분한 마크다운 표로만 출력하세요."
    )
    return f"{base}\n추가 지시: {extra}" if extra.strip() else base


def build_video_prompt(
    extra: str = "",
    frame_timestamps: list[float] | None = None,
    segment_start: float | None = None,
    segment_end: float | None = None,
    has_audio: bool = False,
) -> str:
    """비디오(세그먼트)를 시간/행동/대사 형식의 마크다운 대본으로 전사하는 프롬프트."""
    if segment_start is not None and segment_end is not None:
        segment_info = (
            f"이 영상은 원본 비디오의 {_format_timestamp(segment_start)}부터 "
            f"{_format_timestamp(segment_end)}까지 구간입니다.\n"
        )
    else:
        segment_info = ""

    if frame_timestamps:
        ts_lines = [f"- 프레임 {i+1}: {_format_timestamp(ts)}" for i, ts in enumerate(frame_timestamps)]
        frame_info = (
            "아래 이미지는 해당 구간에서 추출한 대표 프레임입니다.\n"
            + "\n".join(ts_lines)
            + "\n"
        )
    else:
        frame_info = ""

    audio_info = ""
    if has_audio:
        audio_info = "함께 첨부된 오디오는 같은 구간의 소리이므로, 이를 참고하여 발화나 효과음을 정확히 옮기세요.\n"

    if frame_timestamps or has_audio:
        source_info = (
            f"{segment_info}{frame_info}{audio_info}"
            "이 프레임과 오디오를 참고하여 해당 구간의 흐름을 유추하고, "
        )
    else:
        source_info = "비디오를 처음부터 끝까지 시청하고, "

    base = (
        f"{source_info}아래 4개 컬럼으로 구성된 마크다운 표로만 출력하세요.\n"
        "컬럼: 시간, 장면/행동 묘사, 발화자(또는 화자 구분), 대사/소리\n"
        "규칙:\n"
        "- 시간은 원본 비디오 기준 HH:MM:SS 형식입니다. 이벤트가 시작되는 시점을 적습니다.\n"
        "- 장면/행동 묘사: 화면에서 보이는 사람/동물/물체의 동작, 표정, 움직임, 장면 전환 등을 간결히 묘사하세요.\n"
        "- 발화자를 알 수 없으면 '화자1', '화자2' 등으로 구분하거나 '알 수 없음'으로 표기하세요.\n"
        "- 대사/소리: 실제 말한 내용이나 효과음, 배경음을 최대한 정확하게 옮기세요.\n"
        "- 설명, 머리말, 마무리 문구, 코드 블록은 절대 넣지 마세요.\n"
        "- 결과는 컬럼을 '|'로 구분한 마크다운 표로만 출력하세요."
    )
    return f"{base}\n추가 지시: {extra}" if extra.strip() else base


def _format_timestamp(seconds: float) -> str:
    """초를 HH:MM:SS 또는 MM:SS 형식으로 변환한다."""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
