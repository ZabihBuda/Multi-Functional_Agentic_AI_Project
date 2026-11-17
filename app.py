"""Chat with your files: a Streamlit UI over Claude.

Run:  streamlit run app.py

Works as a private local tool by default. Set PUBLIC_MODE=1 (see settings.py
and DEPLOY.md) to run it as a public website with usage caps and upload limits.
"""

import datetime
import os
import threading

import anthropic
import streamlit as st

import settings
from agent import format_answer, run_turn
from file_handlers import AUDIO_EXTS, SUPPORTED, kind_of, to_blocks

st.set_page_config(page_title="Chat with your files", page_icon="📂", layout="wide")


# ---------------------------------------------------------------- clients

@st.cache_resource
def owner_client():
    """One shared client on the owner's key (None if no key is configured)."""
    return anthropic.Anthropic(api_key=settings.OWNER_KEY) if settings.OWNER_KEY else None


def visitor_client(key: str):
    """A client on the visitor's own key, kept only in their session."""
    ss = st.session_state
    if ss.get("visitor_client_key") != key:
        ss.visitor_client = anthropic.Anthropic(api_key=key)
        ss.visitor_client_key = key
    return ss.visitor_client


# ---------------------------------------------------------------- usage caps

@st.cache_resource
def daily_counter():
    """Questions answered on the owner's key today, shared by all visitors.

    Lives in server memory, so it resets if the app restarts. It is a safety
    net; the real budget guard is the spend limit set in the Claude Console.
    """
    return {"day": None, "count": 0, "lock": threading.Lock()}


def take_daily_slot() -> bool:
    if settings.DAILY_QUESTION_CAP <= 0:
        return True
    c = daily_counter()
    today = datetime.date.today().isoformat()
    with c["lock"]:
        if c["day"] != today:
            c["day"], c["count"] = today, 0
        if c["count"] >= settings.DAILY_QUESTION_CAP:
            return False
        c["count"] += 1
        return True


def give_back_daily_slot():
    if settings.DAILY_QUESTION_CAP <= 0:
        return
    c = daily_counter()
    with c["lock"]:
        c["count"] = max(0, c["count"] - 1)


# ---------------------------------------------------------------- file cleanup

def delete_files(client, file_ids):
    """Best-effort delete of files this session put in the Files API."""
    for fid in file_ids:
        try:
            client.files.delete(fid)
        except anthropic.APIError:
            pass


@st.cache_data(ttl=3600, show_spinner=False)
def sweep_old_files(hours: int) -> int:
    """Delete owner-workspace files older than `hours`. Runs at most hourly.

    Visitors who close the tab never click "Start over", so this catches their
    files. It touches every file in the key's workspace, which is why it's off
    unless FILE_RETENTION_HOURS is set (use a workspace for this app only).
    """
    client = owner_client()
    if client is None or hours <= 0:
        return 0
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
    deleted = 0
    try:
        for f in client.files.list():
            if f.created_at < cutoff:
                try:
                    client.files.delete(f.id)
                    deleted += 1
                except anthropic.APIError:
                    pass
    except anthropic.APIError:
        pass
    return deleted


def file_ids_in(blocks) -> list[str]:
    ids = []
    for b in blocks:
        if b.get("type") == "container_upload":
            ids.append(b["file_id"])
        elif b.get("source", {}).get("type") == "file":
            ids.append(b["source"]["file_id"])
    return ids


# ---------------------------------------------------------------- state

def init_state():
    ss = st.session_state
    ss.setdefault("messages", [])        # API-format history sent to Claude
    ss.setdefault("chat", [])            # what the UI shows: (role, text, images, sources)
    ss.setdefault("pending", [])         # blocks for files not yet sent
    ss.setdefault("loaded", {})          # file name -> kind
    ss.setdefault("container_id", None)
    ss.setdefault("file_ids", [])        # Files API ids to delete on "Start over"
    ss.setdefault("free_used", 0)        # questions asked on the owner's key
    ss.setdefault("chat_owner", None)    # "owner" or "visitor": whose key the chat is on


def reset_chat(client):
    ss = st.session_state
    if client is not None:
        delete_files(client, ss.file_ids)
    for key in ("messages", "chat", "pending", "loaded", "container_id",
                "file_ids", "chat_owner"):
        ss.pop(key, None)
    ss.uploader_round = ss.get("uploader_round", 0) + 1  # clears the uploader widget


# ---------------------------------------------------------------- sidebar

def pick_client():
    """Return (client, who) for this visitor, where who is 'visitor' or 'owner'."""
    key = ""
    if settings.ALLOW_VISITOR_KEYS:
        with st.sidebar.expander("Use your own API key",
                                 expanded=not settings.OWNER_KEY):
            key = st.text_input(
                "Anthropic API key", type="password", placeholder="sk-ant-...",
                help="Used only for your session and never stored. Get one at "
                     "platform.claude.com. Usage is billed to your account.",
            ).strip()
    if key:
        return visitor_client(key), "visitor"
    return owner_client(), "owner"


def allowed_types():
    exts = [e for e in SUPPORTED if settings.ALLOW_AUDIO or e not in AUDIO_EXTS]
    return [e.lstrip(".") for e in exts]


def sidebar(client):
    ss = st.session_state
    st.sidebar.header("Your files")
    if client is None:
        st.sidebar.info("Paste an Anthropic API key above to start.")
        return
    limits = f"Up to {settings.MAX_FILES} files, {settings.MAX_FILE_MB} MB each."
    uploads = st.sidebar.file_uploader(
        "CSV, Excel, text, PDF, images" + (" or audio" if settings.ALLOW_AUDIO else ""),
        type=allowed_types(),
        accept_multiple_files=True,
        help=limits,
        key=f"uploader_{ss.get('uploader_round', 0)}",
    )
    for f in uploads or []:
        if f.name in ss.loaded:
            continue
        if len(ss.loaded) >= settings.MAX_FILES:
            st.sidebar.warning(f"Skipped {f.name}: the limit is {settings.MAX_FILES} files. "
                               "Click Start over to use different files.")
            ss.loaded[f.name] = "skipped"
            continue
        if f.size > settings.MAX_FILE_MB * 1024 * 1024:
            st.sidebar.warning(f"Skipped {f.name}: larger than {settings.MAX_FILE_MB} MB.")
            ss.loaded[f.name] = "too large"
            continue
        if kind_of(f.name) == "audio" and not settings.ALLOW_AUDIO:
            ss.loaded[f.name] = "audio not available here"
            continue
        with st.sidebar.status(f"Preparing {f.name}…"):
            try:
                kind, blocks = to_blocks(client, f.name, f.getvalue())
            except Exception as e:  # show the problem, keep the app running
                st.sidebar.error(f"{f.name}: {e}")
                ss.loaded[f.name] = "error"
                continue
        ss.loaded[f.name] = kind
        ss.pending.extend(blocks)
        ss.file_ids.extend(file_ids_in(blocks))
    for name, kind in ss.loaded.items():
        st.sidebar.write(f"• {name} ({kind})")
    if st.sidebar.button("Start over"):
        reset_chat(client)
        st.rerun()
    if settings.PUBLIC_MODE:
        st.sidebar.caption(
            "Privacy: files are kept only for this browser session and sent to "
            "Anthropic's API to answer your questions. Click Start over to delete "
            "them. Don't upload anything sensitive.")


# ---------------------------------------------------------------- answers

def show_images(client, file_ids):
    images = []
    for fid in file_ids:
        meta = client.files.retrieve_metadata(fid)
        data = client.files.download(fid).read()
        if meta.filename.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            st.image(data, caption=os.path.basename(meta.filename))
            images.append(data)
        else:
            st.download_button(f"Download {os.path.basename(meta.filename)}", data,
                               file_name=os.path.basename(meta.filename), key=fid)
    return images


def show_sources(sources):
    """List the passages behind the [n] markers in an answer."""
    if not sources:
        return
    with st.expander(f"Sources ({len(sources)})"):
        for s in sources:
            where = f", {s['location']}" if s["location"] else ""
            quote = s["quote"].replace("\n", " ")
            st.markdown(f"**[{s['number']}] {s['title']}{where}**\n\n> {quote}")


def quota_note(who):
    if who != "owner" or settings.FREE_QUESTIONS_PER_SESSION <= 0:
        return
    left = max(0, settings.FREE_QUESTIONS_PER_SESSION - st.session_state.free_used)
    st.caption(f"{left} free question{'s' if left != 1 else ''} left in this session."
               + (" Add your own API key in the sidebar to keep going."
                  if settings.ALLOW_VISITOR_KEYS else ""))


def check_quota(who) -> str | None:
    """Return a message explaining why this question can't run, or None."""
    if who != "owner":
        return None
    if (settings.FREE_QUESTIONS_PER_SESSION > 0
            and st.session_state.free_used >= settings.FREE_QUESTIONS_PER_SESSION):
        return ("You've used the free questions for this session."
                + (" Add your own Anthropic API key in the sidebar to keep going."
                   if settings.ALLOW_VISITOR_KEYS else ""))
    if not take_daily_slot():
        return ("The site has reached its free limit for today. Please come back "
                "tomorrow" + (", or add your own API key in the sidebar."
                              if settings.ALLOW_VISITOR_KEYS else "."))
    return None


def main():
    init_state()
    if settings.FILE_RETENTION_HOURS > 0:
        sweep_old_files(settings.FILE_RETENTION_HOURS)
    client, who = pick_client()
    ss = st.session_state

    # Files and the sandbox belong to the key that created them, so switching
    # keys mid-chat starts a fresh chat.
    if ss.chat_owner and ss.chat_owner != who and (ss.messages or ss.loaded):
        old = owner_client() if ss.chat_owner == "owner" else None
        reset_chat(old)
        st.toast("Switched API key, so the chat started over.")
    if client is not None and (ss.loaded or ss.messages):
        ss.chat_owner = who

    sidebar(client)

    st.title("Chat with your files")
    if settings.PUBLIC_MODE and not ss.chat:
        st.markdown("Upload spreadsheets, documents or images in the sidebar, then ask "
                    "questions about them. Answers come from Claude and cite your files.")
    for role, text, images, sources in ss.chat:
        with st.chat_message(role):
            st.markdown(text)
            for img in images:
                st.image(img)
            show_sources(sources)

    if client is None:
        st.info("This site needs an Anthropic API key. Add yours in the sidebar.")
        return
    quota_note(who)

    question = st.chat_input("Ask about your files…", max_chars=settings.MAX_QUESTION_CHARS)
    if not question:
        return
    blocked = check_quota(who)
    if blocked:
        st.warning(blocked)
        return
    ss.chat_owner = who

    with st.chat_message("user"):
        st.markdown(question)
    ss.chat.append(("user", question, [], []))
    # Newly uploaded files ride along with this question, once.
    history_len = len(ss.messages)
    ss.messages.append({"role": "user",
                        "content": ss.pending + [{"type": "text", "text": question}]})
    sent_pending, ss.pending = ss.pending, []

    with st.chat_message("assistant"):
        status = st.empty()
        box = st.empty()
        parts = []

        def on_text(t):
            parts.append(t)
            status.empty()
            box.markdown("".join(parts))

        try:
            ss.container_id, file_ids, stop, blocks = run_turn(
                client, ss.messages, ss.container_id,
                on_text=on_text, on_status=lambda s: status.caption(s))
        except anthropic.AuthenticationError:
            del ss.messages[history_len:]  # drop the failed turn so history stays valid
            ss.chat.pop()
            ss.pending = sent_pending
            if who == "owner":
                give_back_daily_slot()
            st.error("That API key was rejected. Check it and try again."
                     if who == "visitor" else "The site's API key isn't working right now.")
            return
        except anthropic.APIError as e:
            del ss.messages[history_len:]  # drop the failed turn so history stays valid
            ss.chat.pop()
            ss.pending = sent_pending
            if who == "owner":
                give_back_daily_slot()
            st.error("Claude couldn't answer just now. Please try again in a moment."
                     if settings.PUBLIC_MODE else f"Claude API error: {e}")
            return
        if who == "owner":
            ss.free_used += 1
        ss.file_ids.extend(file_ids)
        status.empty()
        answer, sources = format_answer(blocks)
        answer = answer or "".join(parts) or "_(no text answer)_"
        if stop == "refusal":
            answer += "\n\n_Claude declined to answer this one._"
        box.markdown(answer)
        images = show_images(client, file_ids)
        show_sources(sources)
    ss.chat.append(("assistant", answer, images, sources))


main()
