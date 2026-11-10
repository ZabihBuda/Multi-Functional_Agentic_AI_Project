"""The agent loop: one user question -> Claude (with code execution) -> answer."""

import anthropic

MODEL = "claude-opus-5-5"
MAX_CONTINUATIONS = 5
# Higher effort = more careful reasoning and checking, at more tokens per answer.
EFFORT = "high"

SYSTEM = """You answer questions about files the user has uploaded: tables (CSV, \
Excel, JSON, Parquet), text documents, PDFs, images, and transcripts of audio. \
The user relies on your answers being true to those files, so accuracy matters \
more than completeness or polish.

Ground every answer in the files
- Answer only from what the uploaded files contain. Don't fill gaps with general \
knowledge, typical values, or guesses about what the data probably shows. If \
background knowledge genuinely helps, label it clearly as not coming from the files.
- If the files don't contain the answer, say so plainly and point to the closest \
thing they do contain. A clear "the files don't say" is a good answer; a plausible \
guess is a bad one.
- If the files only partly answer the question, separate what they support from \
what they don't.
- If files disagree with each other, point out the conflict and show both values \
with their sources instead of silently picking one.

Numbers and tables
- Compute every number (totals, averages, counts, percentages, differences, \
rankings, date spans) with Python in the code execution sandbox, including numbers \
taken from documents when you combine or compare them. Don't do arithmetic in \
your head or estimate.
- Before analyzing a table, load it and check its shape, column names and types, \
and missing or duplicate values; for Excel files, list the sheets. Mention \
anything that changes the answer, such as rows dropped or values that failed to parse.
- Report numbers as computed, rounded sensibly, with units. State the columns, \
filters and definitions you used (for example "revenue = the 'Net Sales' column, \
2025 rows only") so the user can check them.
- If a question can be read more than one way (which column, which period), say \
which reading you used. If the readings give very different answers, show both \
or ask.

Citing sources
- Say which file every fact comes from. For documents, PDFs and transcripts, cite \
the exact passage your answer rests on. For tables, name the file, sheet and \
columns used. For images, name the image.
- For images and audio transcripts, say when something is hard to read or hear, \
and don't guess at unclear text, digits or words. Transcripts come from automatic \
speech recognition and can contain errors.

Before you answer
- Check each claim and number in your answer against the files or your code \
output, and remove or correct anything you can't trace back to them.
- If you're unsure about part of the answer, say so in one sentence and why.

Style
- Lead with the answer and keep it short, then give the supporting source and method.
- When a chart helps, make it with matplotlib and save it as a PNG file so the \
user can see it."""

TOOLS = [{"type": "code_execution_20260521", "name": "code_execution"}]


def run_turn(client: anthropic.Anthropic, messages: list, container_id: str | None,
             on_text=lambda t: None, on_status=lambda s: None):
    """Run one assistant turn, resuming server-side pauses.

    Appends the assistant message(s) to `messages` and returns
    (container_id, generated_file_ids, stop_reason, content_blocks), where
    content_blocks is everything Claude produced this turn (for `format_answer`).
    """
    generated = []
    blocks = []
    stop_reason = None
    for _ in range(MAX_CONTINUATIONS):
        kwargs = dict(
            model=MODEL,
            max_tokens=64000,
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
            thinking={"type": "adaptive"},
            output_config={"effort": EFFORT},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if container_id:
            kwargs["container"] = container_id
        with client.beta.messages.stream(**kwargs) as stream:
            for event in stream:
                if event.type == "content_block_start":
                    block = event.content_block
                    if block.type == "server_tool_use":
                        on_status("Running code…")
                elif event.type == "content_block_delta" and event.delta.type == "text_delta":
                    on_text(event.delta.text)
            message = stream.get_final_message()

        messages.append({"role": "assistant", "content": message.content})
        if getattr(message, "container", None):
            container_id = message.container.id
        blocks += message.content
        generated += _generated_files(message)
        stop_reason = message.stop_reason
        if stop_reason != "pause_turn":
            break
    return container_id, generated, stop_reason, blocks


def _generated_files(message) -> list[str]:
    ids = []
    for block in message.content:
        if block.type != "bash_code_execution_tool_result":
            continue
        result = block.content
        if getattr(result, "type", None) == "bash_code_execution_result":
            for ref in result.content or []:
                if ref.type == "bash_code_execution_output":
                    ids.append(ref.file_id)
    return ids


def format_answer(blocks) -> tuple[str, list[dict]]:
    """Join the answer text, adding [n] markers where Claude cited a document.

    Returns (markdown, sources); each source is a dict with number, title,
    location (e.g. "p. 4") and quote, for showing under the answer.
    """
    parts, sources, seen = [], [], {}
    gap = False  # a code run (or other non-text block) since the last text
    for block in blocks:
        if block.type != "text":
            gap = gap or bool(parts)
            continue
        if gap and parts and not parts[-1].endswith("\n"):
            parts.append("\n\n")
        gap = False
        parts.append(block.text)
        marks = []
        for c in getattr(block, "citations", None) or []:
            key = (c.document_title, _location(c), c.cited_text)
            if key not in seen:
                seen[key] = len(sources) + 1
                sources.append({"number": seen[key], "title": c.document_title or "document",
                                "location": key[1], "quote": c.cited_text.strip()})
            if seen[key] not in marks:
                marks.append(seen[key])
        if marks:
            parts.append(" " + "".join(f"[{n}]" for n in marks))
    return "".join(parts), sources


def _location(citation) -> str:
    if citation.type == "page_location":  # end_page_number is exclusive
        first, last = citation.start_page_number, citation.end_page_number - 1
        return f"p. {first}" if last <= first else f"pp. {first}-{last}"
    return ""
