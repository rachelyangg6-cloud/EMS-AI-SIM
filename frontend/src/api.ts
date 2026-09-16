import type {
  CorpusStats,
  Grade,
  HistoryDetail,
  HistoryEntry,
  ReviewResult,
  StartResponse,
  TurnResponse,
  User,
} from './types'

/**
 * The one place the login token lives.
 *
 * Kept in localStorage rather than in the store so a page refresh does not sign
 * the EMT out mid-shift, and read on every request rather than captured once so
 * that logging out takes effect immediately.
 */
const TOKEN_KEY = 'ems.token'

let onUnauthorized: () => void = () => {}

export const token = {
  get: () => localStorage.getItem(TOKEN_KEY) ?? '',
  set: (value: string) => localStorage.setItem(TOKEN_KEY, value),
  clear: () => localStorage.removeItem(TOKEN_KEY),
  /** What the store does when the server says the session is over. */
  onExpired: (handler: () => void) => {
    onUnauthorized = handler
  },
}

function authHeaders(): Record<string, string> {
  const value = token.get()
  return value ? { authorization: `Bearer ${value}` } : {}
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { 'content-type': 'application/json', ...authHeaders(), ...init?.headers },
  })
  if (response.status === 401) {
    // The token expired or was revoked. Drop it and send the user back to the
    // landing page rather than letting every later call fail the same way.
    token.clear()
    onUnauthorized()
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail ?? 'Your session ended. Sign in again.')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.detail ?? `${response.status} ${response.statusText}`)
  }
  return response.json() as Promise<T>
}

const post = <T>(path: string, body: unknown) =>
  call<T>(path, { method: 'POST', body: JSON.stringify(body) })

export const api = {
  // ── signing in ────────────────────────────────────────────────────────────
  // There is no sign-up. Credentials come from `protocol-users`, which is what
  // lets the server believe a profile's training status.

  login: (username: string, password: string) =>
    post<{ token: string; user: User }>('/login', { username, password }),

  logout: () => post<{ status: string }>('/logout', {}),

  /** Turn a stored token back into a profile, on load. */
  me: () => call<User>('/me'),

  /** Edit your own profile. Not a sign-in, and it cannot change your username,
   *  your department, or your training status. */
  updateProfile: (body: {
    name?: string
    email?: string
    // Omitted means "leave what is stored alone" — the server treats '' that
    // way. This client used to omit scope_level entirely, which reset it to
    // EMT-B on every sign-in.
    scope_level?: string
    years_experience?: number
  }) => post<User>('/profile', body),

  review: (
    sessionId: string,
    body: { decision: 'approve' | 'reject' | 'skip'; comment?: string; realism_rating?: number },
  ) => post<ReviewResult>(`/session/${sessionId}/review`, body),

  startSession: (body: {
    scenario_id?: string
    level?: string
    /** 'generated' deals an unreviewed draft from quarantine instead. */
    mode?: 'vetted' | 'generated'
    /** Claude voices the dispatcher, scene and patient. Server default: on. */
    personas?: boolean
    /** Claude writes the prose around the (deterministic) grade. Default: on. */
    narrative_debrief?: boolean
    environment?: Record<string, string>
  }) => post<StartResponse>('/session/start', body),

  turn: (sessionId: string, utterance: string) =>
    post<TurnResponse>(`/session/${sessionId}/turn`, { utterance }),

  end: (sessionId: string) =>
    post<TurnResponse & { grade: Grade }>(`/session/${sessionId}/end`, {}),

  /** Counts describing the library, for the Features page.
   *
   *  The one route that needs no token. `call` still sends the bearer header
   *  when there is one and the server ignores it, so no separate path is
   *  needed here. */
  corpus: () => call<CorpusStats>('/corpus'),

  /** Your own past calls. There is no parameter that widens it to anyone else. */
  history: () => call<{ sessions: HistoryEntry[] }>('/history'),

  /** One past call with everything said on it. */
  historyDetail: (sessionId: string) => call<HistoryDetail>(`/history/${sessionId}`),

  /** The call as markdown. Not `call()` — that parses JSON, and this is a file. */
  async transcript(sessionId: string): Promise<{ text: string; filename: string }> {
    const response = await fetch(`/api/session/${sessionId}/transcript`, {
      headers: authHeaders(),
    })
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
    const disposition = response.headers.get('content-disposition') ?? ''
    const match = /filename="([^"]+)"/.exec(disposition)
    return {
      text: await response.text(),
      filename: match?.[1] ?? `${sessionId}.md`,
    }
  },
}
