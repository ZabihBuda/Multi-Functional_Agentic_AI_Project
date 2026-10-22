"""The agent loop: one user question -> Claude (with code execution) -> answer."""

import anthropic

MODEL = "claude-opus-5-5"
MAX_CONTINUATIONS = 5

SYSTEM = """You help the user understand and analyze their files: tables (CSV, \
Excel, JSON), text documents, PDFs, images, and transcripts of audio.

- For tables, always compute answers with Python (pandas) in the code execution \
sandbox instead of estimating. Look at the columns and a few rows first.
- When a chart helps, make it with matplotlib and save it as a PNG file so the \
user can see it.
- For documents and transcripts, quote or cite the passage your answer rests on.
- Keep answers short and lead with the answer. Say plainly when the files do not \
contain what the user asked about."""

TOOLS = [{"type": "code_execution_20260521", "name": "code_execution"}]


def run_turn(client: anthropic.Anthropic, messages: list, container_id: str | None,
             on_text=lambda t: None, on_status=lambda s: None):
    """Run one assistant turn, resuming server-side pauses.

    Appends the assistant message(s) to `messages` and returns
    (container_id, generated_file_ids, stop_reason).
    """
    generated = []
    stop_reason = None
    for _ in range(MAX_CONTINUATIONS):
        kwargs = dict(
            model=MODEL,
            max_tokens=64000,
            system=SYSTEM,
            messages=messages,
            tools=TOOLS,
            thinking={"type": "adaptive"},
            output_config={"effort": "medium"},
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
        generated += _generated_files(message)
        stop_reason = message.stop_reason
        if stop_reason != "pause_turn":
            break
    return container_id, generated, stop_reason


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
