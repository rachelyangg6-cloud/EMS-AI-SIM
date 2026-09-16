import { useEffect, useState } from 'react'

import { audio } from './audio'
import { Debrief } from './components/Debrief'
import { Features } from './components/Features'
import { History } from './components/History'
import { Landing } from './components/Landing'
import { Profile, Setup } from './components/Profile'
import { SceneView } from './components/SceneView'
import { Transcript } from './components/Transcript'
import { TurnPrompt } from './components/TurnPrompt'
import { UserGuide } from './components/UserGuide'
import { VitalsMonitor } from './components/VitalsMonitor'
import { Cinematic } from './phases/Cinematic'
import { actions, skip, useStore } from './store'
import { voice } from './voice'

function Call() {
  const scene = useStore((s) => s.scene)
  const vitals = useStore((s) => s.vitals)
  const vitalsGenerated = useStore((s) => s.vitalsGenerated)
  const transcript = useStore((s) => s.transcript)
  const scenarioId = useStore((s) => s.scenarioId)
  const difficulty = useStore((s) => s.difficulty)
  const done = useStore((s) => s.done)
  const queued = useStore((s) => s.queue.length)
  const error = useStore((s) => s.error)

  // Space bar skips the cinematic opening, matching the on-screen button.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && queued) skip()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [queued])

  if (!scene) return null

  return (
    <div className="call">
      <header className="call-head">
        <span className="tag">{scenarioId}</span>
        <span className="tag tag--muted">{difficulty}</span>
        {done && (
          <button type="button" className="ghost" onClick={actions.showDebrief}>
            See debrief
          </button>
        )}
      </header>

      {/* Scene and instruments on the left, everything said on the right, so
          the picture stays put while the transcript grows under it. */}
      <div className="call-body">
        <div className="call-left">
          <div className="stage">
            <SceneView scene={scene} />
            <Cinematic />
          </div>
          <VitalsMonitor vitals={vitals} generated={vitalsGenerated} />
          {error && <p className="error">{error}</p>}
        </div>

        <aside className="call-side" aria-label="Radio and scene traffic">
          <Transcript lines={transcript} />
          <TurnPrompt />
        </aside>
      </div>
    </div>
  )
}

export default function App() {
  const screen = useStore((s) => s.screen)
  const sessionId = useStore((s) => s.sessionId)
  const voiceOn = useStore((s) => s.voiceOn)
  const restoring = useStore((s) => s.restoring)
  const [sound, setSound] = useState(audio.enabled)

  // A stored token becomes a profile once, on load, so a refresh mid-shift
  // does not drop the EMT back onto the landing page.
  useEffect(() => {
    void actions.restore()
  }, [])

  // Nothing at all while the token is being exchanged: rendering the landing
  // page first would flash a sign-in form at somebody already signed in.
  if (restoring) return <main className="app" />

  return (
    // The call and the landing page both need room for two columns; the other
    // screens are single cards.
    <main className={`app ${screen === 'call' || screen === 'landing' ? 'app--wide' : ''}`}>
      {/* These three are reproduced as specimens in UserGuide.tsx. A label
          change here needs the same change there. */}
      <div className="toggles">
        {sessionId && (
          <button
            type="button"
            className="sound"
            title="Download this call as markdown"
            aria-label="Export transcript"
            onClick={() => void actions.exportTranscript()}
          >
            ⬇
          </button>
        )}
        {voice.canSpeak && (
          <button
            type="button"
            className="sound"
            aria-pressed={voiceOn}
            title={voiceOn ? 'Voice on' : 'Voice off'}
            onClick={() => actions.setVoice(!voiceOn)}
          >
            {voiceOn ? '🗣' : '💬'}
          </button>
        )}
        <button
          type="button"
          className="sound"
          aria-pressed={sound}
          title={sound ? 'Sound on' : 'Sound off'}
          onClick={() => {
            audio.setEnabled(!sound)
            setSound(!sound)
          }}
        >
          {sound ? '🔊' : '🔇'}
        </button>
      </div>

      {screen === 'landing' && <Landing />}
      {screen === 'profile' && <Profile />}
      {screen === 'setup' && <Setup />}
      {screen === 'call' && <Call />}
      {screen === 'debrief' && <Debrief />}
      {screen === 'history' && <History />}
      {screen === 'guide' && <UserGuide />}
      {screen === 'features' && <Features />}
    </main>
  )
}
