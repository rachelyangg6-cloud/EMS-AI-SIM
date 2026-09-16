/** Mirrors the payloads in ems/web/server.py. */

export type Phase =
  | 'TONE_OUT' | 'EN_ROUTE' | 'ARRIVAL' | 'SIZE_UP' | 'SCENE_NARRATION'
  | 'TURN' | 'ANSWER' | 'OBSERVE' | 'RESULT'
  | 'END_OF_CALL' | 'DEBRIEF'

export type Speaker = 'dispatcher' | 'narrator' | 'patient' | 'sim' | 'emt'

export interface SimEvent {
  phase: Phase
  speaker: Speaker
  text: string
  awaiting_input: boolean
}

export type TrainingStatus = 'apprentice' | 'certified'

export interface User {
  id: number
  corp_slug: string
  name: string
  /** What they may do to a patient. */
  scope_level: string
  /** Where they are in their training — decides whether they may promote a
   *  generated draft into the vetted corpus. Set by `protocol-users promote`
   *  and by nothing this client can send. */
  training_status: TrainingStatus
  years_experience: number
  /** The handle they log in with. Permanent once issued. */
  username: string
  email: string
}

/** One past call, as `/api/history` lists it. */
export interface HistoryEntry {
  id: string
  scenario_id: string
  mode: string
  difficulty: string
  started_at: string
  ended_at: string | null
  /** Raw points earned. A row from before the scale changed holds a percentage
   *  instead — `points_possible` is null on exactly those rows. */
  score: number | null
  points_possible: number | null
  passed: boolean | null
  grade: Grade | null
}

/** One past call with everything said on it. */
export interface HistoryDetail extends HistoryEntry {
  turns: { seq: number; phase: string; speaker: string; utterance: string }[]
}

/** Only the vitals the EMT has actually measured. */
export interface Vitals {
  rr?: number
  hr?: number
  spo2?: number
  bp?: string
}

export type Posture = 'tripod' | 'slumped' | 'seated' | 'supine' | 'prone' | 'ambulatory'
export type Skin = 'cyanotic' | 'mottled' | 'diaphoretic' | 'pale' | 'flushed' | 'normal'
export type Loc = 'unresponsive' | 'painful' | 'verbal' | 'drowsy' | 'confused' | 'alert'

export interface PatientSpec {
  posture: Posture | null
  skin: Skin | null
  effort: string | null
  loc: Loc | null
  /** Drives the chest-rise rate. Present from the start — you can see fast breathing. */
  rr: number | null
  /** Always null at start: monitor readings arrive through `vitals` once measured. */
  hr: number | null
  spo2: number | null
}

export interface SceneSpec {
  scenario_id: string
  setting: 'residence' | 'street' | 'public-space' | 'workplace' | 'ambulance' | 'unknown'
  time_of_day: 'day' | 'night' | 'dawn' | 'dusk'
  /** Clock hour 0–23 for a continuously shifting sky; null when only the bucket is known. */
  hour: number | null
  weather: string
  hazards: string[]
  bystanders: { role: string; state: string }[]
  patient: PatientSpec | null
  equipment_visible: string[]
}

export interface ActionResult {
  index: number
  action: string
  status: 'hit' | 'partial' | 'missed'
  matched_turn: number | null
  note: string
  /** The EMT's own words that earned this step. */
  said: string
}

export interface Grade {
  scenario_id: string
  /** Points earned on this scenario, and out of what. Deliberately not a
   *  percentage: five size-up items and two points a step is a coarse
   *  measurement, and scaling it to 100 implied a precision it never had. */
  points: number
  points_possible: number
  /** A critical error fails the call on its own, whatever the points say. */
  passed: boolean
  size_up: { covered: string[]; missed: string[]; score: number }
  actions: ActionResult[]
  red_flags_caught: string[]
  red_flags_missed: string[]
  critical_errors: { rule: string; detail: string; guidance: string }[]
  out_of_order: number
  turns_to_first_intervention: number | null
  citations: string[]
  /** Plain-English account of the call, shown before any checklist. */
  summary: string
  /** The scenario author's reasoning behind the answer key. */
  rationale: string
  /** [label, earned, possible] — where the points came from. */
  breakdown: [string, number, number][]
  /** Claude's prose around the result above. Absent when the LLM is switched
   *  off, and when the call to write it failed — see `narrative_error`. */
  narrative?: Narrative
  /** Why there is no narrative. The result is unaffected either way. */
  narrative_error?: string
}

/** The written debrief. It explains the grade; it never sets it. */
export interface Narrative {
  scenario_id: string
  summary: string
  pros: string[]
  cons: string[]
  improvements: string[]
  /** Bullets dropped for citing a source the scenario does not have. */
  stripped: string[]
  fabricated_citations: string[]
  emt_verified: boolean
}

export interface TurnResponse {
  phase: Phase
  awaiting_input: boolean
  done: boolean
  events: SimEvent[]
  vitals: Vitals
  /** Keys in `vitals` the simulator invented rather than read from the scenario. */
  vitals_generated: string[]
  intents: string[]
  /** A nudge toward the next missed action; null unless it is your move. */
  hint: string | null
  grade?: Grade
}

export interface ReviewResult {
  decision: 'approve' | 'reject' | 'skip'
  scenario_id: string
  status: string
  location: 'vetted' | 'generated'
  lesson_recorded: boolean
  /** Only on a skip: how many other drafts are still waiting. */
  drafts_remaining?: number
}

export interface StartResponse extends TurnResponse {
  session_id: string
  scenario_id: string
  /** 'generated' means an unreviewed draft — the debrief offers a verdict. */
  mode: 'vetted' | 'generated'
  difficulty: string
  scene: SceneSpec
}

/** Counts describing the library, from the unauthenticated `/api/corpus`.
 *  Mirrors `ems/corpus_stats.py`; histograms are ordered high to low there, and
 *  object key order is preserved, so the page renders them as they arrive. */
export interface CorpusStats {
  files: number
  pages: {
    total: number
    by_type: Record<string, number>
    by_age_group: Record<string, number>
  }
  scenarios: {
    total: number
    reviewed: number
    expertise_marked: number
    corrected: number
    by_status: Record<string, number>
    by_kind: Record<string, number>
    by_age_group: Record<string, number>
  }
  topics: {
    vocabulary: number
    used: number
    assignments: number
    by_topic: Record<string, number>
  }
  citations: {
    distinct: number
    occurrences: number
    sources_cited: number
    pages_cited: number
    pages_total: number
    pages_distinct: number
    scenarios_cited: number
    scenarios_total: number
    scenarios_distinct: number
  }
  sources: { covered: number; by_source: Record<string, number> }
  lessons: number
  models: { authoring: string; personas: string; grading: string }
}
