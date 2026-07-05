#!/usr/bin/env python3
# [Flow: Step 1 (user columns/instruction input) -> Step 2 (vision/hybrid prompt dynamic generation)]
# Generalized from the old 9-column fixed prompt to user-defined column-based prompts.

# Maps user language codes to full language names for prompt instructions.
# Used to tell the LLM which language to write annotation comments in.
LANGUAGE_NAMES = {
    "ko": "Korean",
    "en": "English",
    "ja": "Japanese",
}


def _language_name(code: str) -> str:
    """Return the full language name for a language code, defaulting to English."""
    return LANGUAGE_NAMES.get(code, "English")


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


def build_row_highlight_prompt(
    rows: list[list[str]],
    instruction: str,
    want_llm_comment: bool,
    language: str = "en",
) -> str:
    """Prompt to select table rows for highlight/margin annotation based on row text only.

    Bbox (coordinate) inference is never delegated to this prompt — coordinates are already
    determined from OCR bboxes, and the LLM performs purely text-based condition judgment
    (reflecting research showing Gemma-4's bbox grounding reliability is low).

    Args:
        rows: list of cell texts in row index order (e.g. [["1", "2026-01-01", "820,000", "transfer"], ...])
        instruction: user-entered condition (e.g. "rows where 800,000 KRW or more was transferred")
        want_llm_comment: if True, the LLM generates a short justification comment for each matched row
        language: user's language code ("ko"/"en"/"ja") — comments will be written in this language

    Returns:
        Prompt string to send to the LLM
    """
    rows_text = "\n".join(f"{i}: {' | '.join(cell for cell in row)}" for i, row in enumerate(rows))
    lang_name = _language_name(language)
    comment_instr = (
        f"For each matched row, write a short comment (about 10 characters) summarizing why it was selected, in {lang_name}."
        if want_llm_comment
        else f'Repeat the "Condition" text verbatim as the comment for every matched row (do not summarize or rephrase), in {lang_name}.'
    )
    return (
        "You are an assistant reviewing tables in a document. Below is the text of a table divided row by row. "
        "Each row is in the format `row_index: cell1 | cell2 | ...`. "
        "Rows from multiple tables/pages may be concatenated, and the first row of each table is usually a header row "
        "containing column names (e.g. 'No. | Category | Withdrawal (KRW) | Deposit (KRW) | ...'). "
        "Column order may differ between tables, so before evaluating the condition, find the nearest preceding header row "
        "and compare only the value in the column whose name exactly matches the condition. "
        "For example, if the condition is 'Withdrawal >= X', check only the column named 'Withdrawal' in the header "
        "and never use values from columns with different names such as 'Deposit'.\n\n"
        f"--- Table data ---\n{rows_text}\n\n"
        f"--- Condition ---\n{instruction}\n\n"
        "Find all row numbers that match the condition above (exclude header rows themselves from matching). "
        "If numeric comparison is needed, remove commas and currency symbols and convert to numbers before comparing. "
        f"{comment_instr}\n"
        "If no rows match, return an empty matches array.\n"
        "Output strictly in the following JSON format. Do not include explanations or code block markers (```).\n"
        "{\n"
        '  "matches": [\n'
        '    {"row_index": 0, "comment": "..."}\n'
        "  ]\n"
        "}\n"
    )


def build_element_highlight_prompt(
    elements: list[dict],
    instruction: str,
    want_llm_comment: bool,
    language: str = "en",
) -> str:
    """Prompt to select elements (table rows + text blocks) for highlight/margin annotation.

    Each element is a dict with the following keys:
      - kind: "table_row" | "text"
      - text: for table rows, joined text in "cell1 | cell2 | ..." form; for text blocks, the block content

    Args:
        elements: list of element dicts in element index order
        instruction: user-entered condition (e.g. "sections containing a person's name", "rows where 800,000 KRW or more was transferred")
        want_llm_comment: if True, the LLM generates a short justification comment for each matched element
        language: user's language code ("ko"/"en"/"ja") — comments will be written in this language

    Returns:
        Prompt string to send to the LLM
    """
    lines: list[str] = []
    for i, el in enumerate(elements):
        kind = el.get("kind", "text")
        text = el.get("text", "")
        tag = "[table row]" if kind == "table_row" else "[text]"
        lines.append(f"{i}: {tag} {text}")
    elements_text = "\n".join(lines)

    lang_name = _language_name(language)
    comment_instr = (
        f"For each matched element, write a short comment (about 10 characters) summarizing why it was selected, in {lang_name}."
        if want_llm_comment
        else f'Repeat the "Condition" text verbatim as the comment for every matched element (do not summarize or rephrase), in {lang_name}.'
    )
    return (
        "You are an assistant reviewing a document. Below are text elements extracted from each page of the document. "
        "Each element is in the format `element_index: [kind] content`, where kind is either [table row] (a single row of a table) "
        "or [text] (a heading/paragraph/footnote/seal text, etc.). "
        "Table rows have cells separated by pipes (|) in the form `cell1 | cell2 | ...`, and the first row may be a header (column names). "
        "Text elements are paragraphs/headings with newlines collapsed to spaces. "
        "Elements from multiple pages may be concatenated in order.\n\n"
        f"--- Element list ---\n{elements_text}\n\n"
        f"--- Condition ---\n{instruction}\n\n"
        "Find all element numbers (element_index) that match the condition above. "
        "For table rows, if numeric comparison is needed, remove commas and currency symbols and convert to numbers before comparing. "
        "For text elements, judge based on whether specific words/names/dates are present. "
        "If the condition is ambiguous, select the elements most contextually relevant. "
        f"{comment_instr}\n"
        "If no elements match, return an empty matches array.\n"
        "Output strictly in the following JSON format. Do not include explanations or code block markers (```).\n"
        "{\n"
        '  "matches": [\n'
        '    {"element_index": 0, "comment": "..."}\n'
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


def _format_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS or MM:SS format."""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
