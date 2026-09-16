/**
 * Web Speech API adapter — free, client-side, no network, works offline.
 *
 * **On the dispatcher's radio effect.** The plan calls for a Web Audio bandpass
 * filter on the dispatcher's voice. That is not possible here: `speechSynthesis`
 * exposes no `MediaStream` and no node you can route into an `AudioContext`, so
 * synthesized speech cannot be filtered client-side at all. What we can do is
 * shape the delivery (a faster, lower voice) and bracket the line with the
 * synthesized squelch bursts from `audio.ts`. Real filtering arrives with
 * `ServerVoice`, where a WAV comes back and there *is* an audio graph.
 *
 * **On recognition support.** `SpeechRecognition` is prefixed and unevenly
 * implemented. iOS Safari has had `webkitSpeechRecognition` since 14.5, but it
 * requires a user gesture and mic permission and can fail per-device. Every
 * failure path here degrades to typing rather than blocking the call — the
 * transcript is always on screen, which is also the answer for a noisy bay.
 */

import { audio } from '../audio'
import { VOICE_SHAPE, type VoiceAdapter, type VoicePersona } from './VoiceAdapter'

type RecognitionCtor = new () => SpeechRecognitionLike

interface RecognitionResultLike extends ArrayLike<{ transcript: string }> {
  isFinal: boolean
}

interface SpeechRecognitionLike {
  lang: string
  interimResults: boolean
  maxAlternatives: number
  continuous: boolean
  start(): void
  stop(): void
  abort(): void
  onresult: ((event: {
    resultIndex: number
    results: ArrayLike<RecognitionResultLike>
  }) => void) | null
  onerror: ((event: { error: string }) => void) | null
  onend: (() => void) | null
}

const recognitionCtor = (): RecognitionCtor | null => {
  const w = window as unknown as {
    SpeechRecognition?: RecognitionCtor
    webkitSpeechRecognition?: RecognitionCtor
  }
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null
}

/**
 * macOS/iOS ship dozens of novelty voices in the `en` list, alphabetically ahead
 * of most real ones. Taking the first four English voices gave the bystander
 * "Bad News" and the narrator "Bahh" — a sheep bleat — on a respiratory-failure
 * call. These are excluded by name; anything unrecognised is assumed real.
 */
const NOVELTY = new Set([
  'Albert', 'Bad News', 'Bahh', 'Bells', 'Boing', 'Bubbles', 'Cellos',
  'Deranged', 'Good News', 'Jester', 'Organ', 'Pipe Organ', 'Superstar',
  'Trinoids', 'Whisper', 'Wobble', 'Zarvox', 'Junior', 'Ralph', 'Fred',
  'Kathy', 'Princess', 'Bruce', 'Agnes', 'Hysterical', 'Grandma', 'Grandpa',
  'Rocko', 'Sandy', 'Shelley', 'Eddy', 'Flo', 'Reed',
])

const isPlainSpeech = (voice: SpeechSynthesisVoice) =>
  // Localised variants read as "Eddy (English (United States))".
  !NOVELTY.has(voice.name.replace(/\s*\(.*\)$/, '').trim())

/** Distinct voices per persona, chosen deterministically from what's installed. */
function pickVoices(): Record<string, SpeechSynthesisVoice | undefined> {
  const all = window.speechSynthesis?.getVoices?.() ?? []
  const english = all.filter((v) => v.lang.toLowerCase().startsWith('en'))
  const usable = english.filter(isPlainSpeech)
  // The platform default is the safest voice on the machine — lead with it.
  const pool = (usable.length ? usable : english.length ? english : all).slice()
  pool.sort((a, b) => Number(b.default) - Number(a.default))

  const at = (i: number) => (pool.length ? pool[i % pool.length] : undefined)
  return {
    dispatcher: at(0),
    patient: at(1),
    bystander: at(2),
    narrator: at(0),
    sim: at(0),
  }
}

export class BrowserVoice implements VoiceAdapter {
  private voices: Record<string, SpeechSynthesisVoice | undefined> = {}
  private recognition: SpeechRecognitionLike | null = null
  /** Final segments so far, accumulated across recognizer restarts. */
  private finalText = ''
  /** True once push-to-talk is released, so `onend` resolves instead of restarting. */
  private releasing = false
  /** Set when the browser refuses the microphone. Unlike a missing API this is
   *  invisible — `canListen` stays true — so it is tracked to be reported. */
  private micBlocked = false

  constructor() {
    if (window.speechSynthesis) {
      this.voices = pickVoices()
      // Voice list loads asynchronously in most browsers.
      window.speechSynthesis.onvoiceschanged = () => {
        this.voices = pickVoices()
      }
    }
  }

  get canSpeak() {
    return typeof window !== 'undefined' && !!window.speechSynthesis
  }

  get canListen() {
    return recognitionCtor() !== null
  }

  get listenBlockedReason() {
    if (!this.canListen) return 'This browser has no speech recognition — type instead.'
    if (this.micBlocked) {
      return 'Microphone blocked — allow access in your browser, then try again. You can type instead.'
    }
    return ''
  }

  async speak(text: string, persona: VoicePersona): Promise<void> {
    if (!this.canSpeak || !text.trim()) return

    // The radio effect, such as it is: squelch in, squelch out.
    if (persona === 'dispatcher') audio.squelch()

    // iOS parks the speech queue in a paused state when the page loses and
    // regains focus, and a queue that is paused swallows `speak()` without ever
    // reporting back. Harmless everywhere else — resuming a queue that is
    // already running is a no-op.
    window.speechSynthesis.resume()

    await new Promise<void>((resolve) => {
      const utterance = new SpeechSynthesisUtterance(text)
      const shape = VOICE_SHAPE[persona] ?? VOICE_SHAPE.narrator
      utterance.rate = shape.rate
      utterance.pitch = shape.pitch
      const voice = this.voices[persona]
      if (voice) utterance.voice = voice
      // Resolve on error too — a failed line must never stall the call.
      utterance.onend = () => resolve()
      utterance.onerror = () => resolve()
      window.speechSynthesis.speak(utterance)
    })

    if (persona === 'dispatcher') audio.squelch()
  }

  /**
   * Listen until the EMT releases push-to-talk — never until the recognizer
   * decides they have finished.
   *
   * Web Speech ends an utterance at the first pause it detects. With
   * `continuous = false` that truncated "give supplemental oxygen with a nasal
   * cannula at 6 liters per minute" to "…at 6 l", because the small hesitation
   * before "liters" read as the end of the sentence. Three changes stop that:
   *
   *   - `continuous = true`, so a pause is a pause rather than a full stop;
   *   - `onend` restarts capture while the EMT is still holding, because
   *     browsers end a continuous session on their own timers too; and
   *   - final segments accumulate across those restarts instead of the last
   *     one replacing everything before it.
   *
   * The interim tail is kept as well, so releasing mid-word still yields what
   * had been heard rather than dropping it.
   */
  listen(onPartial?: (text: string) => void): Promise<string> {
    const Ctor = recognitionCtor()
    if (!Ctor) return Promise.resolve('')

    // Barge-in: the EMT talking over the sim stops the sim.
    window.speechSynthesis?.cancel()

    return new Promise<string>((resolve) => {
      let settled = 0
      let interim = ''
      const finish = (recognition: SpeechRecognitionLike | null) => {
        recognition?.abort()
        this.recognition = null
        this.releasing = false
        resolve([this.finalText, interim].join(' ').replace(/\s+/g, ' ').trim())
      }

      this.finalText = ''
      this.releasing = false
      // Cleared each attempt, so granting permission recovers without a reload.
      this.micBlocked = false

      const start = () => {
        const recognition = new Ctor()
        this.recognition = recognition
        recognition.lang = 'en-US'
        recognition.interimResults = true
        recognition.maxAlternatives = 1
        recognition.continuous = true

        recognition.onresult = (event) => {
          interim = ''
          for (let i = event.resultIndex; i < event.results.length; i += 1) {
            const result = event.results[i]
            if (result.isFinal) this.finalText += ` ${result[0].transcript}`
            else interim += ` ${result[0].transcript}`
          }
          onPartial?.([this.finalText, interim].join(' ').replace(/\s+/g, ' ').trim())
        }

        // A recognition error is a miss, not a crash — fall through to typing.
        // But a *denied* permission is not a miss: it never recovers on its own,
        // and discarding it left the EMT pressing a button that did nothing and
        // said nothing. `canListen` is true in that case — the API is present,
        // it is the permission that is not — so this is the only place it can be
        // caught.
        recognition.onerror = (event) => {
          if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
            this.micBlocked = true
          }
        }

        recognition.onend = () => {
          // Released, or the browser gave up twice in a row: hand back what we
          // have. Otherwise the EMT is still speaking, so keep listening.
          if (this.releasing || settled > 8) {
            finish(null)
            return
          }
          settled += 1
          try {
            start()
          } catch {
            finish(null)
          }
        }

        recognition.start()
      }

      try {
        start()
      } catch {
        finish(null)
      }
    })
  }

  stopListening() {
    // The flag has to be set before stop(): onend fires synchronously in some
    // browsers, and without it the handler would restart capture instead of
    // resolving.
    this.releasing = true
    this.recognition?.stop()
  }

  cancel() {
    window.speechSynthesis?.cancel()
    this.releasing = true
    this.recognition?.abort()
    this.recognition = null
  }
}
