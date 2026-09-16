import { useSyncExternalStore } from 'react'

import { api, token } from './api'
import { audio } from './audio'
import { voice, type VoicePersona } from './voice'
import type { CorpusStats, Grade, HistoryDetail, HistoryEntry, Phase, SceneSpec, SimEvent, ReviewResult, StartResponse, TurnResponse, User, Vitals } from './types'

/**
 * One store, no Redux.
 *
 * The server sends a whole burst of events per request — the tone-out through
 * the size-up prompt arrives in a single response. Playing them back one at a
 * time on a timer is what turns a JSON array into a call, so the queue below is
 * the heart of this file.
 */

export const reducedMotion =
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/** How long each phase holds the screen, in ms. */
const DWELL: Partial<Record<Phase, number>> = {
  TONE_OUT: 3600,
  EN_ROUTE: 4000,
  ARRIVAL: 1600,
  SCENE_NARRATION: 3200,
  ANSWER: 2600,
  OBSERVE: 2600,
  RESULT: 1600,
  END_OF_CALL: 1400,
  DEBRIEF: 300,
}

const dwell = (phase: Phase) => (reducedMotion ? 350 : (DWELL[phase] ?? 1200))

const LLM_KEY = 'ems.llm'

/**
 * Whether Claude plays the call, read once at load.
 *
 * There is no control for this on screen, and that is the point: for a trainee
 * "should the patient talk back" is not a question with a wrong answer, and the
 * checkbox that used to ask it only ever produced the confusion that it was
 * asking whether the app used an LLM at all. It always does now.
 *
 * It stays switchable for the people running the simulator, because a
 * deterministic call is the one you can reproduce, diagnose and run for free:
 * load `?llm=off` once and it sticks, `?llm=on` puts it back.
 */
function llmEnabled(): boolean {
  if (typeof window === 'undefined') return true
  const asked = new URLSearchParams(window.location.search).get('llm')
  if (asked === 'off' || asked === 'on') {
    try {
      window.localStorage.setItem(LLM_KEY, asked)
    } catch {
      /* private browsing: honor it for this page load and move on */
    }
    return asked === 'on'
  }
  try {
    return window.localStorage.getItem(LLM_KEY) !== 'off'
  } catch {
    return true
  }
}

export interface State {
  screen: 'landing' | 'setup' | 'call' | 'debrief' | 'history' | 'profile' | 'guide' | 'features'
  user: User | null
  /** True while the stored token is being exchanged for a profile on load.
   *  Without it the landing page flashes up before the rehydrate lands. */
  restoring: boolean
  /** Past calls, and the one being read. Loaded on demand. */
  history: HistoryEntry[]
  historyDetail: HistoryDetail | null
  /** Counts for the Features page. Fetched once, then kept — the corpus
   *  cannot change without a deploy, which reloads the page anyway. */
  corpus: CorpusStats | null
  sessionId: string | null
  scenarioId: string
  /** 'generated' = an unreviewed draft; the debrief offers a verdict. */
  mode: 'vetted' | 'generated'
  /** Whether Claude voices the call and writes the debrief. On by default —
   *  see `llmEnabled` for the switch and why it is not on screen. */
  llmOn: boolean
  /** Set once this call's draft has been judged, so the panel stops asking. */
  reviewed: ReviewResult | null
  difficulty: string
  scene: SceneSpec | null
  phase: Phase
  serverAwaiting: boolean
  done: boolean
  vitals: Vitals
  vitalsGenerated: string[]
  transcript: SimEvent[]
  queue: SimEvent[]
  current: SimEvent | null
  grade: Grade | null
  busy: boolean
  error: string | null
  /** Voice output/input. Off until the EMT asks for it — mics need a gesture. */
  voiceOn: boolean
  listening: boolean
  /** Running transcript while push-to-talk is held, so the EMT can see
   *  what is being heard rather than discovering it in the transcript. */
  heardSoFar: string
  /** The nudge for this turn, and whether the trainee wants to see it. */
  hint: string | null
  hintsOn: boolean
  /** Exactly what started this call, so it can be started again. Holds the
   *  *resolved* scenario id, never the empty box that was typed — replaying a
   *  blank id would deal a different call and look like a replay. */
  lastStart: StartArgs | null
}

export interface StartArgs {
  level: string
  scenarioId: string
  timeOfDay: string
  mode: 'vetted' | 'generated'
}

const initial: State = {
  screen: 'landing',
  user: null,
  restoring: false,
  history: [],
  historyDetail: null,
  corpus: null,
  sessionId: null,
  scenarioId: '',
  mode: 'vetted',
  llmOn: llmEnabled(),
  reviewed: null,
  difficulty: '',
  scene: null,
  phase: 'TONE_OUT',
  serverAwaiting: false,
  done: false,
  vitals: {},
  vitalsGenerated: [],
  transcript: [],
  queue: [],
  current: null,
  grade: null,
  busy: false,
  error: null,
  voiceOn: false,
  listening: false,
  heardSoFar: '',
  hint: null,
  hintsOn: false,
  lastStart: null,
}

let state = initial
const listeners = new Set<() => void>()
let timer: number | undefined

function set(patch: Partial<State>) {
  state = { ...state, ...patch }
  listeners.forEach((l) => l())
}

export function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export const getState = () => state
export const useStore = <T,>(select: (s: State) => T): T =>
  useSyncExternalStore(subscribe, () => select(state))

/** True only when the prompt is actually on screen and the queue has drained. */
export const canSpeak = (s: State) =>
  s.serverAwaiting && s.queue.length === 0 && !s.busy && !s.done

// ── cinematic playback ──────────────────────────────────────────────────────

/** Bumped by skip()/enqueue() so a speech promise from an abandoned run is ignored. */
let playToken = 0

/** Rough milliseconds to say `text` aloud, plus a wide allowance. */
const speakingTime = (text: string) =>
  Math.min(60_000, 2_000 + text.split(/\s+/).length * 600)

/**
 * Speak a line, but never wait forever for the browser to admit it finished.
 *
 * `BrowserVoice.speak` resolves from `onend`/`onerror`, and iOS Safari fires
 * neither when it declines to speak — which it does whenever `speak()` is
 * called outside a user gesture, as it is here, one `fetch` after the tap that
 * started the call. The promise never settled, so playback stopped on the line
 * it was on and the call sat on the tone-out with the input disabled. That is
 * the freeze; it needs no bug in the voice adapter to happen again, which is
 * why the guard lives out here rather than inside one implementation of it.
 *
 * On timeout the utterance is canceled before moving on, so a line that starts
 * speaking late cannot talk over the one after it.
 */
async function spokenOrTimedOut(text: string, speaker: VoicePersona) {
  let watchdog: number | undefined
  const expired = new Promise<'timeout'>((resolve) => {
    watchdog = window.setTimeout(() => resolve('timeout'), speakingTime(text))
  })
  try {
    if ((await Promise.race([voice.speak(text, speaker), expired])) === 'timeout') {
      voice.cancel()
    }
  } finally {
    window.clearTimeout(watchdog)
  }
}

async function playNext() {
  const token = playToken
  const [next, ...rest] = state.queue
  if (!next) return
  audio.cue(next.phase)
  set({ current: next, queue: rest, transcript: [...state.transcript, next] })
  if (!rest.length) return

  // With voice on, the line's own length is the dwell — a fixed timer would
  // either talk over itself or leave dead air.
  if (state.voiceOn && next.text && !next.awaiting_input) {
    try {
      await spokenOrTimedOut(next.text, next.speaker)
    } catch {
      /* a voice that fails is a silent call, not a broken one */
    }
    if (token === playToken) void playNext()
    return
  }
  timer = window.setTimeout(playNext, dwell(next.phase))
}

function enqueue(events: SimEvent[]) {
  window.clearTimeout(timer)
  playToken += 1
  set({ queue: events, current: null })
  void playNext()
}

/** Jump past the cinematic opening — the plan calls for en-route to be skippable. */
export function skip() {
  if (!state.queue.length) return
  window.clearTimeout(timer)
  playToken += 1
  voice.cancel()
  const last = state.queue[state.queue.length - 1]
  set({
    transcript: [...state.transcript, ...state.queue],
    queue: [],
    current: last,
  })
}

// ── actions ─────────────────────────────────────────────────────────────────

function absorb(data: TurnResponse) {
  set({
    phase: data.phase,
    serverAwaiting: data.awaiting_input,
    done: data.done,
    vitals: data.vitals,
    vitalsGenerated: data.vitals_generated ?? [],
    hint: data.hint ?? null,
    grade: data.grade ?? state.grade,
    busy: false,
  })
  enqueue(data.events)
}

async function guard(work: () => Promise<void>) {
  set({ busy: true, error: null })
  try {
    await work()
  } catch (e) {
    set({ busy: false, error: e instanceof Error ? e.message : String(e) })
  }
}

export const actions = {
  async logIn(username: string, password: string) {
    await guard(async () => {
      const { token: issued, user } = await api.login(username.trim(), password)
      token.set(issued)
      set({ user, screen: 'setup', busy: false })
    })
  },

  async logOut() {
    // Revoke server-side before forgetting it locally, or the token stays
    // valid for twelve hours in whatever else has a copy.
    try {
      await api.logout()
    } catch {
      /* a token the server has already forgotten is still logged out */
    }
    token.clear()
    window.clearTimeout(timer)
    playToken += 1
    voice.cancel()
    set({ ...initial })
  },

  /** On load: turn a stored token back into a profile, so a refresh does not
   *  sign the EMT out. A token that has expired just lands on the landing
   *  page — `api` clears it and calls the handler registered below. */
  async restore() {
    if (!token.get()) return
    set({ restoring: true })
    try {
      set({ user: await api.me(), screen: 'setup', restoring: false })
    } catch {
      set({ user: null, screen: 'landing', restoring: false })
    }
  },

  async saveProfile(body: {
    name?: string
    email?: string
    scope_level?: string
    years_experience?: number
  }) {
    await guard(async () => {
      set({ user: await api.updateProfile(body), screen: 'setup', busy: false })
    })
  },

  async openHistory() {
    set({ screen: 'history', historyDetail: null })
    await guard(async () => {
      const { sessions } = await api.history()
      set({ history: sessions, busy: false })
    })
  },

  async openHistoryEntry(sessionId: string) {
    await guard(async () => {
      set({ historyDetail: await api.historyDetail(sessionId), busy: false })
    })
  },

  closeHistoryEntry() {
    set({ historyDetail: null })
  },

  showProfile() {
    set({ screen: 'profile' })
  },

  showGuide() {
    set({ screen: 'guide' })
  },

  /** The Features page. Its prose stands alone, so the screen is shown first
   *  and the numbers land when they land — a failed fetch leaves an error line
   *  rather than a blank page. Cached in the store, so coming back is instant. */
  async showFeatures() {
    set({ screen: 'features' })
    if (state.corpus) return
    await guard(async () => {
      set({ corpus: await api.corpus(), busy: false })
    })
  },

  backToMenu() {
    set({ screen: 'setup', historyDetail: null })
  },

  async startCall(
    level: string,
    scenarioId: string,
    timeOfDay: string,
    mode: 'vetted' | 'generated' = 'vetted',
  ) {
    await guard(async () => {
      const data: StartResponse = await api.startSession({
        // No user_id: the call belongs to whoever holds the token.
        level,
        mode,
        personas: state.llmOn,
        narrative_debrief: state.llmOn,
        scenario_id: scenarioId || undefined,
        // 'auto' sends nothing, so the server derives the time from the clock.
        // Sending 'day' by default is what kept every call looking like noon.
        environment: timeOfDay === 'auto' ? {} : { time_of_day: timeOfDay },
      })
      set({
        screen: 'call',
        sessionId: data.session_id,
        scenarioId: data.scenario_id,
        mode: data.mode,
        // The id the server settled on, so a replay of a random draw is a
        // replay and not another draw.
        lastStart: { level, scenarioId: data.scenario_id, timeOfDay, mode },
        reviewed: null,
        difficulty: data.difficulty,
        scene: data.scene,
        transcript: [],
        grade: null,
      })
      absorb(data)
    })
  },

  async speak(utterance: string) {
    if (!canSpeak(state)) return
    const said: SimEvent = {
      phase: state.phase,
      speaker: 'emt',
      text: utterance,
      awaiting_input: false,
    }
    set({ transcript: [...state.transcript, said], busy: true, error: null })
    await guard(async () => {
      absorb(await api.turn(state.sessionId!, utterance))
    })
  },

  async endCall() {
    await guard(async () => {
      absorb(await api.end(state.sessionId!))
    })
  },

  setVoice(on: boolean) {
    if (!on) voice.cancel()
    set({ voiceOn: on, listening: false, heardSoFar: '' })
  },

  setHints(on: boolean) {
    set({ hintsOn: on })
  },

  /** Download the call so far as markdown, for marking up afterwards. */
  async exportTranscript() {
    if (!state.sessionId) return
    await guard(async () => {
      const { text, filename } = await api.transcript(state.sessionId!)
      const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown' }))
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      link.click()
      URL.revokeObjectURL(url)
      set({ busy: false })
    })
  },

  /** Push-to-talk, pressed. Barge-in is implicit: listening cancels speech. */
  async pushToTalk() {
    if (!state.voiceOn || state.listening || !canSpeak(state)) return
    voice.cancel()
    set({ listening: true, heardSoFar: '' })
    try {
      const heard = await voice.listen((text) => set({ heardSoFar: text }))
      set({ listening: false, heardSoFar: '' })
      if (heard.trim()) await actions.speak(heard.trim())
    } catch (e) {
      set({ listening: false, heardSoFar: '', error: e instanceof Error ? e.message : String(e) })
    }
  },

  /** Push-to-talk, released — keep what was heard. */
  releaseToTalk() {
    if (state.listening) voice.stopListening()
  },

  /** Record this EMT's verdict on the generated draft they just played. */
  async review(
    decision: 'approve' | 'reject' | 'skip',
    comment: string,
    realism?: number,
  ) {
    const sessionId = state.sessionId
    if (!sessionId) return
    await guard(async () => {
      const result = await api.review(sessionId, {
        decision,
        comment,
        realism_rating: realism,
      })
      set({ reviewed: result, busy: false })
    })
  },

  showDebrief() {
    set({ screen: 'debrief' })
  },

  /** Run the same call again from the tone-out, same scenario, same settings.
   *
   *  An approved draft has left quarantine by the time this is offered, so
   *  replaying it in 'generated' mode would ask the server for a file that is
   *  no longer there. Approval moves it into the vetted library, so that is
   *  where the replay looks for it.
   */
  async replayCall() {
    const last = state.lastStart
    if (!last) return
    const mode =
      last.mode === 'generated' && state.reviewed?.decision === 'approve'
        ? 'vetted'
        : last.mode
    window.clearTimeout(timer)
    playToken += 1
    voice.cancel()
    set({
      ...initial,
      user: state.user,
      voiceOn: state.voiceOn,
      hintsOn: state.hintsOn,
      llmOn: state.llmOn,
      lastStart: state.lastStart,
    })
    await actions.startCall(last.level, last.scenarioId, last.timeOfDay, mode)
  },

  newCall() {
    window.clearTimeout(timer)
    playToken += 1
    voice.cancel()
    set({
      ...initial,
      user: state.user,
      voiceOn: state.voiceOn,
      hintsOn: state.hintsOn,
      llmOn: state.llmOn,
      screen: 'setup',
    })
  },
}

// A 401 from anywhere — an expired token, a revoked one — puts the EMT back on
// the landing page instead of leaving them on a screen whose every button now
// fails. Registered here rather than in api.ts so that file stays free of the
// store.
token.onExpired(() => {
  window.clearTimeout(timer)
  playToken += 1
  voice.cancel()
  set({ ...initial, error: 'Your session ended. Sign in again.' })
})
