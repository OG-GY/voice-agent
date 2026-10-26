# The Copper Pot: voice reservation assistant

I built a voice assistant for a made-up restaurant called The Copper Pot. You call it from the browser, talk to it, and it can book a table, cancel a booking, or answer questions about the restaurant, like opening hours, free tables and the difference between table types.

The assistant's brain is my own code: rules, patterns and a state machine. **No big AI model (GPT, Claude, Gemini...) makes any decision.** Speech to text is faster-whisper, and the voice you hear is the browser's built-in voice.

All data is fake. You don't need any API key or account to run it.

- How the brain makes decisions: see [DESIGN.md](DESIGN.md)
- Which AI tools I used while building it: see [AI_USAGE.md](AI_USAGE.md)

```
Browser (mic) -> WebSocket -> faster-whisper -> the brain (my code) -> reply text -> browser voice
                                                   |
                                          SQLite (fake bookings)
```

---

## What you need first

Install these once:

1. **Python 3.12 and uv.** uv installs the right Python for you. On Windows, open PowerShell and run:
   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```
   On macOS or Linux, see https://docs.astral.sh/uv/ for the one-line install.
2. **Node.js 20 or newer** (with npm). Get it from https://nodejs.org.
3. **Chrome or Edge.** They work best for the microphone. Firefox works too.

Close and reopen your terminal after installing, then check that `uv --version` and `node --version` both work.

---

## Step 1: Run the backend

Go to the backend folder:

```powershell
cd backend
```

Do this once:

```powershell
uv sync                                          # installs everything from the lock file
uv run python -m app.speech.download_model       # downloads the speech model (about 150 MB)
```

Now start it:

```powershell
uv run python -m app.serve
```

Leave this terminal open. Check that it works by opening these in your browser:

- http://localhost:8000/health should say `{"status":"ok"}`
- http://localhost:8000/ready should say `"status":"ready"` (it says `"degraded"` for a few seconds while the speech model loads, and for good if the model is missing: text still works)

The database is a small file in `backend/data/` that is created for you. The fake demo bookings are loaded every time the backend starts, so **restart the backend to reset the demo data.**

---

## Step 2: Run the frontend

Open a **second terminal** and go to the frontend folder:

```powershell
cd frontend
npm ci
npm run dev
```

Now open **http://localhost:3000** in Chrome or Edge. Use `localhost` exactly like this, not `127.0.0.1`: the backend only accepts calls from `localhost:3000`.

If your backend is somewhere else, copy `.env.example` to `.env.local` and change `NEXT_PUBLIC_WS_URL`.

---

## Step 3: Make a call

1. Press **Start call** and allow the microphone when the browser asks.
2. Listen to the greeting, then talk when the status says **Listening: go ahead**.
3. Watch the **What it decided** box. It shows what the brain understood and why it answered the way it did.
4. Press **End call** when you're done.

No microphone, or you blocked it? Type in the box at the bottom instead. The call works the same.

Things to try:

- **Book a table:** "I want to book a table", then answer its questions. It asks for the table type, the day, the time, how many people, then your name, Mr/Ms, and phone number.
- **Ask what the table types are:** "What's the difference?"
- **Ask questions:** "What are your timings?", "Where are you?", "Do you have any window tables tonight?"
- **Change your mind:** "Actually make it 5 people."
- **Pick a table that doesn't fit:** a general table for 7 people. It suggests the private area.
- **Cancel a booking:** say "cancel my booking", then the reference `CP-1001`, then the name `Alex Sample`. That's a fake booking made for testing.
- **Interrupt it:** start talking while it's speaking and it stops to listen.
- **Say something unrelated:** "What's the weather?" It politely says it can't help with that.
- **Hold on / start over / talk to a person:** it handles those too.

The coming Friday's window tables are all full at 7 PM, and Saturday evening is busy. That lets you try the "this time is taken, how about these?" answers.

Using speakers? The assistant can hear its own voice through the mic. If that happens twice in one call, it turns interrupting off for that call and tells you. **Headphones fix it.**

---

## Chat with the brain without a browser

You can talk to the brain in the terminal, with no microphone and no frontend:

```powershell
cd backend
uv run python -m app.brain.cli --trace
```

Type what a caller would say. `--trace` prints what the brain decided after every reply. Add `--now "2026-10-28 15:00"` to freeze the clock so "tomorrow" always means the same day. Type `/help` inside it to see the extra commands.

---

## Run the tests

Backend (from `backend/`):

```powershell
uv run pytest                  # 163 tests
uv run ruff check app tests    # style check
uv run mypy app                # type check
```

Frontend (from `frontend/`):

```powershell
npm test                       # 156 unit tests
npm run typecheck
npm run lint
npm run build
```

The backend has no model-dependent tests: they use a fake speech-to-text, so you don't need the speech model to run them.

There is also one optional test that talks to a **running** backend:

```powershell
cd frontend
$env:LIVE_WS_URL = "ws://127.0.0.1:8000/ws/call"
npx vitest run lib/live.test.ts
```

---

## Settings

The backend reads `backend/.env`. The defaults in `.env.example` are fine for trying it out. The ones you might change:

| Setting | What it does |
|---|---|
| `PORT` | Backend port (default 8000). |
| `STT_ENABLED` | `false` turns speech recognition off. Text calls still work. |
| `STT_MODEL` | Speech model (`base.en` by default). `small.en` is more accurate but slower. |
| `SEED_DEMO_DATA` | Loads the fake demo bookings at startup. |
| `EXPOSE_DEBUG_TRACE` | Shows the cleaned-up text in the "What it decided" box. Development only. |
| `CORS_ORIGINS` | Which websites may call the backend (default `http://localhost:3000`). |
| `BRAIN_FIXED_NOW` | Freezes the clock for demos, like `2026-10-30 18:00`. Development only. |

Setting `APP_ENV=production` turns on strict checks. The backend refuses to start if something unsafe is set, like the demo clock, demo data, or a non-`https` origin.

---

## If something goes wrong

- **"Couldn't connect"**: the backend isn't running, or you opened `127.0.0.1:3000` instead of `localhost:3000`.
- **`/ready` says `degraded`, or it says speech isn't available**: the speech model isn't loaded. Run the `download_model` command from Step 1 and restart the backend. You can still type.
- **The browser never asks for the microphone**: check the site's permissions in the browser, then reload the page.
- **It mishears a word** (for example "Mr." as "Dad"): say it a bit slower, or type it.
- **The assistant keeps cutting itself off**: use headphones. Or set `BARGE_IN_DEFAULT` to `false` in `frontend/lib/config.ts` to turn interrupting off.
- **Port already in use**: change `PORT` in `backend/.env`, and `NEXT_PUBLIC_WS_URL` in `frontend/.env.local` to match.

---

## Where things are

```
backend/
  app/brain/           the brain: understanding, remembering, deciding, replying
  app/services/        the restaurant, the clock, the booking rules, SQLite bookings
  app/api/             the WebSocket, limits, health checks
  app/speech/          speech-to-text (faster-whisper) and its queue
  app/db/, migrations/ the database file and its setup
  tests/               backend tests
frontend/
  lib/                 the call logic: protocol, audio pipeline, voice detection
  components/, app/    the page you see
```

Not built on purpose: accounts and logins, recording calls, and a real callback system. When the assistant says "our team will call you back", that is only wording. [DESIGN.md](DESIGN.md) lists the other known limits.
