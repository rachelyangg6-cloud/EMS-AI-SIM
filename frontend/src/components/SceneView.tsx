import { useEffect, useId, useState } from 'react'

import { useSpring } from '../motion'
import type { SceneSpec } from '../types'
import { Patient } from './Patient'

/**
 * Layered scene: background (by setting, tinted by time of day) → hazards →
 * patient → bystanders → equipment.
 *
 * Most scenarios in the corpus never say where they are, so `unknown` is the
 * common case and has to look deliberate rather than broken.
 *
 * **Arrival is a camera push-in, not a fade.** Background, patient and the
 * foreground chips settle on a spring at different rates, which is the whole of
 * what reads as depth here — three layers is enough. It replaces a door-opening
 * keyframe that was a cut with an easing curve on it.
 */

const SKY: Record<string, [string, string]> = {
  day: ['#cfe0ef', '#eef3f7'],
  night: ['#1a2233', '#2b3448'],
  dawn: ['#e8c9b0', '#f3e2d4'],
  dusk: ['#8f7f9e', '#c9b3bd'],
}

/**
 * Sky keyframes through the day, for the calls where we know the actual hour.
 * The four buckets above are still the fallback: a scenario that says "at
 * night" has fixed the bucket without telling us which hour of the night.
 */
const SKY_HOURS: [number, string, string][] = [
  [0, '#141b2b', '#232c42'],
  [5, '#1e2740', '#3b3550'],
  [7, '#e8c9b0', '#f3e2d4'],
  [9, '#cfe0ef', '#eef3f7'],
  [15, '#cfe0ef', '#eef3f7'],
  [18, '#e6c9b4', '#f0dfd2'],
  [20, '#8f7f9e', '#c9b3bd'],
  [22, '#1a2233', '#2b3448'],
  [24, '#141b2b', '#232c42'],
]

/** Tints laid over the whole scene, so bad air reads before you parse a label. */
const WEATHER_WASH: Record<string, string> = {
  smoke: 'rgba(156,116,70,0.30)',
  fog: 'rgba(232,236,240,0.38)',
  heat: 'rgba(255,168,64,0.15)',
  cold: 'rgba(150,190,230,0.18)',
}

function mix(from: string, to: string, t: number): string {
  const channels = [1, 3, 5].map((i) => {
    const a = parseInt(from.slice(i, i + 2), 16)
    const b = parseInt(to.slice(i, i + 2), 16)
    return Math.round(a + (b - a) * t)
  })
  return `#${channels.map((c) => c.toString(16).padStart(2, '0')).join('')}`
}

function skyForHour(hour: number): [string, string] {
  const h = Math.min(Math.max(hour, 0), 24)
  let i = 0
  while (i < SKY_HOURS.length - 2 && SKY_HOURS[i + 1][0] <= h) i++
  const [start, topA, bottomA] = SKY_HOURS[i]
  const [end, topB, bottomB] = SKY_HOURS[i + 1]
  const t = end === start ? 0 : (h - start) / (end - start)
  return [mix(topA, topB, t), mix(bottomA, bottomB, t)]
}

const HAZARD_LABEL: Record<string, string> = {
  traffic: 'Traffic',
  fire: 'Fire',
  smoke: 'Smoke',
  electrical: 'Downed line',
  chemical: 'Chemical',
  weapon: 'Weapon',
  violence: 'Violence',
  animal: 'Animal',
  'unstable-vehicle': 'Unstable vehicle',
  stairs: 'Stairs',
  glass: 'Glass',
  water: 'Water',
  ice: 'Ice',
  crowd: 'Crowd',
  'confined-space': 'Confined space',
}

function Background({ scene }: { scene: SceneSpec }) {
  const [top, bottom] =
    scene.hour === null || scene.hour === undefined
      ? SKY[scene.time_of_day] ?? SKY.day
      : skyForHour(scene.hour)
  const indoors = scene.setting === 'residence' || scene.setting === 'ambulance'
  const wash = WEATHER_WASH[scene.weather]
  // Unique per instance: a bare id="sky" makes every scene on a page resolve
  // url(#sky) to whichever rendered first.
  const skyId = useId()
  return (
    <svg className="scene-bg" viewBox="0 0 400 240" preserveAspectRatio="xMidYMid slice" aria-hidden>
      <defs>
        <linearGradient id={skyId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={top} />
          <stop offset="100%" stopColor={bottom} />
        </linearGradient>
      </defs>
      <rect width="400" height="240" fill={`url(#${skyId})`} />
      <rect y="170" width="400" height="70" fill="rgba(0,0,0,0.14)" />

      {scene.setting === 'residence' && (
        <g opacity="0.5">
          <rect x="36" y="52" width="86" height="118" fill="rgba(0,0,0,0.16)" />
          <rect x="52" y="70" width="54" height="44" fill={top} opacity="0.7" />
          <rect x="290" y="88" width="74" height="82" fill="rgba(0,0,0,0.12)" />
        </g>
      )}
      {scene.setting === 'street' && (
        <g opacity="0.55">
          <rect y="186" width="400" height="54" fill="rgba(0,0,0,0.22)" />
          <path d="M0 212 H400" stroke="rgba(255,255,255,0.6)" strokeWidth="4" strokeDasharray="26 22" />
          <rect x="16" y="40" width="42" height="130" fill="rgba(0,0,0,0.14)" />
          <rect x="340" y="30" width="46" height="140" fill="rgba(0,0,0,0.14)" />
        </g>
      )}
      {scene.setting === 'ambulance' && (
        <g opacity="0.45">
          <rect x="24" y="30" width="352" height="150" rx="10" fill="rgba(0,0,0,0.18)" />
          <rect x="46" y="52" width="72" height="46" rx="4" fill={top} opacity="0.6" />
        </g>
      )}
      {(scene.setting === 'public-space' || scene.setting === 'workplace') && (
        <g opacity="0.4">
          <rect x="0" y="60" width="400" height="110" fill="rgba(0,0,0,0.1)" />
          <path d="M60 60 V170 M160 60 V170 M260 60 V170 M360 60 V170" stroke="rgba(0,0,0,0.14)" strokeWidth="8" />
        </g>
      )}
      {indoors && <rect width="400" height="240" fill="rgba(60,40,20,0.06)" />}
      {scene.weather === 'rain' && (
        <g stroke="rgba(255,255,255,0.35)" strokeWidth="1.5">
          {Array.from({ length: 40 }, (_, i) => (
            <line key={i} x1={(i * 37) % 400} y1={(i * 53) % 240} x2={((i * 37) % 400) - 6} y2={((i * 53) % 240) + 14} />
          ))}
        </g>
      )}
      {scene.weather === 'snow' && (
        <g fill="rgba(255,255,255,0.7)">
          {Array.from({ length: 46 }, (_, i) => (
            <circle key={i} cx={(i * 41) % 400} cy={(i * 67) % 240} r="2" />
          ))}
        </g>
      )}
      {wash && <rect width="400" height="240" fill={wash} />}
      {scene.weather === 'heat' && (
        <g stroke="rgba(255,255,255,0.28)" strokeWidth="1.5" fill="none">
          {Array.from({ length: 7 }, (_, i) => (
            <path key={i} d={`M40 ${168 - i * 9} q22 -6 44 0 t44 0 t44 0 t44 0`} />
          ))}
        </g>
      )}
      {scene.weather === 'cold' && (
        <g stroke="rgba(255,255,255,0.5)" strokeWidth="1.5">
          {Array.from({ length: 14 }, (_, i) => (
            <line key={i} x1={(i * 29) % 400} y1="170" x2={(i * 29) % 400} y2={178 + (i % 4) * 5} />
          ))}
        </g>
      )}
    </svg>
  )
}

export function SceneView({ scene }: { scene: SceneSpec }) {
  // 0 on mount, 1 once arrived. The spring does the push-in; each layer reads
  // the same value and moves by a different amount, which is the parallax.
  const [arrived, setArrived] = useState(false)
  useEffect(() => {
    // A frame's delay, so the spring has a 0 to start from. Setting it in the
    // same tick as the mount means React batches both and nothing moves.
    const id = requestAnimationFrame(() => setArrived(true))
    return () => cancelAnimationFrame(id)
  }, [])
  const push = useSpring(arrived ? 1 : 0, { stiffness: 42, damping: 13 })

  // The background travels least and the near chips most, as they would if the
  // camera were walking in.
  const layer = (depth: number) => ({
    transform: `scale(${1 + depth * 0.14 * (1 - push)}) translateY(${depth * 26 * (1 - push)}px)`,
    opacity: Math.min(1, 0.35 + push * 0.9),
  })

  return (
    <div className={`scene scene--${scene.setting} scene--${scene.time_of_day}`}>
      <div className="scene-layer" style={layer(0.35)}>
        <Background scene={scene} />
      </div>

      {scene.hazards.length > 0 && (
        <ul className="hazards" aria-label="Scene hazards" style={layer(1)}>
          {scene.hazards.map((h) => (
            <li key={h}>⚠ {HAZARD_LABEL[h] ?? h}</li>
          ))}
        </ul>
      )}

      <div className="scene-stage" style={layer(0.75)}>
        {scene.patient ? (
          <Patient patient={scene.patient} />
        ) : (
          <p className="scene-empty">No patient on this call.</p>
        )}
      </div>

      {scene.bystanders.length > 0 && (
        <ul className="bystanders" aria-label="Bystanders" style={layer(1.15)}>
          {scene.bystanders.map((b) => (
            <li key={b.role}>
              <span className="bystander-figure" aria-hidden />
              {b.role}
              {b.state !== 'present' && <em> · {b.state}</em>}
            </li>
          ))}
        </ul>
      )}

      {scene.equipment_visible.length > 0 && (
        <ul className="equipment" aria-label="Equipment in view" style={layer(1.15)}>
          {scene.equipment_visible.map((e) => (
            <li key={e}>{e.replace(/-/g, ' ')}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
