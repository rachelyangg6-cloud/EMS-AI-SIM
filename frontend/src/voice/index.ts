/**
 * The one-line swap.
 *
 * Change `voice` below to `new ServerVoice()` and the whole app moves to
 * server-side speech. Nothing else in the codebase names a speech API.
 */

import { BrowserVoice } from './BrowserVoice'
import { silentVoice, type VoiceAdapter } from './VoiceAdapter'

export { ServerVoice } from './ServerVoice'
export { silentVoice, VOICE_SHAPE } from './VoiceAdapter'
export type { VoiceAdapter, VoicePersona } from './VoiceAdapter'

/** Browser speech where available, a no-op adapter where it isn't. */
export const voice: VoiceAdapter =
  typeof window === 'undefined' ? silentVoice : new BrowserVoice()
