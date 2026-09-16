import { useEffect, useRef, useState } from 'react'

import { reducedMotion } from './store'

/**
 * A shared clock and a spring. About sixty lines, no dependency.
 *
 * What made the old motion look cheap was not the shapes — it was that every
 * moving thing used `transition: 900ms ease`, so an arm, a head and a torso all
 * started together, traveled at the same rate and arrived together. Nothing
 * had weight. A spring fixes that on its own: it overshoots a little, settles,
 * and does it at a speed that depends on how far it had to go.
 *
 * Everything here collapses to a jump under `prefers-reduced-motion`. That is
 * checked once at module load, in the store, because it is the same question
 * for every consumer.
 */

// ── the clock ────────────────────────────────────────────────────────────────
//
// One requestAnimationFrame loop for the whole app, not one per component. It
// runs only while something is subscribed, so nothing is burning a frame budget
// on the debrief screen.

type Tick = (seconds: number) => void

const subscribers = new Set<Tick>()
let frame = 0
let origin = 0

function loop(now: number) {
  if (!origin) origin = now
  const seconds = (now - origin) / 1000
  subscribers.forEach((fn) => fn(seconds))
  frame = subscribers.size ? requestAnimationFrame(loop) : 0
}

function subscribeToClock(fn: Tick) {
  subscribers.add(fn)
  if (!frame) frame = requestAnimationFrame(loop)
  return () => {
    subscribers.delete(fn)
    if (!subscribers.size && frame) {
      cancelAnimationFrame(frame)
      frame = 0
    }
  }
}

/**
 * Seconds since the first frame, updated every frame.
 *
 * Re-renders the calling component at the display's refresh rate, so use it on
 * a leaf — the patient figure, not the screen around it.
 */
export function useClock(active = true): number {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    if (!active || reducedMotion) return
    return subscribeToClock(setSeconds)
  }, [active])
  return seconds
}

// ── the spring ───────────────────────────────────────────────────────────────

export interface SpringConfig {
  /** How hard it pulls toward the target. Higher is snappier. */
  stiffness?: number
  /** Resistance. Left out, it is critical damping — arrives without wobbling. */
  damping?: number
}

/**
 * Follows `target` under spring physics, returning the current value.
 *
 * Integrated in fixed 4ms sub-steps rather than one step of whatever the frame
 * happened to be: a dropped frame in a variable-step integrator does not just
 * stutter, it changes the trajectory, and a stiff spring can leave the screen
 * entirely.
 */
export function useSpring(target: number, config: SpringConfig = {}): number {
  const stiffness = config.stiffness ?? 170
  const damping = config.damping ?? 2 * Math.sqrt(stiffness)

  const [value, setValue] = useState(target)
  const state = useRef({ x: target, v: 0, last: 0 })

  useEffect(() => {
    if (reducedMotion) {
      state.current.x = target
      state.current.v = 0
      setValue(target)
      return
    }
    return subscribeToClock((seconds) => {
      const s = state.current
      const elapsed = s.last ? Math.min(seconds - s.last, 0.064) : 0
      s.last = seconds

      const STEP = 0.004
      for (let t = 0; t < elapsed; t += STEP) {
        const dt = Math.min(STEP, elapsed - t)
        s.v += (-stiffness * (s.x - target) - damping * s.v) * dt
        s.x += s.v * dt
      }

      // Settled. Snap and stop re-rendering — a spring that never quite
      // arrives keeps the whole app at 60fps forever.
      if (Math.abs(s.x - target) < 0.0005 && Math.abs(s.v) < 0.0005) {
        s.x = target
        s.v = 0
      }
      setValue(s.x)
    })
  }, [target, stiffness, damping])

  return value
}

// ── breathing ────────────────────────────────────────────────────────────────

/**
 * How far through one breath, as chest excursion from 0 (fully exhaled) to 1.
 *
 * Not a sine wave. Inspiration is active and takes about a third of the cycle;
 * expiration is passive, slower, and is followed by an end-expiratory pause
 * where the chest is simply still. A symmetric `ease-in-out` on scaleY has no
 * pause at all, which is exactly why the old one read as a pulsing rectangle
 * rather than as someone breathing.
 */
export function breathCurve(phase: number, agonal = false): number {
  // Agonal respirations are a gasp and a long nothing — the pause is the
  // clinical finding, so it has to be visible as one.
  const inhale = agonal ? 0.1 : 0.34
  const exhale = agonal ? 0.16 : 0.46

  if (phase < inhale) {
    // Fast off the bottom, decelerating into full inspiration.
    return Math.sin((phase / inhale) * (Math.PI / 2))
  }
  if (phase < inhale + exhale) {
    const p = (phase - inhale) / exhale
    return (1 + Math.cos(p * Math.PI)) / 2
  }
  return 0
}

/** Blink openness: 1 open, 0 shut. Intervals vary, because a metronome blink
 *  is more unsettling than no blink at all.
 *
 *  The schedule advances in an effect rather than during render: React may
 *  render the same frame twice, and drawing the next interval during render
 *  would consume two of them and make the blinking twice as fast under
 *  StrictMode as in production. */
export function useBlink(seconds: number, enabled: boolean): number {
  const schedule = useRef({ at: 2.5, closed: false })
  const [, force] = useState(0)

  useEffect(() => {
    if (!enabled || reducedMotion) return
    const s = schedule.current
    if (!s.closed && seconds >= s.at) {
      s.closed = true
      force((n) => n + 1)
    } else if (s.closed && seconds >= s.at + CLOSED_FOR) {
      s.closed = false
      // 2.4–7.2s. Drawn fresh each time rather than jittered around a mean, so
      // two blinks in quick succession stay possible.
      s.at = seconds + 2.4 + Math.random() * 4.8
      force((n) => n + 1)
    }
  }, [seconds, enabled])

  if (!enabled || reducedMotion) return 1
  const into = seconds - schedule.current.at
  if (into < 0 || into > CLOSED_FOR) return 1
  // Down and up: shutting is faster than opening, as a real lid is.
  const p = into / CLOSED_FOR
  return p < 0.4 ? 1 - p / 0.4 : (p - 0.4) / 0.6
}

const CLOSED_FOR = 0.14
