# Putting the app on the web

This guide puts "Chat with your files" online as a public website on
[Streamlit Community Cloud](https://streamlit.io/cloud), which is free and
deploys straight from this GitHub repository. It takes about 15 minutes.

## How the public site protects you

When `PUBLIC_MODE` is on, the app adds these safeguards:

| Safeguard | Default | Setting |
|---|---|---|
| Free questions per visitor session, on your key | 10 | `FREE_QUESTIONS_PER_SESSION` |
| Free questions per day, across all visitors | 300 | `DAILY_QUESTION_CAP` |
| Visitors can paste their own API key to keep going | on | `ALLOW_VISITOR_KEYS` |
| Files per session | 5 | `MAX_FILES` |
| Size per file | 10 MB | `MAX_FILE_MB` and `server.maxUploadSize` in `.streamlit/config.toml` |
| Question length | 2,000 characters | `MAX_QUESTION_CHARS` |
| Audio uploads (CPU-heavy transcription) | off | `ALLOW_AUDIO` |
| Delete uploaded files from Anthropic after N hours | off (2 in the example) | `FILE_RETENTION_HOURS` |

Other things that are true in public mode:

- Visitor files are never written to disk on the server. They stay in the
  visitor's browser session and are sent to Anthropic's API. **Start over**
  deletes them from Anthropic's Files API too.
- A visitor's own API key lives only in their session and is never stored or logged.
- Error details are hidden from visitors, and the Streamlit developer menu is hidden.
- Your API key lives in the host's secrets settings, never in the repository.

The per-session and daily caps live in the server's memory, so they reset when the
app restarts, and a visitor can get a new session by reopening the page. They
are a safety net. **Your real budget guard is the spend limit in the Claude
Console (step 1).**

To have no free tier at all (every visitor brings their own key), leave
`ANTHROPIC_API_KEY` out of the secrets. To use only your key, set
`ALLOW_VISITOR_KEYS = "0"`.

## Step 1: Make a dedicated API key with a spend limit

1. Sign in to the [Claude Console](https://platform.claude.com).
2. Create a new **workspace** just for this site, for example `file-chat-public`.
   Keeping it separate means the file cleanup below can't touch your other files,
   and you can see the site's costs on their own.
3. In that workspace, set a **monthly spend limit** you're comfortable with (for
   example $20). When it's reached, the site's free questions stop working
   until next month, and visitors with their own key are unaffected.
4. Create an **API key** in that workspace and copy it somewhere safe for step 3.

## Step 2: Deploy from GitHub

1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with GitHub.
2. Click **Create app** and choose to deploy from a GitHub repository.
3. Pick this repository, branch `main`, and main file `app.py`.
4. Optionally pick a custom subdomain, such as `chat-with-your-files`.
5. Open **Advanced settings**, choose Python 3.12 or newer, and paste the
   secrets from step 3 into the **Secrets** box.
6. Click **Deploy**. The first build takes a few minutes.

A private repository works too: Community Cloud asks for access to it, and the
website is still public.

## Step 3: Secrets

Copy `.streamlit/secrets.toml.example`, put in your key from step 1, and paste
it into the Secrets box. You can change these any time under the app's
**Settings > Secrets**; the app restarts with the new values.

```toml
ANTHROPIC_API_KEY = "sk-ant-..."
PUBLIC_MODE = "1"
FREE_QUESTIONS_PER_SESSION = "10"
DAILY_QUESTION_CAP = "300"
ALLOW_VISITOR_KEYS = "1"
MAX_FILE_MB = "10"
MAX_FILES = "5"
ALLOW_AUDIO = "0"
FILE_RETENTION_HOURS = "2"
CLAUDE_MODEL = "claude-opus-5-5"
CLAUDE_EFFORT = "high"
```

## Step 4: Check it

Open the site in a private browser window and:

1. Upload a small CSV and ask a question about it. You should get an answer
   and see "N free questions left".
2. Upload a PDF and check that the answer has `[1]`-style citations.
3. Click **Start over** and check the files list empties.
4. In the Claude Console, check the workspace's usage shows the questions.

## Costs

With Claude Opus 5.5 at `high` effort, a question typically costs somewhere
between a few cents and half a dollar, more for big files or long chats.
Watch the workspace's usage page for the first few days to see real numbers. To make the free tier cheaper, set
`CLAUDE_EFFORT = "medium"`, or `CLAUDE_MODEL = "claude-sonnet-5-5"` (about half
the price per token). Lower the caps if usage grows faster than you'd like.

## Other hosts

The app is a plain Streamlit app, so it also runs on Hugging Face Spaces
(Streamlit SDK), Render, Railway or any Docker host. Set the same values as
environment variables there, and run
`streamlit run app.py --server.port $PORT --server.address 0.0.0.0`.
