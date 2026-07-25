#!/usr/bin/env python3
# [Flow: Step 1 (user columns/instruction input) -> Step 2 (vision/hybrid prompt dynamic generation)]
# Generalized from the old 9-column fixed prompt to user-defined column-based prompts.

DEFAULT_COLUMNS = [
    "No.", "Category", "Account Number", "Date",
    "Withdrawal (KRW)", "Deposit (KRW)", "Transaction Details", "Transfer Memo", "Account",
]


def build_vision_prompt(columns: list[str], extra: str = "") -> str:
    """Prompt to extract a page as layout-preserving markdown from an image."""
    cols = ", ".join(columns)
    base = (
        "Convert this page to markdown. "
        "Never force the entire content into a table format. Preserve the visual layout of the original document "
        "(headings, paragraphs, items, whitespace, table positions, font size, weight, indentation, column separation, alignment) as faithfully as possible. "
        "Extract every piece of text, numbers, dates, signatures, seals, footnotes, headers, footers, page numbers, logos, and background text without omission. "
        "If only part of the page is a table, render only that part as a table and keep the rest as natural markdown following the original layout. "
        "Do not summarize or omit any content. Do not add inferences or interpretations. "
        "Do not include any explanations, headers, or closing remarks. "
        "Leave empty cells blank. Keep numbers and commas exactly as in the original. "
        f"The following columns ({cols}) are for reference only; use that structure only when applicable."
    )
    return f"{base}\nAdditional instructions: {extra}" if extra.strip() else base


def build_text_prompt(columns: list[str], ocr_text: str, extra: str = "") -> str:
    """Prompt to structure OCR raw text into CSV."""
    header = ",".join(columns)
    instr = (
        "Below is the OCR raw text of a PDF page. "
        f"Convert it into CSV with {len(columns)} columns.\n"
        "Rules:\n"
        f"- CSV header: {header}\n"
        "- Do not output any explanations, markdown, or code blocks. Output CSV data only.\n"
        "- Each row is a single CSV record on one line.\n"
        "- Keep commas in monetary amounts.\n"
        "- Leave empty cells blank.\n"
        "- Correct OCR errors where possible.\n"
        "- If there is no data, output the header only.\n"
    )
    if extra.strip():
        instr += f"- Additional instructions: {extra}\n"
    return f"{instr}\nOCR raw text:\n{ocr_text}"


def build_media_prompt(columns: list[str], extra: str = "") -> str:
    """Prompt to extract content from an image."""
    cols = ", ".join(columns) if columns else "content"
    base = (
        "Analyze the provided image and output markdown that preserves the visual layout of the original document as faithfully as possible. "
        "If only part of the image is a table, render only that part as a table and never force the entire content into a table format. "
        "Extract every piece of text, numbers, dates, signatures, seals, footnotes, headers, footers, page numbers, and logos without omission. "
        "Do not summarize or omit any content. Do not add inferences or interpretations. "
        "Do not include any explanations, headers, or closing remarks. "
        f"The following columns ({cols}) are for reference only; use that structure only when applicable."
    )
    return f"{base}\nAdditional instructions: {extra}" if extra.strip() else base


def build_paddleocr_parameter_recommendation_prompt() -> str:
    """Prompt to send to the Vision LLM to auto-recommend PaddleOCR-VL parameters."""
    return (
        "You are a document OCR layout expert. Examine the attached page image and recommend, in JSON, "
        "the parameters that would yield the most accurate parsing with PaddleOCR-VL.\n\n"
        "First, classify the document into one of the following types:\n"
        "- receipt: short paper, possible skew/distortion, small text, items and amounts centered\n"
        "- invoice: tabular format, business numbers/amounts/items centered\n"
        "- form: many boxes/fields filled in by the user\n"
        "- paper: academic paper, paragraphs, headings, sections, possible formulas/figures\n"
        "- table_heavy: report dominated by tables or a mix of tables and text\n"
        "- image_heavy: more images/diagrams/blueprints than text\n"
        "- business_card: small card, logo, short text\n"
        "- report: general report with natural paragraphs and sections, occasional tables/images\n"
        "- mixed: does not clearly fall into any of the above\n\n"
        "Decide each of the following as true/false or a number/string:\n"
        "- layout_threshold: minimum confidence for the layout model to detect a region (0.1~0.9). "
        "  0.35 for receipts/business cards/small documents, 0.4~0.45 for forms/table-heavy, 0.5 for general reports/papers.\n"
        "- layout_merge_bboxes_mode: how to merge nested layout boxes. "
        "  One of 'large' (keep largest), 'small' (keep smallest), 'union' (keep all).\n"
        "- use_doc_orientation_classify: true if the document is rotated 90/180/270 degrees.\n"
        "- use_doc_unwarping: true if the document is crumpled or curved (scan/photo).\n"
        "- use_layout_detection: true to use layout analysis (almost always true).\n"
        "- use_ocr_for_image_block: true to extract hidden text inside images/diagrams.\n"
        "- format_block_content: true to format results as clean markdown.\n"
        "- layout_nms: true if post-processing is needed due to many overlapping boxes.\n"
        "- layout_unclip_ratio: layout box expansion ratio (0.5~2.0), typically 1.0.\n"
        "- use_chart_recognition: true if charts/graphs are prominent and numerical extraction matters.\n"
        "- use_seal_recognition: true if seal/stamp recognition is needed.\n\n"
        "Output strictly in the following JSON format. Do not include explanations or code block markers (```).\n"
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


def build_text_search_highlight_prompt(
    page_texts: list[tuple[int, str]],
    instruction: str,
    want_llm_comment: bool,
) -> str:
    """[Flow: Step 1 (페이지별 텍스트 인덱스 생성) -> Step 2 (조건 + 예시 JSON 포함 프롬프트 조립)]

    검색 가능한 PDF의 텍스트 레이어에서 직접 검색할 때 사용하는 프롬프트.
    LLM은 위치(페이지/좌표)에 관여하지 않고, 강조해야 할 정확한 텍스트 내용만 반환한다.
    백엔드가 반환된 text를 PDF 텍스트 레이어에서 검색해 모든 발생 위치를 형광펜으로 칠한다.

    Args:
        page_texts: (1-based page_no, 페이지 텍스트) 튜플 목록
        instruction: 사용자가 입력한 조건 문구
        want_llm_comment: True면 LLM이 요약 코멘트를 생성, False면 사용자 문구를 그대로 사용

    Returns:
        LLM에 전송할 프롬프트 문자열
    """
    page_blocks = []
    for page_no, text in page_texts:
        page_blocks.append(f"--- Page {page_no} ---\n{text}")
    pages_section = "\n\n".join(page_blocks)

    comment_instr = (
        "For each matched text, write a short comment (about 10 characters) summarizing why it was selected. "
        "Write the comment in the SAME language as the user's condition text above."
        if want_llm_comment
        else 'Repeat the "Condition" text verbatim as the comment for every matched text (do not summarize or rephrase). '
        "Keep the original language of the condition text."
    )

    return (
        "You are an assistant reviewing a searchable PDF. Below are text excerpts from each page. "
        "The PDF already has a text layer, so you do NOT need to provide coordinates or page numbers. "
        "Only return the exact text content that should be highlighted according to the condition. "
        "If the same text appears multiple times, it will be highlighted on every occurrence.\n\n"
        f"--- Page texts ---\n{pages_section}\n\n"
        f"--- Condition ---\n{instruction}\n\n"
        "Find all exact text spans in the document that match the condition. "
        "Return the text exactly as it appears in the document (preserve punctuation, spaces, numbers, and line breaks). "
        "For table rows, you may either return the full row text with cells separated by pipes (|), "
        "or return the exact text of the specific cell/cells that match the condition. "
        "Do not paraphrase or summarize the text; use the exact wording from the page excerpts above. "
        "When the user asks for a specific highlight color (e.g., red, yellow, green, blue), use the corresponding color name. "
        "Available colors: red, yellow, green, blue, orange, purple, pink, gray. If no color is implied, default to yellow.\n"
        "Determine the annotation display mode based on the user's request: "
        "'highlight' if the user asks for highlights only, "
        "'margin_note' if the user asks for margin notes only, "
        "'both' if the user asks for both or does not specify.\n"
        "Determine the comment mode based on the user's request: "
        "'user_text' if the user explicitly says to use the input text verbatim as the comment, "
        "'llm_summary' if the user wants AI-generated summaries or does not specify.\n"
        "When the user asks for a specific opacity/transparency (e.g., 'transparently', 'lightly', '50%', 'semi-transparent'), "
        "include an 'opacity' field with a value between 0.0 (fully transparent) and 1.0 (fully opaque). "
        "If no opacity is requested, omit the 'opacity' field.\n"
        "\n"
        f"{comment_instr}\n"
        "If no text matches, return an empty matches array.\n"
        "Output strictly in the following JSON format. Do not include explanations or code block markers (```).\n"
        "{\n"
        '  "mode": "both",\n'
        '  "comment_mode": "llm_summary",\n'
        '  "matches": [\n'
        '    {"text": "exact text from the document", "comment": "...", "color": "yellow", "opacity": 0.5}\n'
        "  ]\n"
        "}\n"
    )


def build_docling_refinement_prompt(columns: list[str], docling_markdown: str, extra: str = "") -> str:
    """Prompt to clean up and restructure markdown extracted by Docling using an LLM."""
    cols = ", ".join(columns) if columns else "content"
    base = (
        "Below is the raw markdown of a document extracted by Docling. "
        "Preserve the visual layout of the original document (headings, paragraphs, items, whitespace, table positions, "
        "font size, weight, indentation, column separation, alignment) as faithfully as possible. "
        "If there are tables, format them as markdown tables and leave empty cells blank. "
        "Keep numbers, dates, monetary amounts, and commas exactly as in the original. "
        "Do not summarize the content. Do not add inferences or interpretations. "
        "Do not include any explanations, headers, or closing remarks. "
        f"The following columns ({cols}) are for reference only; use that structure only when applicable.\n\n"
        "Docling raw text:\n"
        f"{docling_markdown}"
    )
    return f"{base}\n\nAdditional instructions: {extra}" if extra.strip() else base


def build_audio_prompt(
    extra: str = "",
    segment_start: float | None = None,
    segment_end: float | None = None,
) -> str:
    """Prompt to transcribe audio (segment) as a markdown transcript with time/speaker/dialogue columns."""
    if segment_start is not None and segment_end is not None:
        segment_info = (
            f"This audio is a segment from {_format_timestamp(segment_start)} to "
            f"{_format_timestamp(segment_end)} of the original file.\n"
        )
    else:
        segment_info = ""

    base = (
        f"{segment_info}Listen to the audio from beginning to end and output the transcript as a markdown table with the following 3 columns.\n"
        "Columns: Time, Speaker (or speaker label), Dialogue\n"
        "Rules:\n"
        "- Time is in HH:MM:SS format based on the original audio. Use the timestamp when speech begins.\n"
        "- If the speaker is unknown, label them as 'Speaker 1', 'Speaker 2', etc., or 'Unknown'.\n"
        "- For dialogue, transcribe the actual spoken content as accurately as possible.\n"
        "- Do not include any explanations, headers, closing remarks, or code blocks.\n"
        "- Output only a markdown table with columns separated by '|'."
    )
    return f"{base}\nAdditional instructions: {extra}" if extra.strip() else base


def build_video_prompt(
    extra: str = "",
    frame_timestamps: list[float] | None = None,
    segment_start: float | None = None,
    segment_end: float | None = None,
    has_audio: bool = False,
) -> str:
    """Prompt to transcribe video (segment) as a markdown transcript with time/action/dialogue columns."""
    if segment_start is not None and segment_end is not None:
        segment_info = (
            f"This video is a segment from {_format_timestamp(segment_start)} to "
            f"{_format_timestamp(segment_end)} of the original video.\n"
        )
    else:
        segment_info = ""

    if frame_timestamps:
        ts_lines = [f"- Frame {i+1}: {_format_timestamp(ts)}" for i, ts in enumerate(frame_timestamps)]
        frame_info = (
            "The images below are representative frames extracted from this segment.\n"
            + "\n".join(ts_lines)
            + "\n"
        )
    else:
        frame_info = ""

    audio_info = ""
    if has_audio:
        audio_info = "The accompanying audio is the sound from the same segment; use it to accurately transcribe speech and sound effects.\n"

    if frame_timestamps or has_audio:
        source_info = (
            f"{segment_info}{frame_info}{audio_info}"
            "Using these frames and audio, infer the flow of the segment and "
        )
    else:
        source_info = "Watch the video from beginning to end and "

    base = (
        f"{source_info}output only a markdown table with the following 4 columns.\n"
        "Columns: Time, Scene/Action description, Speaker (or speaker label), Dialogue/Sound\n"
        "Rules:\n"
        "- Time is in HH:MM:SS format based on the original video. Use the timestamp when the event begins.\n"
        "- Scene/Action description: concisely describe the actions, expressions, movements, and scene transitions of people/animals/objects visible on screen.\n"
        "- If the speaker is unknown, label them as 'Speaker 1', 'Speaker 2', etc., or 'Unknown'.\n"
        "- Dialogue/Sound: transcribe the actual spoken content, sound effects, and background audio as accurately as possible.\n"
        "- Do not include any explanations, headers, closing remarks, or code blocks.\n"
        "- Output only a markdown table with columns separated by '|'."
    )
    return f"{base}\nAdditional instructions: {extra}" if extra.strip() else base


def build_vision_text_highlight_prompt(
    instruction: str,
    want_llm_comment: bool,
) -> str:
    """Vision LLM이 문서 이미지를 보고 강조할 텍스트 내용만 반환하도록 하는 프롬프트.

    LLM은 위치(페이지/좌표/bbox)에 관여하지 않고, 조건에 맞는 텍스트 내용만 반환한다.
    백엔드가 searchable PDF의 텍스트 레이어에서 해당 text를 검색해 모든 발생 위치를 highlight한다.

    Args:
        instruction: 사용자가 입력한 조건 문구
        want_llm_comment: True면 LLM이 요약 코멘트를 생성, False면 사용자 문구를 그대로 사용

    Returns:
        Vision LLM에 전송할 프롬프트 문자열
    """
    comment_instr = (
        "For each matched text, write a short comment (about 10-20 characters) summarizing its content. "
        "Write the comment in the SAME language as the user's condition text above."
        if want_llm_comment
        else 'Repeat the "Condition" text verbatim as the comment for every matched text (do not summarize or rephrase). '
        "Keep the original language of the condition text."
    )
    return (
        "You are a document annotation assistant. Examine the provided document image carefully. "
        "The document has already been processed into a searchable text layer, so you do NOT need to provide "
        "coordinates, page numbers, or bounding boxes. "
        "Only return the exact text content that should be highlighted according to the condition. "
        "If the same text appears multiple times, it will be highlighted on every occurrence.\n\n"
        f"--- Condition ---\n{instruction}\n\n"
        "Find ALL text in the image that matches the condition above. "
        "For table rows, you may return the full row text with cells separated by pipes (|), "
        "or return the exact text of the specific cell/cells that match the condition. "
        "Do not paraphrase or summarize the text; use the exact wording visible in the image. "
        "If numeric comparison is needed, remove commas and currency symbols and convert to numbers. "
        "When the user asks for a specific highlight color, use one of the following colors: "
        "red, yellow, green, blue, orange, purple, pink, gray. If no color is implied, default to yellow.\n"
        "Determine the annotation display mode based on the user's request: "
        "'margin_note' (sticky note — memo icon placed on the target text with a comment popup) if the user asks for annotations/notes ('주석', '메모', '콜아웃', '설명', '스티키노트', '메모지'), "
        "'highlight' (pure highlight fill without overlay text) if the user asks for fluorescent pen/highlight ('형광펜', '하이라이트', '강조', '색칠'), "
        "'both' if the user asks for both or does not specify.\n"

        "Determine the comment mode based on the user's request: "
        "'user_text' if the user explicitly says to use the input text verbatim as the comment, "
        "'llm_summary' if the user wants AI-generated summaries or does not specify.\n"
        "When the user asks for a specific opacity/transparency (e.g., 'transparently', 'lightly', '50%', 'semi-transparent'), "
        "include an 'opacity' field with a value between 0.0 (fully transparent) and 1.0 (fully opaque). "
        "If no opacity is requested, omit the 'opacity' field.\n"
        f"{comment_instr}\n"
        "If no text matches, return an empty matches array.\n"
        "Output strictly in the following JSON format. Do not include explanations or code block markers (```).\n"
        "{\n"
        '  "mode": "both",\n'
        '  "comment_mode": "llm_summary",\n'
        '  "matches": [\n'
        '    {"text": "exact text from the document", "comment": "...", "color": "yellow", "opacity": 0.5}\n'
        "  ]\n"
        "}\n"
    )


def build_annotation_edit_prompt(
    annotations: list[dict],
    instruction: str,
    user_language: str = "ko",
) -> str:
    """[Flow: Step 1 (기존 주석 목록 직렬화) -> Step 2 (편집 instruction 주입) -> Step 3 (LLM이 id별 새 색상/코멘트 반환)]

    기존 AI 주석의 색상/코멘트를 사용자 instruction에 맞게 재편집하기 위한 프롬프트.
    각 주석의 id, type, 현재 색상, 현재 코멘트, 원본 텍스트(있으면)를 LLM에 전달하면
    LLM이 변경이 필요한 주석만 id 기준으로 새 color/comment를 반환한다.
    bbox/위치는 유지하고 색상/코멘트만 갱신하므로, LLM은 위치 정보를 다루지 않는다.

    Args:
        annotations: 편집 대상 주석 목록. 각 항목은 {id, type, color, comment, text} 형태.
        instruction: 사용자가 입력한 편집 조건 (예: "색상을 빨간색으로", "코멘트를 간결하게")
        user_language: 사용자 설정 언어. 코멘트 작성 우선순위에 사용 (기본값 "ko").

    Returns:
        LLM에 전달할 프롬프트 문자열. LLM은 JSON {edits: [{id, color, comment}]} 반환.
    """
    lines: list[str] = []
    for a in annotations:
        ann_id = a.get("id", "")
        atype = "sticky" if str(a.get("type", "")).lower() in ("freetext", "freetextcallout", "text", "sticky") else "highlight"
        color = a.get("color", "")
        comment = a.get("comment", "")
        text = a.get("text", "")
        text_part = f' | text="{text}"' if text else ""
        lines.append(f'id={ann_id} | type={atype} | color={color} | comment="{comment}"{text_part}')
    annotations_text = "\n".join(lines)

    return (
        "You are an assistant editing existing PDF annotations. Below is a list of existing annotations.\n"
        "Each line is: id=... | type=highlight|sticky | color=#RRGGBB | comment=\"...\" | text=\"...\"\n"
        "- 'highlight' annotations mark a region of the document; 'text' is the highlighted content (if available).\n"
        "- 'sticky' annotations are sticky note (memo icon) placed on a region; 'comment' is the popup note text.\n\n"
        f"--- Existing annotations ---\n{annotations_text}\n\n"
        f"--- Edit instruction ---\n{instruction}\n\n"
        "Apply the edit instruction to the annotations above. You may change the color and/or the comment text.\n"
        "Available color names: red, yellow, green, blue, orange, purple, pink, gray. "
        "If the instruction does not imply a color change, keep the original color. "
        "If the instruction does not imply a comment change, keep the original comment. "
        "Write/rewrite comments in the user's configured language (" + user_language + ") if known; otherwise, use the same language as the edit instruction. "
        "Keep comments short (about 10-30 characters). "
        "Only include annotations that actually need a change. If none need changing, return an empty edits array.\n\n"
        "Output strictly in the following JSON format. Do not include explanations or code block markers (```).\n"
        "{\n"
        '  "edits": [\n'
        '    {"id": "<annotation id>", "color": "<color name>", "comment": "..."}\n'
        "  ]\n"
        "}\n"
    )


def _format_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS or MM:SS format."""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
