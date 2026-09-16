import { useEffect, useRef } from 'react'

import type { SimEvent } from '../types'

const WHO: Record<string, string> = {
  dispatcher: 'Dispatch',
  narrator: 'Scene',
  patient: 'Patient',
  sim: 'Sim',
  emt: 'You',
}

/** Always visible: it is the fallback when audio is off or the room is loud. */
export function Transcript({ lines }: { lines: SimEvent[] }) {
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [lines.length])

  return (
    <section className="transcript" aria-label="Transcript" aria-live="polite">
      {lines.map((line, i) => (
        <p key={i} className={`line line--${line.speaker}`}>
          <span className="who">{WHO[line.speaker] ?? line.speaker}</span>
          {line.text}
        </p>
      ))}
      <div ref={end} />
    </section>
  )
}
