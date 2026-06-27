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
    """초를 HH:MM:SS 형식으로 변환한다."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
