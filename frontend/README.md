# EMT Ride-Along — frontend

React + TypeScript + Vite. Plays a whole call: dispatcher tone-out, response,
arrival, a graded scene size-up, the patient turn by turn, then the debrief.

## Run it

```bash
python -m ems.cli.serve      # API on :8000  (from the repo root)
npm install && npm run dev   # UI  on :5173, /api proxied to :8000
```

The dev server binds `0.0.0.0`, so an iPad on the same network can open
`http://<your-mac-ip>:5173`.

## How it fits together

The server owns the state machine. One request per EMT turn: `store.ts` posts
what the EMT said and gets back every event the sim produces in reply, then
plays them out on a timer — that queue is what turns a JSON array into a call.

Two rules the UI must not break:

- **`Patient.tsx` renders only what the `SceneSpec` states.** The chest-rise
  animation period *is* the respiratory rate (RR 36 → a 1.67s cycle); the skin
  color *is* the scenario's stated skin finding. Nothing is invented.
- **`VitalsMonitor.tsx` shows only measured values.** The server decides what is
  known; a number the EMT never went and got stays `––`.

`prefers-reduced-motion` is honoured throughout — the call still plays, without
the animation.

## Voice

Nothing outside `src/voice/` names a speech API. `voice/index.ts` picks the
adapter; swapping `BrowserVoice` for `ServerVoice` is one line and no component
changes.

- **`BrowserVoice`** (default) — Web Speech API, client-side, free, offline.
- **`ServerVoice`** — posts to `/api/stt` and `/api/tts`. Both routes exist and
  return **501**; the contract is fixed so this can be written now and pointed
  at Whisper/Piper later.

Voice is **off until you turn it on** (🗣 in the corner) — microphones need a
user gesture, and an app that talks on load is an app people mute. With it on,
each line's own length sets the dwell, push-to-talk appears beside the input,
and pressing it interrupts whatever the sim is saying. The transcript stays on
screen either way: it is the fallback for a noisy bay and for any browser whose
speech recognition refuses.
