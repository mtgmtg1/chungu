#!/usr/bin/env python3
# [Flow: Step 1 (사용자 컬럼/지시 입력) -> Step 2 (vision/hybrid 프롬프트 동적 생성)]
# 기존 9컬럼 고정 프롬프트를 사용자 정의 컬럼 기반으로 일반화.

DEFAULT_COLUMNS = [
    "연번", "구분", "계좌번호", "거래일자",
    "출금금액(원)", "입금금액(원)", "거래기록사항", "이체메모", "계정",
]


def build_vision_prompt(columns: list[str], extra: str = "") -> str:
    """이미지를 직접 보고 마크다운 표로 추출하라는 프롬프트."""
    cols = ", ".join(columns)
    base = (
        f"이 페이지의 표를 아래 {len(columns)}개 컬럼을 그대로 유지하는 마크다운 표로만 출력하세요. "
        f"컬럼: {cols}. "
        "설명, 머리말, 마무리 문구는 절대 넣지 마세요. "
        "빈 셀은 공백으로 두고, 숫자와 콤마는 원본 그대로 쓰세요. "
        "헤더가 없는 페이지는 데이터만 표로 만드세요. "
        "표가 여러 개면 주요 데이터 표 하나만 출력하세요."
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
    """이미지/오디오/비디오에서 표 또는 전사를 추출하는 통일 프롬프트."""
    cols = ", ".join(columns) if columns else "내용"
    base = (
        "제공된 파일을 분석하고, 아래 4개 컬럼으로 구성된 마크다운 표로만 출력하세요. "
        "컬럼: 파일명, 유형, 위치/시간/페이지, 추출내용. "
        "설명, 머리말, 마무리 문구는 절대 넣지 마세요. "
        "오디오는 초 단위로, 비디오는 프레임 시간을 기준으로, 이미지는 위치를 1로 표기하세요. "
        f"PDF 컬럼이 지정된 경우({cols}) 관련 내용을 추출내용 열에 함께 담으세요."
    )
    return f"{base}\n추가 지시: {extra}" if extra.strip() else base
