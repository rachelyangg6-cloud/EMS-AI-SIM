import { useState } from 'react'

import { actions, useStore } from '../store'

/**
 * The front door: what this is on the left, the login on the right.
 *
 * There is no sign-up link, and its absence is deliberate rather than an
 * omission — accounts are issued with `protocol-users`, which is what lets the
 * server believe a profile's training status. The copy below says so, because a
 * login form with no way in is otherwise just a dead end.
 */
export function Landing() {
  const busy = useStore((s) => s.busy)
  const error = useStore((s) => s.error)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  const ready = username.trim() !== '' && password !== ''

  return (
    <div className="landing">
      <section className="landing-pitch">
        <p className="eyebrow">EMT ride-along</p>
        <h1>Practice a whole call, dispatch to debrief.</h1>
        <p className="lede">
          The tones drop, you arrive, and what happens next is what you say.
          Size up the scene, work the patient, and get graded against a rubric
          an EMT signed off on — not a quiz, a call.
        </p>

        <dl className="landing-points">
          <div>
            <dt>Grounded and traceable</dt>
            <dd>
              Every scenario, answer, and grading step is linked back to the
              specific source or section of the EMT training materials, SOPs,
              or SOGs that support it, making each output transparent,
              verifiable, and grounded in an identifiable source.
            </dd>
          </div>
          <div>
            <dt>Reviewed by people who run calls</dt>
            <dd>
              Cases enter the shared library only when a certified EMT approves
              them, and every approval is recorded against the person who made it.
            </dd>
          </div>
          <div>
            <dt>Your practice is kept</dt>
            <dd>
              Each call is stored with its transcript and its grading, so you
              can go back to a call you fumbled and see exactly where.
            </dd>
          </div>
        </dl>
      </section>

      <form
        className="card landing-login"
        onSubmit={(e) => {
          e.preventDefault()
          if (ready) void actions.logIn(username, password)
        }}
      >
        <h2>Sign in</h2>
        <p className="sub">Use the username and password your department issued you.</p>

        <label>
          Username
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            required
            autoFocus
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>

        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={busy || !ready}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>

        <p className="hint">
          No account, or lost your password? Whoever runs the simulator for your
          department can issue a new one. There is no self-service reset — that
          is what keeps a certified EMT’s approval worth something.
        </p>
      </form>

      {/* Spans both columns and sits under the fold: the login is what a
          returning user came for, and this is for everyone who cannot yet. */}
      <section className="landing-contact">
        <h2>Interested in trying EMS RideAlong?</h2>
        <p>
          If you’re an EMS department, EMT, or EMT trainee interested in trying
          the app, contact whoever runs this simulator for access or more
          information.
        </p>
      </section>
    </div>
  )
}
