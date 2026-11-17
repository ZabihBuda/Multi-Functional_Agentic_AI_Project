"""Settings for running the app locally or as a public website.

Every setting is read from an environment variable. On Streamlit Community
Cloud, top-level keys in the app's Secrets box become environment variables,
so the same names work there. Locally they can go in `.env`.

With PUBLIC_MODE off (the default), the app behaves like a private local tool:
no question caps, audio allowed. Turn PUBLIC_MODE on for a public deployment.
"""

import os

from dotenv import load_dotenv

load_dotenv()  # local .env, if present; hosted platforms set real env vars


def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


PUBLIC_MODE = _flag("PUBLIC_MODE", False)

# Your own key. Leave it unset to require every visitor to bring their own.
OWNER_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()

# Let visitors paste their own Anthropic API key (used only for their session,
# never stored). Their questions don't count against the caps below.
ALLOW_VISITOR_KEYS = _flag("ALLOW_VISITOR_KEYS", True)

# Caps that protect the owner's key in public mode.
FREE_QUESTIONS_PER_SESSION = _int("FREE_QUESTIONS_PER_SESSION", 10 if PUBLIC_MODE else 0)
DAILY_QUESTION_CAP = _int("DAILY_QUESTION_CAP", 300 if PUBLIC_MODE else 0)  # 0 = no cap

# Upload limits. The hard per-file size limit is server.maxUploadSize in
# .streamlit/config.toml (10 MB); raise both to allow bigger files locally.
MAX_FILE_MB = _int("MAX_FILE_MB", 10)
MAX_FILES = _int("MAX_FILES", 5 if PUBLIC_MODE else 50)
MAX_QUESTION_CHARS = _int("MAX_QUESTION_CHARS", 2000 if PUBLIC_MODE else 100_000)

# Audio is transcribed on the web server's CPU, which is slow and memory-hungry
# on free hosting. Off by default in public mode.
ALLOW_AUDIO = _flag("ALLOW_AUDIO", not PUBLIC_MODE)

# Delete files the app uploaded to Anthropic's Files API once they're older
# than this many hours, sweeping the owner key's whole workspace. Only turn
# this on when the key belongs to a workspace used by this app alone.
FILE_RETENTION_HOURS = _int("FILE_RETENTION_HOURS", 0)  # 0 = sweep off

# Model and effort, overridable without code changes.
MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("CLAUDE_EFFORT", "high")
