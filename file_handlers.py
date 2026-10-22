"""Turn an uploaded file into Claude message content blocks.

Each handler returns a list of content blocks to attach to the next user turn:
- tables (CSV, Excel, JSON) are uploaded into the code execution sandbox,
- text and PDF go in as documents,
- images go in as image blocks (Claude vision),
- audio is transcribed locally first, then goes in as a text document.
"""

from pathlib import Path

TABLE_EXTS = {".csv", ".tsv", ".xlsx", ".xls", ".json", ".parquet"}
TEXT_EXTS = {".txt", ".md", ".log", ".html", ".xml", ".py", ".yaml", ".yml"}
PDF_EXTS = {".pdf"}
IMAGE_EXTS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".gif": "image/gif", ".webp": "image/webp"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".webm"}

SUPPORTED = sorted(TABLE_EXTS | TEXT_EXTS | PDF_EXTS | set(IMAGE_EXTS) | AUDIO_EXTS)


def kind_of(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in TABLE_EXTS:
        return "table"
    if ext in TEXT_EXTS:
        return "text"
    if ext in PDF_EXTS:
        return "pdf"
    if ext in IMAGE_EXTS:
        return "image"
    if ext in AUDIO_EXTS:
        return "audio"
    return "unknown"


def _upload(client, name: str, data: bytes, mime: str) -> str:
    return client.files.upload(file=(name, data, mime)).id


def transcribe(name: str, data: bytes) -> str:
    """Speech-to-text with faster-whisper, run locally (Claude has no audio input)."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError(
            "Audio needs the optional 'faster-whisper' package: pip install faster-whisper"
        ) from e
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=Path(name).suffix) as tmp:
        tmp.write(data)
        tmp.flush()
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(tmp.name)
        return "\n".join(
            f"[{s.start:6.1f}s] {s.text.strip()}" for s in segments
        )


def to_blocks(client, name: str, data: bytes) -> tuple[str, list[dict]]:
    """Return (kind, content blocks) for one uploaded file."""
    kind = kind_of(name)
    if kind == "table":
        file_id = _upload(client, name, data, "application/octet-stream")
        note = (f"The table file '{name}' is uploaded to your code execution "
                "sandbox. Load it with pandas to answer questions about it.")
        return kind, [{"type": "text", "text": note},
                      {"type": "container_upload", "file_id": file_id}]
    if kind == "text":
        text = data.decode("utf-8", errors="replace")
        return kind, [{"type": "document", "title": name, "citations": {"enabled": True},
                       "source": {"type": "text", "media_type": "text/plain", "data": text}}]
    if kind == "pdf":
        file_id = _upload(client, name, data, "application/pdf")
        return kind, [{"type": "document", "title": name, "citations": {"enabled": True},
                       "source": {"type": "file", "file_id": file_id}}]
    if kind == "image":
        file_id = _upload(client, name, data, IMAGE_EXTS[Path(name).suffix.lower()])
        return kind, [{"type": "text", "text": f"Image file: {name}"},
                      {"type": "image", "source": {"type": "file", "file_id": file_id}}]
    if kind == "audio":
        transcript = transcribe(name, data)
        return kind, [{"type": "document", "title": f"Transcript of {name}",
                       "citations": {"enabled": True},
                       "source": {"type": "text", "media_type": "text/plain",
                                  "data": transcript or "(no speech detected)"}}]
    raise ValueError(f"Unsupported file type: {name}")
