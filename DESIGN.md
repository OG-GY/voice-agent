# Design: The Copper Pot

## Use case

I built a voice assistant for a made-up restaurant called The Copper Pot. It does the job a receptionist does on the phone: book a table, cancel a booking, and answer questions about opening hours, location, free tables and the table types. A caller can just talk, with no menu to go through, and the assistant should never say something worked when it didn't.

**The brain is my own code.** Rules, patterns and a state machine make every decision, including understanding what the caller said. No LLM (GPT, Claude, Gemini...) is used anywhere in the product. I chose this because the behavior is predictable, easy to test, and every reply can be explained by a decision trace.

## The big picture

```
Browser mic -> voice detection -> WebSocket -> faster-whisper -> THE BRAIN -> reply text -> browser voice
Typed text  --------------------> WebSocket ------------------> THE BRAIN
                                                                  |
                                                      booking repository -> SQLite
```

I kept conversation logic separate from audio, the network and the database, so each part can be tested and changed on its own.

- **Frontend:** Next.js, TypeScript and plain CSS. One page with Start call / End call.
- **Backend:** FastAPI with one WebSocket per call.
- **Brain:** a pure function of the current state, the caller's text, the clock and the booking repository's answers. It knows nothing about audio or the network.
- **Database:** SQLite behind a repository interface. The brain only talks to the interface. Tests use an in-memory version, and a different database could replace SQLite without touching the brain.
- **Speech:** faster-whisper turns speech into text. The browser's built-in voice speaks the replies. Typed text goes through the exact same brain.

## How the brain makes decisions

Every time the caller says something, the brain does these steps:

1. **Clean the text.** Lower-case it, drop fillers ("um", "uh"), fix common mishearings ("for people" becomes "four people"), turn spoken numbers into digits ("seven thirty" becomes 7:30), and fix typos like "widow table" with fuzzy matching. The fuzzy matching is deliberately careful: it only corrects toward restaurant words, never touches yes / no / cancel, and never touches names.
2. **Find the details.** Day ("tomorrow", "next Friday", "the 14th"), time ("7pm", "half past seven", "evening"), party size ("table for four", "me and my wife"), table type, name, title, phone number and booking reference.
3. **Work out what the caller wants.** Weighted patterns score intents such as book, cancel, ask availability, hours, location, "what's the difference between the tables", yes, no, hold on, repeat, start over, talk to a person, goodbye and off-topic. Context matters: "yes" counts more right after a yes/no question, and "actually make it 8" is a correction.
4. **Update what it knows.** The dialogue state remembers every detail so it never asks twice. The last mention wins ("4... no, 5 people" is 5), a vague answer like "this weekend" is kept aside until the caller picks a day, and "the second one" is matched against the options it just offered.
5. **Decide what to do.** A state machine. Interrupts are checked first on every turn (goodbye, hold on, repeat, a question, off-topic, not understood), then the handler for the current phase (booking, cancelling, enquiry).
6. **Ask the booking service** when needed: free tables, alternatives, booking, cancelling.
7. **Write the reply.** Short sentences made to be spoken, from templates.
8. **Record why.** Every turn produces a decision trace (intent, what changed, phase change, reason). The page shows it in the "What it decided" box.

## Making a booking

The brain collects the details in this order: table type, day, time, party size. Several can come in one sentence ("a window table on Friday at 8 for four"), and it only asks for what's missing.

- Each detail is validated as it arrives: not in the past, not a closed day, inside opening hours, on a 30-minute slot, a sensible party size, a table type that fits the party. A bad value is explained and asked again.
- **Availability is checked as soon as those four are known**, before asking for any personal details, so the caller isn't asked for a phone number for a table that isn't free.
- If it's taken, the brain offers the nearest free times for the same table type, plus the same time in the other types, and the caller can say "the second one". If the whole day is full, it points to the next day with space.
- Then it asks for the name, title (Mr / Mrs / Ms, or "just the name is fine") and phone number, and **reads the whole booking back**.
- **Nothing is booked until the caller says yes.**
- When the caller confirms, the booking is saved in one database transaction that re-checks the slot. If someone else took it in the meantime, the brain says so and offers alternatives. **The booking is only reported as done after the database confirms it**, and the caller hears a reference like `CP-4821`.
- Asking for the same booking twice (a retry, a dropped connection) returns the first booking and does not take a second table.

**"Sir" and "ma'am" are used only once the caller's title is known.** I never guess from a name or a voice. If the caller says "it's ma'am, not sir", it corrects itself with an apology.

### The restaurant

| | |
|---|---|
| Open | Tuesday to Sunday, 12:00 to 22:00. Last seating 21:00. Closed Mondays. |
| Slots | Every 30 minutes. A sitting lasts 90 minutes. Up to 60 days ahead. |
| General table | 4 tables of 2, 3 of 4, 1 of 6 (up to 6 people) |
| Window table | 3 tables of 2, 2 of 4 (up to 4 people) |
| Private table | 2 booths of 6, 1 room of 8 (3 to 8 people) |
| Bigger groups | More than 8 go to the events team. |

If the chosen type can't seat the party (a general table for 7), the brain doesn't just ask again. It explains and suggests the type that fits as a yes/no question, here the private area. It can also explain the three table types if the caller asks.

## Cancelling a booking

The caller gives the booking reference and the name on the booking. Only when both match does the brain describe the booking and ask for confirmation.

- **Every mismatch gets the same reply**, whether the reference is unknown or the name is wrong: "I couldn't match those details." It never says which part failed or whether the reference exists. Both answers are cleared, and the caller starts again.
- Three failures in one call hand the caller to the team. Too many failures from one caller (5 in 15 minutes) or overall (30 in 15 minutes) ends the call with "try again later". Those counts are kept in the database, so they survive restarts.
- The cancel itself also re-checks the name in one guarded database step, so a wrong name can never cancel anything and a booking can only be cancelled once.
- "Already cancelled" is only said after verification.

The name is a basic check for the demo. It is **not strong authentication**, and 4-digit references are guessable. Real use needs more.

## Calls that aren't a booking

- **Just asking:** hours, location, free tables, what the table types are. The brain answers, offers a booking once, and takes "no thanks" or "ok thanks" as a friendly goodbye. Anything the caller already said carries over if they decide to book.
- **Off-topic** ("what's the weather?"): it politely says it can't help and goes back to the question it was on. Three in a row go to the team.
- **Not understood:** it asks again. Three misses in a row, or the same question asked three times without an answer, go to the team.
- **"Hold on":** it waits quietly and is more patient with silence.
- **Repeat, start over, talk to a person, goodbye:** handled at any point. Goodbye in the middle of a booking warns once that it isn't saved yet.
- **Silence:** after a long wait it asks "Are you still there?" and ends the call if that continues.
- **Wrong phone number:** it must be 10 or 11 digits, said digit by digit or with hyphens. If not, it says the number doesn't look right instead of guessing.
- **Hanging up halfway:** nothing is saved. Only a confirmed booking is ever written.

## Interrupting the assistant

Callers can talk over the assistant, and it stops and listens. The risk is that its own voice comes out of the speakers and into the microphone. I handle that in layers:

- While it speaks, listening is stricter: louder and longer speech is needed, and the assistant's fading voice just after it stops is ignored.
- Each interruption is checked against what the speech recognizer actually heard. If nothing usable was heard, or the text mostly repeats the assistant's own sentence, it counts as a **suspected echo**. Two in a row switch that call to "no interrupting": the microphone is muted while it speaks, and the page says so.
- A real interruption (something different from the assistant's sentence) resets the count, even if the brain didn't understand it, so a real person is never switched off by mistake.
- It's one switch to turn off for good (`BARGE_IN_DEFAULT` in `frontend/lib/config.ts`). Headphones avoid the problem completely.

## When something goes wrong

- **Database unavailable or locked:** the brain says the booking system isn't available right now. The call stays up, hours and location still work, and the state is kept so the caller can continue. It never claims a booking or cancellation went through.
- **A bug in the brain:** the caller hears "I didn't quite get that" and the call goes on. Only the kind of error is logged.
- **Microphone blocked or no speech model:** the call continues by typing.
- **Speech queue full or too slow:** the caller is asked to say it again. A bounded queue protects the machine.
- **The call is lost or the server restarts:** the page tells the caller that the team will call back. **This is only wording. No callback system exists.**

## Audio on the frontend

The browser's microphone audio is resampled to 16 kHz mono with my own resampler (tested at 44.1 and 48 kHz), cut into 20 ms frames, and run through energy-based voice detection. A turn ends after 0.8 s of quiet, speech shorter than 0.3 s is ignored, and one utterance is at most 25 s. The whole utterance is sent as **one** message, never frame by frame. Audio stays in memory and is never saved.

The page's code that controls the call has no React or browser code in it, so it can be tested with fakes. It handles one request at a time, ignores late messages from an earlier call, and cleans up the microphone, audio, voice, listeners and connection exactly once, however the call ends. A new call starts completely fresh.

## Session and data

Each call has its own dialogue state in memory. Nothing is mixed between callers, and the state is dropped when the call ends. Bookings live in SQLite (WAL mode, one writer at a time). The database itself forbids two bookings on one table and slot, so a race between two callers can't double-book, and I tested that with 20 threads fighting for one table.

## Privacy, safety and limits

- Logs never contain what was said, names, phone numbers or references, and a filter masks anything that looks like one by mistake.
- What the page receives is a separate "public" version of each turn: personal details are masked in the trace and state. Only the spoken reply carries them, because the caller needs to hear the read-back.
- Every incoming message is validated. There are limits on message size, text and audio length, active calls, calls and messages per address, and a penalty for abusive clients.
- The backend refuses to start with unsafe production settings (a demo clock, demo data, a non-`https` origin, a missing secret).
- No data is real: every name and number is invented.
- For real use: secure WebSockets (`wss`) are required, and the origin check is not authentication, so call tokens would be needed.

## How I tested it

The backend has 163 tests and the frontend has 156. They cover the brain's conversations, cancel verification, the table-type questions, contact details, the SQLite rules (restarts, 20-thread races, a locked database), the WebSocket (errors, limits, close codes, shutdown), privacy of logs and traces, the audio code, the call controller with a fake microphone and voice, and the echo fallback. Where I could, I checked a test by breaking the code on purpose and watching it fail. See [README.md](README.md) to run them.

Unit tests can't prove how a real microphone and speakers behave together, so that part was tried by hand.

## Trade-offs and known limits

- **Rules instead of an AI model.** The brain is predictable and testable, but it only understands what I wrote patterns for. Unusual phrasing falls back to "didn't catch that" and a re-ask.
- **SQLite** keeps setup simple and suits one server. More servers would need PostgreSQL; the repository interface is there for that, and I wrote it down but did not build it.
- **One server process.** The limits and the speech queue are per process.
- **Browser voice** quality depends on the device. Something like ElevenLabs could replace it later if the quality is worth the cost and the extra dependency.
- **Speech recognition makes mistakes** ("Dad" instead of "Mr."). The brain asks again rather than guessing, but it can still be annoying.
- **Energy-based voice detection** can be fooled by steady loud noise. Typing is the fallback.
- **The callback message is not real**, as said above.
- **Not built:** accounts, call recording, backups and data-retention tooling, a metrics endpoint.

The main priority was correctness and predictable behavior over adding more infrastructure. Features count as done only once they're implemented and tested.
