# AI Usage

I used AI as an assistant while building this project. The product decisions, the architecture, the rules of the brain and the choice of libraries were mine. The AI helped me think things through and wrote code for what I had already decided.

## How I worked

1. **Architecture first, by myself.** I started by writing down the architecture, the technical decisions and the flow of the voice agent. Then I gave it to Claude (chat) and talked through the product with it, and I reviewed what it said.
2. **Going deeper.** Claude asked me to define more precisely how each part would work. So I asked it what is needed to describe the complete technical implementation, and it gave me a list of areas. I used that list to break the work into steps.
3. **The brain.** I defined the rules myself: what the assistant asks, in what order, how it handles table types, corrections, cancellations and unclear callers. I used Claude to refine those rules, not to invent them.
4. **Claude Code.** After that I moved to Claude Code with all of those details in a markdown file. I asked it how this could be divided into small parts, and we split the work into small chunks of implementation.
5. **One feature at a time.** We started with the brain. Claude Code wrote a plan for it, I reviewed the plan and approved it, and only then was it implemented. After that I tested the feature myself, and only when it worked did we move to the next one (backend API, then frontend).

## Who decided what

- **Me:** the use case, the architecture, the rules of the brain, every library and technical decision (FastAPI, SQLite, faster-whisper, Next.js, browser voice, no LLM in the brain), what to build and what to leave out, and approving every plan.
- **AI:** writing code for the plans I approved, writing tests, and running checks. It did what I asked, and I tested the result before going on.

## Tools I used

- **Claude (chat):** to talk through the product and the architecture, and to refine my rules.
- **Claude Code:** to plan each part with me and write the code, the tests and the documents.
- **Graphify:** this was my own decision, not the AI's. I chose to add it and set it up in the project to cut token use. It builds a knowledge graph of the project, so Claude Code can look up how parts of the code connect instead of reading many files again and again. This reduced how many tokens were used.

## Where the AI was wrong

**The database.** The AI suggested PostgreSQL. This is a small project with one server, so I chose SQLite instead. It needs no setup, and the database itself stops two bookings on the same table and time. PostgreSQL stays a documented option if it ever needs more than one server.

**Other technical decisions I made myself:**

- WebSocket instead of WebRTC for the call. It is simpler, and I only need to send one utterance at a time.
- faster-whisper on the backend for speech to text, instead of the browser's Web Speech API. It gives me one predictable result that I can test.
- No Prometheus and no login or accounts. The project doesn't need them.
- No time zone handling, because all callers are in the same area.
- Table types (general, window, private), and asking "do you want a private or window table, or should I book a general one?" before booking.
- Calling the caller "sir" or "ma'am" only when they have told us, never guessing.

**Mistakes the AI made, which I found by testing:**

- It read "the 2nd one" (picking an option) as a date.
- It took the word "Fine" as the caller's name.
- It rejected phone numbers written with hyphens, and didn't say when a number had the wrong length.
- It treated "what's the difference?" as an off-topic question.
- It said a mutation check had failed a test before it had actually run it. I made it run the check and correct the note.
- It merged the work into the fork's `main`, against the submission guide. I had it move everything to the `candidate-OG-GY` branch and restore `main`.
- It first said my repository was not a fork, which was wrong.

In each case I found the problem by testing, and the AI fixed it with a test added.

## Token usage

These numbers come from my usage dashboard, one row per hour of use. They are the hours I have screenshots for. The dashboard shows one cost per hour, covering input, output and cache together. It does not split the cost between input and output.

| Hour | Cost | Input tokens | Output tokens | Input cache (miss) | Input cache (hit) | Messages |
|---|---|---|---|---|---|---|
| 13:00 | $1.56 | 38 | 34,718 | 93,209 | 1,230,369 | 13 |
| 15:00 | $1.55 | 26 | 39,895 | 64,337 | 4,489,363 | 5 |
| 19:00 | $11.73 | 78 | 120,843 | 886,095 | 31,095,753 | 4 |
| 20:00 | $9.28 | 88 | 84,110 | 153,688 | 39,098,020 | 8 |
| 21:00 | $0.21 | 4 | 1,625 | 40,728 | 131,392 | 1 |
| **Total** | **$24.33** | **234** | **281,191** | **1,238,057** | **76,044,897** | **31** |

- **Input tokens** are the new tokens sent to the model. **Input cache (miss)** are tokens read fresh and stored for reuse. **Input cache (hit)** are tokens reused from that cache, which is cheaper. Almost all of the input was cache hits, because the project context was reused on every message.
- **Output tokens** are what the AI wrote (code, tests, documents): about 281 thousand across these hours.
