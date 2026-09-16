import { useEffect, useRef, useState } from 'react'

import { actions, canSpeak, useStore } from '../store'
import { voice } from '../voice'

const PROMPT: Record<string, string> = {
  SIZE_UP: 'Size up the scene.',
  TURN: 'What do you do or say?',
}

/** Whose turn it is, and the typed input. Voice replaces this in Project 7. */
export function TurnPrompt() {
  const phase = useStore((s) => s.phase)
  const ready = useStore(canSpeak)
  const busy = useStore((s) => s.busy)
  const done = useStore((s) => s.done)
  const voiceOn = useStore((s) => s.voiceOn)
  const listening = useStore((s) => s.listening)
  const heardSoFar = useStore((s) => s.heardSoFar)
  const hint = useStore((s) => s.hint)
  const hintsOn = useStore((s) => s.hintsOn)
  const [text, setText] = useState('')
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (ready) input.current?.focus()
  }, [ready, phase])

  // The call being over used to render nothing here, which left the only route
  // onward as a button in the header — off-screen after a call of any length.
  // Whoever just finished is looking at this spot, so the way forward goes here.
  if (done) {
    return (
      <div className="turn turn--over">
        <p className="turn-prompt">
          <span className="pip" aria-hidden />
          Call complete.
        </p>
        <button type="button" onClick={actions.showDebrief}>
          See debrief
        </button>
      </div>
    )
  }

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const said = text.trim()
    if (!said || !ready) return
    setText('')
    void actions.speak(said)
  }

  return (
    <form className={`turn ${ready ? 'turn--yours' : ''}`} onSubmit={submit}>
      <p className="turn-prompt">
        <span className={`pip ${ready ? 'pip--live' : ''}`} aria-hidden />
        {listening
          ? 'Listening — release when you finish.'
          : ready
            ? (PROMPT[phase] ?? 'Your turn.')
            : busy
              ? 'Thinking…'
              : 'Listen…'}
        {/* What the recognizer has so far. Seeing "6 l" appear while you are
            still saying "liters per minute" is the difference between
            correcting it now and finding it in the transcript afterwards. */}
        {listening && heardSoFar && (
          <span className="heard-so-far">“{heardSoFar}”</span>
        )}
        {/* Reproduced as a specimen in UserGuide.tsx — keep the labels in step. */}
        <button
          type="button"
          className={`hint-toggle ${hintsOn ? 'hint-toggle--on' : ''}`}
          aria-pressed={hintsOn}
          onClick={() => actions.setHints(!hintsOn)}
        >
          {hintsOn ? 'Hints on' : 'Hints off'}
        </button>
      </p>
      {/* Only while it is actually your move — a nudge after the fact is a
          spoiler, not a hint. */}
      {hintsOn && ready && hint && <p className="nudge">💡 {hint}</p>}
      {/* Any reason, not just an absent API: a denied mic permission leaves
          `canListen` true and used to show nothing at all. */}
      {voiceOn && voice.listenBlockedReason && (
        <p className="hint">{voice.listenBlockedReason}</p>
      )}
      {/* The loop runs ask → answer → decide for as long as you keep talking,
          so how to stop has to be said rather than inferred from a button. */}
      {ready && (
        <p className="hint">
          Finished? Press <strong>End call</strong> — or say “end of call” — to get your debrief.
        </p>
      )}
      <div className="turn-row">
        {voiceOn && voice.canListen && (
          <button
            type="button"
            className={`ptt ${listening ? 'ptt--live' : ''}`}
            disabled={!ready && !listening}
            aria-label="Push to talk"
            aria-pressed={listening}
            onPointerDown={() => void actions.pushToTalk()}
            onPointerUp={actions.releaseToTalk}
            onPointerLeave={actions.releaseToTalk}
          >
            🎙
          </button>
        )}
        <input
          ref={input}
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={!ready}
          placeholder={ready ? 'Say what you would do…' : ''}
          aria-label="What you say or do"
          enterKeyHint="send"
        />
        <button type="submit" disabled={!ready || !text.trim()}>
          Say
        </button>
        <button type="button" className="ghost" onClick={() => void actions.endCall()} disabled={busy}>
          End call
        </button>
      </div>
    </form>
  )
}
