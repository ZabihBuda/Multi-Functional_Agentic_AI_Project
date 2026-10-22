"""Chat with your files: a Streamlit UI over Claude.

Run:  streamlit run app.py
"""

import os

import anthropic
import streamlit as st
from dotenv import load_dotenv

from agent import run_turn
from file_handlers import SUPPORTED, to_blocks

load_dotenv()  # reads ANTHROPIC_API_KEY from a local .env file, if present

st.set_page_config(page_title="Chat with your files", page_icon="📂", layout="wide")


@st.cache_resource
def get_client():
    return anthropic.Anthropic()


def init_state():
    ss = st.session_state
    ss.setdefault("messages", [])        # API-format history sent to Claude
    ss.setdefault("chat", [])            # what the UI shows: (role, text, images)
    ss.setdefault("pending", [])         # blocks for files not yet sent
    ss.setdefault("loaded", {})          # file name -> kind
    ss.setdefault("container_id", None)


def sidebar(client):
    ss = st.session_state
    st.sidebar.header("Your files")
    uploads = st.sidebar.file_uploader(
        "CSV, Excel, text, PDF, images or audio",
        type=[e.lstrip(".") for e in SUPPORTED],
        accept_multiple_files=True,
    )
    for f in uploads or []:
        if f.name in ss.loaded:
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
    for name, kind in ss.loaded.items():
        st.sidebar.write(f"• {name} ({kind})")
    if st.sidebar.button("Start over"):
        for key in ("messages", "chat", "pending", "loaded", "container_id"):
            del ss[key]
        st.rerun()


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


def main():
    init_state()
    client = get_client()
    sidebar(client)
    ss = st.session_state

    st.title("Chat with your files")
    for role, text, images in ss.chat:
        with st.chat_message(role):
            st.markdown(text)
            for img in images:
                st.image(img)

    question = st.chat_input("Ask about your files…")
    if not question:
        return

    with st.chat_message("user"):
        st.markdown(question)
    ss.chat.append(("user", question, []))
    # Newly uploaded files ride along with this question, once.
    ss.messages.append({"role": "user",
                        "content": ss.pending + [{"type": "text", "text": question}]})
    ss.pending = []

    with st.chat_message("assistant"):
        status = st.empty()
        box = st.empty()
        parts = []

        def on_text(t):
            parts.append(t)
            status.empty()
            box.markdown("".join(parts))

        try:
            ss.container_id, file_ids, stop = run_turn(
                client, ss.messages, ss.container_id,
                on_text=on_text, on_status=lambda s: status.caption(s))
        except anthropic.APIError as e:
            ss.messages.pop()  # drop the failed question so history stays valid
            st.error(f"Claude API error: {e}")
            return
        status.empty()
        answer = "".join(parts) or "_(no text answer)_"
        if stop == "refusal":
            answer += "\n\n_Claude declined to answer this one._"
        box.markdown(answer)
        images = show_images(client, file_ids)
    ss.chat.append(("assistant", answer, images))


main()
