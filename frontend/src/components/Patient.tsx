import type { PatientSpec } from '../types'
import { breathCurve, useBlink, useClock, useSpring } from '../motion'
import { reducedMotion } from '../store'

/**
 * One parameterized figure, built out of blocks like a minifigure. Every visible
 * property is driven by the SceneSpec, which is derived from EMT-vetted text —
 * the picture cannot say something the scenario does not.
 *
 * The chest-rise animation period *is* the respiratory rate: at RR 36 the chest
 * completes a cycle every 60/36 = 1.67s. That is the point of the whole thing.
 * The *shape* of that cycle is now an asymmetric respiratory curve — active
 * inspiration, slower passive expiration, then an end-expiratory pause — rather
 * than a symmetric CSS keyframe, which had no pause and read as a rectangle
 * being pulsed. The period is untouched; only the shape changed.
 *
 * **The figure is never completely still unless the patient is.** A slow
 * shoulder sway, an occasional blink and a little head drift run off a shared
 * clock. A frozen scene reads as a broken renderer, and a patient who is
 * genuinely motionless should be motionless because they are unresponsive.
 *
 * **Skin color lives on the head and hands.** Those are the parts a minifigure
 * leaves uncovered, and they are also where an EMT actually reads color. The
 * torso and legs keep a fixed uniform color so that a change of skin tone is
 * the only thing on the figure that ever changes hue.
 */

const SKIN: Record<string, string> = {
  cyanotic: '#8098c8',
  mottled: '#b58a92',
  pale: '#ecdfd4',
  flushed: '#d98f76',
  diaphoretic: '#e0b79b',
  normal: '#e3b492',
}

const TORSO_COLOUR = '#4a5b78'
/** A shade off the torso, so an arm reads as an arm and not as more chest. */
const ARM_COLOUR = '#3d4c66'
const LEG_COLOUR = '#333e56'

/** Used only when the scenario states no rate — a still figure would read as apnoeic. */
const RESTING_RR = 14

const LID: Record<string, number> = {
  alert: 0,
  confused: 0.15,
  verbal: 0.5,
  drowsy: 0.6,
  painful: 0.85,
  unresponsive: 1,
}

/** How far the torso expands on each breath. */
const EXCURSION: Record<string, number> = {
  'accessory-muscle-use': 0.075,
  labored: 0.065,
  obstructed: 0.05,
  normal: 0.04,
  shallow: 0.018,
  agonal: 0.09,
  apneic: 0,
}

const POSE: Record<string, { rotate: number; x: number; y: number; legs: 'bent' | 'straight' }> = {
  tripod: { rotate: -12, x: 0, y: 0, legs: 'bent' },
  slumped: { rotate: 14, x: 4, y: 8, legs: 'bent' },
  seated: { rotate: 0, x: 0, y: 0, legs: 'bent' },
  supine: { rotate: -90, x: -14, y: 30, legs: 'straight' },
  prone: { rotate: 90, x: 14, y: 30, legs: 'straight' },
  ambulatory: { rotate: 0, x: 0, y: -10, legs: 'straight' },
}

export function Patient({ patient }: { patient: PatientSpec }) {
  const pose = POSE[patient.posture ?? 'seated'] ?? POSE.seated
  const skin = SKIN[patient.skin ?? 'normal'] ?? SKIN.normal
  const lid = LID[patient.loc ?? 'alert'] ?? 0
  const excursion = EXCURSION[patient.effort ?? 'normal'] ?? EXCURSION.normal

  const rate = patient.rr ?? RESTING_RR
  const period = 60 / Math.max(4, rate)
  const breathing = excursion > 0 && !reducedMotion
  const fade = { transition: reducedMotion ? undefined : 'fill 1200ms ease' }

  // Tripod braces the arms forward onto the knees; otherwise they hang.
  const armAngle = patient.posture === 'tripod' ? 26 : 6
  const legHeight = pose.legs === 'bent' ? 26 : 40

  // ── motion ────────────────────────────────────────────────────────────────
  // The clock runs while anything on the figure is moving. An apneic patient
  // under reduced motion subscribes to nothing at all.
  const alive = !reducedMotion && (breathing || lid < 1)
  const seconds = useClock(alive)

  const rise = breathing ? breathCurve((seconds % period) / period, patient.effort === 'agonal') : 0
  const chestScale = 1 + excursion * rise

  // Sub-pixel idle life at two incommensurate periods, so it never repeats
  // visibly. Scaled by responsiveness: an unresponsive patient does not sway.
  const life = 1 - lid
  const sway = life * 0.55 * Math.sin(seconds * 0.61)
  const drift = life * 0.9 * Math.sin(seconds * 0.37 + 1.2)
  const lidOpen = useBlink(seconds, lid < 0.35)

  // Pose and limbs arrive on springs rather than on one shared 900ms ease, so
  // the body settles instead of every part landing at the same instant. The
  // torso is heavier than the arms, so it is the slower of the two.
  const rotate = useSpring(pose.rotate, { stiffness: 90 })
  const shiftX = useSpring(pose.x, { stiffness: 90 })
  const shiftY = useSpring(pose.y, { stiffness: 90 })
  const arm = useSpring(armAngle, { stiffness: 150 })
  const headTilt = useSpring(lid * 14, { stiffness: 120 })

  return (
    <svg
      viewBox="0 0 200 210"
      className="patient"
      role="img"
      aria-label={[
        patient.posture ?? 'position not stated',
        patient.skin ? `${patient.skin} skin` : 'skin color not stated',
        patient.effort ?? '',
        patient.loc ?? '',
        patient.rr ? `respiratory rate ${patient.rr}` : '',
      ]
        .filter(Boolean)
        .join(', ')}
    >
      <g transform={`translate(${shiftX + drift} ${shiftY}) rotate(${rotate + sway} 100 120)`}>
        {/* legs — hip block, then two blocks below it */}
        <rect x="68" y="146" width="64" height="17" rx="3" fill={LEG_COLOUR} />
        <rect x="70" y="163" width="27" height={legHeight} rx="3" fill={LEG_COLOUR} />
        <rect x="103" y="163" width="27" height={legHeight} rx="3" fill={LEG_COLOUR} />
        {/* feet */}
        <rect x="66" y={163 + legHeight - 6} width="33" height="9" rx="3" fill="#232c3e" />
        <rect x="101" y={163 + legHeight - 6} width="33" height="9" rx="3" fill="#232c3e" />

        {/* arms — each is one block plus the C-clip hand, rotated at the shoulder */}
        <g transform={`rotate(${arm} 68 96)`}>
          <rect x="54" y="92" width="21" height="48" rx="8" fill={ARM_COLOUR} />
          <rect x="55" y="133" width="19" height="18" rx="8" fill={skin} style={fade} />
        </g>
        <g transform={`rotate(${-arm} 132 96)`}>
          <rect x="125" y="92" width="21" height="48" rx="8" fill={ARM_COLOUR} />
          <rect x="126" y="133" width="19" height="18" rx="8" fill={skin} style={fade} />
        </g>

        {/* torso — the trapezoid that breathes */}
        {/* The waist, so the chest rises off a fixed belt line. */}
        <g
          className="chest"
          transform={breathing ? `translate(0 ${147 * (1 - chestScale)}) scale(1 ${chestScale})` : undefined}
        >
          <path
            d="M76 88 H124 A4 4 0 0 1 128 92 L133 142 A4 4 0 0 1 129 147 H71 A4 4 0 0 1 67 142 L72 92 A4 4 0 0 1 76 88 Z"
            fill={TORSO_COLOUR}
          />
          {/* accessory muscle use is visible at the neck and between the ribs */}
          {(patient.effort === 'accessory-muscle-use' || patient.effort === 'labored') && (
            <path
              d="M88 96 L92 112 M112 96 L108 112"
              stroke="rgba(0,0,0,0.3)"
              strokeWidth="4"
              strokeLinecap="round"
            />
          )}
        </g>

        {/* neck + head */}
        <rect x="88" y="78" width="24" height="12" rx="2" fill={skin} style={fade} />
        <g transform={`rotate(${headTilt} 100 54) translate(${drift * 0.6} 0)`}>
          {/* the stud on top */}
          <rect x="90" y="14" width="20" height="9" rx="3" fill={skin} style={fade} />
          <rect x="66" y="22" width="68" height="60" rx="12" fill={skin} style={fade} />
          {/* eyes: the lid closes as responsiveness falls */}
          <g>
            <ellipse cx="86" cy="48" rx="5" ry={5 * (1 - lid) * lidOpen} fill="#2b2b33" />
            <ellipse cx="114" cy="48" rx="5" ry={5 * (1 - lid) * lidOpen} fill="#2b2b33" />
          </g>
          {/* Dusky lips read as cyanosis even on a small screen. The curve bows
              *upward* — a mouth that bows down reads as a smile, which is a
              grotesque thing to put on a patient in respiratory failure. */}
          <path
            d="M87 68 Q100 62 113 68"
            stroke={patient.skin === 'cyanotic' ? '#4d6fae' : '#b46a5e'}
            strokeWidth="4"
            strokeLinecap="round"
            fill="none"
            style={{ transition: 'stroke 1200ms ease' }}
          />
          {patient.skin === 'diaphoretic' && (
            <g fill="rgba(150,200,255,0.85)">
              <circle cx="76" cy="34" r="2.6" />
              <circle cx="124" cy="38" r="2.4" />
              <circle cx="100" cy="27" r="2.2" />
            </g>
          )}
        </g>
      </g>
    </svg>
  )
}
