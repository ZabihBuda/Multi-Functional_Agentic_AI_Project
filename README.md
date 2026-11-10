# Chat with your files

Upload spreadsheets, documents, images or audio, then ask questions about them in plain language. Answers come from Claude, which runs real Python code on your tables instead of guessing at numbers.

Built with Python, [Streamlit](https://streamlit.io) and the [Claude API](https://platform.claude.com/docs).

## What it can do

- **Spreadsheets** (CSV, TSV, Excel, JSON, Parquet): "What were total sales by region?", "Plot revenue per month." Claude loads the file with pandas in a secure cloud sandbox, computes the answer and draws charts.
- **Documents** (TXT, Markdown, logs, PDF): "Summarize this report", "What does it say about deadlines?" Answers cite the passage they come from.
- **Images** (PNG, JPG, GIF, WebP): "What's in this photo?", "Read the numbers off this chart."
- **Audio** (MP3, WAV, M4A, OGG, FLAC): turned into a transcript on your machine, then handled like a document.

You can upload several files at once and ask questions that span them.

## How it keeps answers accurate

The app is built to answer from your files, not from Claude's general knowledge:

- **Grounded answers.** Claude is told to answer only from the uploaded files and to say plainly when they don't contain the answer, rather than guess. Where files only partly answer a question, or disagree with each other, it says so.
- **Computed numbers.** Every total, average, percentage or comparison is calculated with Python in the sandbox, never estimated. Claude checks each table's columns, types and missing values first, and states the columns and filters it used so you can check the method.
- **Citations.** Answers from documents, PDFs and transcripts carry `[1]`-style markers. Open **Sources** under the answer to see the exact passage each one rests on, with page numbers for PDFs. Answers from tables name the file and columns; answers from images name the image.
- **Stated uncertainty.** Claude flags unreadable parts of images, possible speech-recognition errors in transcripts, and ambiguous questions (saying which reading it used).
- **Careful effort.** The model runs at `high` effort, so it spends more time checking its work before answering.

## Quick start

You need Python 3.10 or newer and an Anthropic API key from the [Claude Console](https://platform.claude.com).

```bash
git clone https://github.com/ZabihBuda/Multi-Functional_Agentic_AI_Project.git
cd Multi-Functional_Agentic_AI_Project

python -m venv .venv
source .venv/bin/activate          # on Windows: .venv\Scripts\activate

pip install -r requirements.txt
pip install faster-whisper         # optional, only for audio files

cp .env.example .env               # on Windows: copy .env.example .env
# open .env and paste your API key

streamlit run app.py
```

Streamlit opens the app in your browser (usually at http://localhost:8501). Drop files into the sidebar and start asking.

## How it works

```
your files ──> file_handlers.py ──> Claude message blocks
                                         │
your question ──> agent.py ──> Claude Opus 5.5 + code execution sandbox
                                         │
                app.py <── streamed answer, tables and charts
```

| File | What it does |
|---|---|
| `app.py` | The Streamlit page: sidebar uploader, chat history, streaming answers, inline charts |
| `agent.py` | Sends the conversation to Claude, streams the reply, resumes long code runs, collects charts Claude saves |
| `file_handlers.py` | Turns each upload into the right input: sandbox upload for tables, document for text and PDF, image for pictures, transcript for audio |

New files are sent along with your next question, once. The sandbox is kept between questions, so data Claude has loaded stays loaded.

## Settings you can change

| Setting | Where | Default |
|---|---|---|
| Model | `MODEL` in `agent.py` | `claude-opus-5-5` (try `claude-sonnet-5-5` for cheaper, faster answers) |
| Effort | `EFFORT` in `agent.py` | `high` (`medium` is cheaper and faster, `max` is the most thorough) |
| Instructions to Claude | `SYSTEM` in `agent.py` | answer only from the files, compute numbers with code, cite sources, flag uncertainty |
| Speech-to-text model | `transcribe()` in `file_handlers.py` | Whisper `base` on CPU |

## Costs and privacy

- Each question is billed to your Anthropic account by tokens used. Large text files are resent with every question, so they cost more over a long chat.
- Tables, PDFs and images are uploaded to Anthropic through the Files API, and code runs in Anthropic's sandbox. Audio is transcribed locally and only the transcript is sent.
- Your API key stays in `.env`, which `.gitignore` keeps out of Git.

## Known limits

- The sandbox expires after a period of inactivity. If a later question fails, click **Start over** in the sidebar.
- Audio transcription on CPU is slow for long recordings, and transcripts can mishear words. Check important quotes against the recording.
- Citations with exact passages cover documents, PDFs and transcripts. For tables and images, the answer names its source but has no clickable passage.
- This is a prototype: there is no login, and chats are not saved after you close the page.

## License

MIT. See [LICENSE](LICENSE).
