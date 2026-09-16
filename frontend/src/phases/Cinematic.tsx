import { actions, skip, useStore } from '../store'

/**
 * The pre-arrival phases. They are not decoration: the tone-out, the response
 * and the size-up are where new EMTs actually get hurt, and no flashcard app
 * simulates them.
 */

export function ToneOut({ text }: { text: string }) {
  const [unit, ...rest] = text.split(',')
  return (
    <div className="cinematic cinematic--tone">
      <p className="cad-label">Dispatch</p>
      <p className="cad-unit">{unit}</p>
      <p className="cad-body">{rest.join(',').replace(/^\s*respond for:\s*/i, '')}</p>
    </div>
  )
}

export function EnRoute({ text }: { text: string }) {
  return (
    <div className="cinematic cinematic--enroute">
      <div className="lightbar" aria-hidden>
        <span />
        <span />
      </div>
      <p className="cad-body">{text}</p>
      <button type="button" className="ghost" onClick={skip}>
        Skip ahead
      </button>
    </div>
  )
}

export function Arrival({ text }: { text: string }) {
  return (
    <div className="cinematic cinematic--arrival">
      <div className="doors" aria-hidden>
        <span />
        <span />
      </div>
      <p className="cad-body">{text}</p>
    </div>
  )
}

export function SizeUpBanner() {
  return (
    <div className="cinematic cinematic--sizeup">
      <p className="cad-label">Scene size-up</p>
      <p className="cad-body">
        Scene safety · BSI · number of patients · MOI/NOI · additional resources
      </p>
    </div>
  )
}

/** Picks the overlay for whatever phase is on screen right now. */
export function Cinematic() {
  const current = useStore((s) => s.current)
  const difficulty = useStore((s) => s.difficulty)
  if (!current) return null

  // Basic-level trainees get the size-up checklist shown; harder levels get the
  // prompt alone. (The full scaffolding axis lands with the rest of Project 8.)
  if (current.phase === 'SIZE_UP') return difficulty === 'basic' ? <SizeUpBanner /> : null
  if (current.phase === 'TONE_OUT') return <ToneOut text={current.text} />
  if (current.phase === 'EN_ROUTE') return <EnRoute text={current.text} />
  if (current.phase === 'ARRIVAL') return <Arrival text={current.text} />
  if (current.phase === 'END_OF_CALL')
    return (
      <div className="cinematic cinematic--arrival">
        <p className="cad-body">{current.text}</p>
        <button type="button" onClick={actions.showDebrief}>
          See debrief
        </button>
      </div>
    )
  return null
}
