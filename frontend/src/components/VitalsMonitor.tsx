import { useEffect, useRef, useState } from 'react'

import { reducedMotion } from '../store'
import type { Vitals } from '../types'

/**
 * Shows only what the EMT has measured. You do not see a blood pressure you
 * never took — the server decides what is known, this just renders it.
 *
 * When a value *changes*, it transitions rather than snapping: a number that
 * jumps reads as a UI state change, a number that moves reads as a patient
 * responding to what you did. Nothing changes vitals until Project 6 adds a
 * physiology model, so today this fires on the ventilation-improves case only
 * when a value is corrected — the machinery is here and tested.
 */
function useAnimated(value: number | undefined): number | undefined {
  const [shown, setShown] = useState(value)
  const previous = useRef(value)

  useEffect(() => {
    if (value === undefined) {
      previous.current = undefined
      setShown(undefined)
      return
    }
    // First appearance: fade in at the true value, never count up from zero.
    if (previous.current === undefined || reducedMotion) {
      previous.current = value
      setShown(value)
      return
    }
    const from = previous.current
    const started = performance.now()
    let frame = 0
    const tick = (now: number) => {
      const k = Math.min(1, (now - started) / 1200)
      setShown(Math.round(from + (value - from) * k))
      if (k < 1) frame = requestAnimationFrame(tick)
      else previous.current = value
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [value])

  return shown
}

function Reading({
  label,
  value,
  unit,
  generated,
}: {
  label: string
  value?: number | string
  unit?: string
  generated?: boolean
}) {
  const numeric = typeof value === 'number' ? value : undefined
  const animated = useAnimated(numeric)
  const display = typeof value === 'string' ? value : animated
  const known = display !== undefined

  return (
    <div className={`reading ${known ? 'reading--known' : 'reading--unknown'}`}>
      <span className="reading-label">
        {label}
        {/* The scenario did not state this one; the simulator made it up. Say so
            on the tile rather than letting it pass as vetted content. */}
        {known && generated && (
          <abbr className="sim-tag" title="Simulator-generated — not stated by this scenario">
            SIM
          </abbr>
        )}
      </span>
      <span className="reading-value">
        {known ? display : '––'}
        {known && unit && <em>{unit}</em>}
      </span>
    </div>
  )
}

export function VitalsMonitor({
  vitals,
  generated = [],
}: {
  vitals: Vitals
  generated?: string[]
}) {
  const made = new Set(generated)
  return (
    <section className="monitor" aria-label="Vitals monitor">
      <Reading label="RR" value={vitals.rr} generated={made.has('rr')} />
      <Reading label="Pulse" value={vitals.hr} generated={made.has('hr')} />
      <Reading label="SpO₂" value={vitals.spo2} unit="%" generated={made.has('spo2')} />
      <Reading label="BP" value={vitals.bp} generated={made.has('bp')} />
    </section>
  )
}
