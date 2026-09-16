import { useState } from 'react'

import { actions, useStore } from '../store'

type CallMode = 'vetted' | 'generated'

/**
 * Editing your own profile — reached from the menu, not on the way in.
 *
 * Three fields are missing on purpose. The username is permanent, because it is
 * what a person's practice history hangs off. The department is an
 * administrative fact. And the training status decides who may write to the
 * shared library, so it is set by `protocol-users promote` and by nothing a
 * browser can send.
 */
export function Profile() {
  const user = useStore((s) => s.user)
  const busy = useStore((s) => s.busy)
  const error = useStore((s) => s.error)
  const [name, setName] = useState(user?.name ?? '')
  const [email, setEmail] = useState(user?.email ?? '')
  const [scope, setScope] = useState(user?.scope_level ?? 'EMT-B')
  const [years, setYears] = useState(user?.years_experience ?? 0)

  return (
    <form
      className="card"
      onSubmit={(e) => {
        e.preventDefault()
        void actions.saveProfile({
          name: name.trim(),
          email: email.trim(),
          scope_level: scope,
          years_experience: years,
        })
      }}
    >
      <h1>Your profile</h1>
      <p className="sub">
        {user?.username} · {user?.corp_slug}
      </p>

      <label>
        Your name
        <input value={name} onChange={(e) => setName(e.target.value)} required />
      </label>
      <label>
        Email
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@example.org"
        />
      </label>
      <label>
        Scope of practice
        <select value={scope} onChange={(e) => setScope(e.target.value)}>
          <option value="EMT-B">EMT-B</option>
          <option value="AEMT">AEMT</option>
          <option value="Paramedic">Paramedic</option>
        </select>
      </label>
      <label>
        Years of experience
        <input
          type="number"
          min={0}
          max={50}
          value={years}
          onChange={(e) => setYears(Number(e.target.value))}
        />
      </label>

      <p className="hint">
        {user?.training_status === 'certified'
          ? 'You are a certified reviewer: you can approve generated cases into the shared library.'
          : 'Approving generated cases into the shared library is for certified EMTs. Ask whoever runs the simulator for your department.'}{' '}
        Your username and department cannot be changed here, and a new password
        has to be issued the same way.
      </p>

      {error && <p className="error">{error}</p>}
      <div className="row">
        <button type="submit" disabled={busy || !name.trim()}>
          {busy ? 'Saving…' : 'Save'}
        </button>
        <button type="button" className="ghost" onClick={actions.backToMenu}>
          Back
        </button>
      </div>
    </form>
  )
}

export function Setup() {
  const user = useStore((s) => s.user)
  const busy = useStore((s) => s.busy)
  const error = useStore((s) => s.error)
  const [level, setLevel] = useState('intermediate')
  const [scenario, setScenario] = useState('')
  const [timeOfDay, setTimeOfDay] = useState('auto')
  const [mode, setMode] = useState<CallMode>('vetted')

  return (
    <form
      className="card"
      onSubmit={(e) => {
        e.preventDefault()
        void actions.startCall(level, scenario.trim(), timeOfDay, mode)
      }}
    >
      <h1>Pick a call</h1>
      <p className="sub">
        {user?.name} · {user?.corp_slug}
        {user?.training_status === 'certified' && ' · certified reviewer'}
      </p>

      <label>
        Difficulty
        <select value={level} onChange={(e) => setLevel(e.target.value)}>
          <option value="basic">Basic</option>
          <option value="intermediate">Intermediate</option>
          <option value="expert">Expert</option>
        </select>
      </label>
      <label>
        Time of day
        <select value={timeOfDay} onChange={(e) => setTimeOfDay(e.target.value)}>
          <option value="auto">Auto — whatever time it is now</option>
          <option value="day">Day</option>
          <option value="night">Night</option>
          <option value="dawn">Dawn</option>
          <option value="dusk">Dusk</option>
        </select>
      </label>
      {/* One box, two things: a topic if you know what you want to practice, a
          scenario id if you know exactly which call. The id form still works but
          is no longer advertised here — trainees may not have the resource the
          ids come from, so the user guide documents it instead. */}
      <label>
        Topic or scenario <em>(optional)</em>
        <input
          value={scenario}
          onChange={(e) => setScenario(e.target.value)}
          placeholder="e.g. hypoxia, chest pain, or stroke"
        />
      </label>

      {/* Unreviewed drafts are never in the ordinary draw — you ask for one.
          Only offered to a certified EMT, because playing one is only useful if
          you can also say whether it was any good. */}
      {user?.training_status === 'certified' && (
        <label>
          Case source
          <select value={mode} onChange={(e) => setMode(e.target.value as CallMode)}>
            <option value="vetted">Vetted library — reviewed calls</option>
            <option value="generated">Unreviewed draft — you decide at the end</option>
          </select>
        </label>
      )}

      {error && <p className="error">{error}</p>}
      <button type="submit" disabled={busy}>
        {busy ? 'Toning out…' : 'Start the call'}
      </button>

      <nav className="menu-links">
        <button type="button" className="link" onClick={actions.showGuide}>
          User guide
        </button>
        <button type="button" className="link" onClick={() => void actions.showFeatures()}>
          Features
        </button>
        <button type="button" className="link" onClick={() => void actions.openHistory()}>
          Past calls
        </button>
        <button type="button" className="link" onClick={actions.showProfile}>
          Your profile
        </button>
        <button type="button" className="link" onClick={() => void actions.logOut()}>
          Sign out
        </button>
      </nav>
    </form>
  )
}
