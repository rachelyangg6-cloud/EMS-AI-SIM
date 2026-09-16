/**
 * The only voice surface the app talks to.
 *
 * Nothing outside `voice/` touches `SpeechRecognition` or `speechSynthesis`.
 * Swapping browser speech for a local Whisper/Piper server, or a cloud voice, is
 * a one-line change in `voice/index.ts` — no phase component, session logic, or
 * grading code moves.
 */

import type { Speaker } from '../types'

export type VoicePersona = Speaker

export interface VoiceAdapter {
  /** Speech recognition is available and permitted. */
  readonly canListen: boolean
  /** Speech synthesis is available. */
  readonly canSpeak: boolean
  /** Human-readable reason `canListen` is false, for the UI to explain. */
  readonly listenBlockedReason: string

  /** Speak one line. Resolves when the audio finishes or is canceled. */
  speak(text: string, persona: VoicePersona): Promise<void>

  /**
   * Listen until `stopListening` is called. Resolves with the transcript, ''
   * if nothing was heard.
   *
   * The recognizer must not decide when the EMT has finished. Web Speech ends
   * an utterance at the first pause unless told otherwise, which truncated
   * "nasal cannula at 6 liters per minute" to "6 l" in testing. `onPartial`
   * reports the running transcript so the UI can show what is being heard
   * while it is still being said.
   */
  listen(onPartial?: (text: string) => void): Promise<string>

  /** End capture and keep what was heard — the release half of push-to-talk. */
  stopListening(): void

  /** Stop everything immediately — used for barge-in. */
  cancel(): void
}

/**
 * How each voice should sound. `rate` and `pitch` are the only levers the Web
 * Speech API gives us; the dispatcher's radio character comes from the squelch
 * bursts around the line, not from filtering the speech itself (see BrowserVoice).
 */
export const VOICE_SHAPE: Record<string, { rate: number; pitch: number }> = {
  dispatcher: { rate: 1.15, pitch: 0.9 },
  patient: { rate: 0.92, pitch: 1.05 },
  bystander: { rate: 1.1, pitch: 1.15 },
  narrator: { rate: 1.0, pitch: 1.0 },
  sim: { rate: 1.05, pitch: 1.0 },
  emt: { rate: 1.0, pitch: 1.0 },
}

/** A no-op adapter, for when voice is off or unsupported. */
export const silentVoice: VoiceAdapter = {
  canListen: false,
  canSpeak: false,
  listenBlockedReason: 'Voice is off.',
  async speak() {},
  async listen() {
    return ''
  },
  stopListening() {},
  cancel() {},
}
