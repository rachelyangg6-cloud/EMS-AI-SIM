/**
 * Server-side speech — the same interface, a different backend.
 *
 * The endpoints are stubbed on the server (they return 501) so the wire contract
 * is fixed now rather than negotiated later. Nothing else in the app changes
 * when this replaces `BrowserVoice`.
 *
 * This is also where the dispatcher's radio filter becomes real: a WAV comes
 * back, so it decodes into an `AudioBuffer` and routes through a bandpass —
 * which is exactly what `speechSynthesis` makes impossible in `BrowserVoice`.
 */

import { VOICE_SHAPE, type VoiceAdapter, type VoicePersona } from './VoiceAdapter'

/** Telephone/radio band. Everything outside it is what makes speech sound "radio". */
const RADIO_BAND = { low: 400, high: 2600 }

export class ServerVoice implements VoiceAdapter {
  private context: AudioContext | null = null
  private playing: AudioBufferSourceNode | null = null
  private recorder: MediaRecorder | null = null

  get canSpeak() {
    return true
  }

  get canListen() {
    return typeof navigator !== 'undefined' && !!navigator.mediaDevices?.getUserMedia
  }

  get listenBlockedReason() {
    return this.canListen ? '' : 'This browser cannot record audio — type instead.'
  }

  private audioContext(): AudioContext {
    if (!this.context) this.context = new AudioContext()
    if (this.context.state === 'suspended') void this.context.resume()
    return this.context
  }

  async speak(text: string, persona: VoicePersona): Promise<void> {
    if (!text.trim()) return
    const shape = VOICE_SHAPE[persona] ?? VOICE_SHAPE.narrator

    const response = await fetch('/api/tts', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ text, persona, rate: shape.rate, pitch: shape.pitch }),
    })
    if (!response.ok) throw new Error(`/api/tts ${response.status}`)

    const ctx = this.audioContext()
    const buffer = await ctx.decodeAudioData(await response.arrayBuffer())
    const source = ctx.createBufferSource()
    source.buffer = buffer

    if (persona === 'dispatcher') {
      // The radio effect BrowserVoice cannot do: band-limit the speech itself.
      const low = ctx.createBiquadFilter()
      low.type = 'highpass'
      low.frequency.value = RADIO_BAND.low
      const high = ctx.createBiquadFilter()
      high.type = 'lowpass'
      high.frequency.value = RADIO_BAND.high
      const drive = ctx.createWaveShaper()
      drive.curve = squashCurve()
      source.connect(low).connect(high).connect(drive).connect(ctx.destination)
    } else {
      source.connect(ctx.destination)
    }

    this.playing = source
    await new Promise<void>((resolve) => {
      source.onended = () => {
        this.playing = null
        resolve()
      }
      source.start()
    })
  }

  async listen(onPartial?: (text: string) => void): Promise<string> {
    if (!this.canListen) return ''
    this.playing?.stop() // barge-in

    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const recorder = new MediaRecorder(stream)
    this.recorder = recorder
    const chunks: Blob[] = []

    const recorded = new Promise<Blob>((resolve) => {
      recorder.ondataavailable = (event) => chunks.push(event.data)
      recorder.onstop = () => resolve(new Blob(chunks, { type: recorder.mimeType }))
    })
    recorder.start()
    // The caller stops us via cancel(); this resolves when they do.
    const blob = await recorded
    stream.getTracks().forEach((track) => track.stop())
    this.recorder = null

    const form = new FormData()
    form.append('audio', blob, 'utterance.webm')
    const response = await fetch('/api/stt', { method: 'POST', body: form })
    if (!response.ok) throw new Error(`/api/stt ${response.status}`)
    const data = (await response.json()) as { text?: string }
    const text = (data.text ?? '').trim()
    // Server transcription is not streamed, so there is one "partial" and it is
    // the final text. Reported anyway so the UI has a single code path.
    onPartial?.(text)
    return text
  }

  stopListening() {
    if (this.recorder?.state === 'recording') this.recorder.stop()
  }

  cancel() {
    this.playing?.stop()
    this.playing = null
    if (this.recorder?.state === 'recording') this.recorder.stop()
  }
}

/** Gentle saturation — the compressed, slightly clipped sound of a radio. */
function squashCurve(): Float32Array<ArrayBuffer> {
  const n = 1024
  const curve = new Float32Array(new ArrayBuffer(1024 * 4))
  for (let i = 0; i < n; i++) {
    const x = (i * 2) / n - 1
    curve[i] = Math.tanh(x * 2.2)
  }
  return curve
}
