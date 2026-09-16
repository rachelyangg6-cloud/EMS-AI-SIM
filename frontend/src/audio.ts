/**
 * Web Audio cues — synthesized, so there are no files and nothing to license.
 *
 * Browsers refuse to start an AudioContext until the user has interacted with
 * the page, so the context is created lazily on the first cue after a click.
 */

import type { Phase } from './types'

let ctx: AudioContext | null = null
let enabled = true

function context(): AudioContext | null {
  if (!enabled) return null
  if (!ctx) {
    const Ctor = window.AudioContext ?? (window as never as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
    if (!Ctor) return null
    ctx = new Ctor()
  }
  if (ctx.state === 'suspended') void ctx.resume()
  return ctx
}

function tone(freq: number, start: number, duration: number, gain = 0.12, type: OscillatorType = 'sine') {
  const audioCtx = context()
  if (!audioCtx) return
  const osc = audioCtx.createOscillator()
  const amp = audioCtx.createGain()
  osc.type = type
  osc.frequency.value = freq
  // Ramp the envelope so the cue does not click.
  amp.gain.setValueAtTime(0, audioCtx.currentTime + start)
  amp.gain.linearRampToValueAtTime(gain, audioCtx.currentTime + start + 0.02)
  amp.gain.setValueAtTime(gain, audioCtx.currentTime + start + duration - 0.04)
  amp.gain.linearRampToValueAtTime(0, audioCtx.currentTime + start + duration)
  osc.connect(amp).connect(audioCtx.destination)
  osc.start(audioCtx.currentTime + start)
  osc.stop(audioCtx.currentTime + start + duration)
}

/** Short burst of filtered noise — the squelch tail on a radio transmission. */
function squelch(start = 0) {
  const audioCtx = context()
  if (!audioCtx) return
  const frames = audioCtx.sampleRate * 0.12
  const buffer = audioCtx.createBuffer(1, frames, audioCtx.sampleRate)
  const data = buffer.getChannelData(0)
  for (let i = 0; i < frames; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / frames)
  const source = audioCtx.createBufferSource()
  source.buffer = buffer
  const band = audioCtx.createBiquadFilter()
  band.type = 'bandpass'
  band.frequency.value = 1800
  const amp = audioCtx.createGain()
  amp.gain.value = 0.05
  source.connect(band).connect(amp).connect(audioCtx.destination)
  source.start(audioCtx.currentTime + start)
}

export const audio = {
  setEnabled(value: boolean) {
    enabled = value
    if (!value && ctx) void ctx.suspend()
  },

  get enabled() {
    return enabled
  },

  /** One squelch burst — the tail of a radio transmission. */
  squelch() {
    squelch()
  },

  /** The two-tone alert that opens every call. */
  toneOut() {
    tone(660, 0, 0.45, 0.1, 'square')
    tone(880, 0.5, 0.45, 0.1, 'square')
    squelch(1.0)
  },

  /** One monitor blip, played when a vital sign first appears. */
  beep() {
    tone(1046, 0, 0.09, 0.07, 'sine')
  },

  cue(phase: Phase) {
    if (phase === 'TONE_OUT') this.toneOut()
    if (phase === 'OBSERVE') this.beep()
    if (phase === 'END_OF_CALL') squelch()
  },
}
