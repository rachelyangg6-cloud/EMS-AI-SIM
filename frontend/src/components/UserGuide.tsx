/**
 * The orientation a new EMT would otherwise have to get from somebody's memory.
 *
 * **Why the controls below are the real ones.** Every demo here is a real
 * `<button>` carrying the real className, not a picture and not a lookalike.
 * The classes are the contract and they live in one stylesheet, so a style
 * change reaches this page without anybody remembering to update it. What a
 * copy cannot track is a *label* change, so the source sites carry a pointer
 * comment naming this file.
 *
 * They are wrapped in `inert`, which takes the whole subtree out of the tab
 * order, the accessibility tree and pointer events at once. Two things that do
 * not work instead: `disabled` fades a button to 45% opacity, which
 * misrepresents the control; and swapping in a `<span>` loses the padding,
 * radius and color that live on the bare `button` selector.
 *
 * Because an inert control cannot be toggled, each pair is shown in both
 * states side by side.
 */

import type { ReactNode } from 'react'

import { actions } from '../store'

/** One specimen control, captioned. The caption sits outside the inert node so
 *  a screen reader still describes a control it cannot reach. */
function Demo({ label, children }: { label: string; children: ReactNode }) {
  return (
    <figure className="guide-demo">
      <div className="guide-demo-stage" inert>
        {children}
      </div>
      <figcaption className="hint">{label}</figcaption>
    </figure>
  )
}

export function UserGuide() {
  return (
    <div className="card guide">
      <header className="row">
        <div>
          <h1>User guide</h1>
          <p className="sub">
            What every button does, in the order you meet them.
          </p>
        </div>
        <button type="button" className="ghost" onClick={actions.backToMenu}>
          Back
        </button>
      </header>

      <section className="panel">
        <h2>The icons in the corner</h2>
        <p>
          These sit in the top right of <em>every</em> screen, including this
          one. The ones below are specimens — the live ones are up there now.
        </p>
        <div className="guide-demos">
          <Demo label="Sound on. Tap to mute the sirens, radio squelch and monitor tones.">
            <button type="button" className="sound">🔊</button>
            <button type="button" className="sound">🔇</button>
          </Demo>
          <Demo label="Voice off. Tap to have the dispatcher, patient and bystanders read their lines aloud.">
            <button type="button" className="sound">💬</button>
            <button type="button" className="sound">🗣</button>
          </Demo>
          <Demo label="Download the call so far as markdown. Appears only once a call is running.">
            <button type="button" className="sound">⬇</button>
          </Demo>
        </div>
        <p className="hint">
          Neither sound nor voice is remembered between visits — both start off
          again when you reload the page.
        </p>
      </section>

      <section className="panel">
        <h2>Browser and permissions</h2>
        <p>
          Speaking and listening use the browser&rsquo;s own speech engine, so
          they work in <strong>Chrome, Edge and Safari</strong> only. Firefox
          has no speech recognition at all — everything still works, you just
          type instead of talking.
        </p>
        <p>
          The first time you press the microphone the browser asks for
          permission. <strong>Allow it.</strong> If you dismiss or block that
          prompt, the app tells you the microphone is blocked; the fix is the
          camera/microphone icon in your address bar, then try again.
        </p>
        <p className="hint">
          Sound playback can also need a click somewhere on the page first —
          browsers refuse to play audio on a page you have not interacted with.
        </p>
      </section>

      <section className="panel">
        <h2>Picking a call</h2>
        <dl>
          <dt>Difficulty</dt>
          <dd>
            Basic, intermediate or expert. This is about how much the patient
            volunteers on their own: on an expert call you have to ask.
          </dd>
          <dt>Time of day</dt>
          <dd>
            Changes the light, the scene and the traffic. <em>Auto</em> uses
            whatever time it actually is right now.
          </dd>
          <dt>Topic or scenario <em>(optional)</em></dt>
          <dd>
            Leave it blank for a random call. Type a topic — hypoxia, chest
            pain, stroke — to practice one thing. If you happen to know a
            specific scenario&rsquo;s id you can paste that instead, but you are
            not expected to.
          </dd>
          <dt>Case source <em>(certified reviewers only)</em></dt>
          <dd>
            Most people never see this. <em>Vetted library</em> is the reviewed
            corpus. <em>Unreviewed draft</em> plays a call nobody has checked
            yet, and asks you at the end whether it was any good.
          </dd>
        </dl>
        <p className="hint">
          <strong>Start the call</strong> reads &ldquo;Toning out…&rdquo; while
          dispatch is written.
        </p>
      </section>

      <section className="panel">
        <h2>During the call</h2>
        <p>
          The call opens with the tone-out, the response and your arrival. Press{' '}
          <strong>Skip ahead</strong> to jump straight to the patient.
        </p>
        <p>
          Then it is your turn, every turn. Say or type what you would actually
          do — &ldquo;I check for a radial pulse&rdquo; — and the scene answers.
        </p>
        <div className="guide-demos">
          <Demo label="Hints are off by default. Turn them on for a nudge about what to consider next; it only appears while it is your move.">
            <button type="button" className="hint-toggle">Hints off</button>
            <button type="button" className="hint-toggle hint-toggle--on">Hints on</button>
          </Demo>
          <Demo label="Push to talk: hold it down, speak, let go. Red means it is listening. It only appears once voice is on.">
            <button type="button" className="ptt">🎙</button>
            <button type="button" className="ptt ptt--live">🎙</button>
          </Demo>
        </div>
        <p>
          <strong>There is no microphone button of its own.</strong> The
          microphone appears when you turn <em>voice</em> on with 🗣 in the top
          right corner, and disappears when you turn it off. Typing always
          works, in every browser, whether or not voice is on.
        </p>
        <div className="guide-demos">
          <Demo label="The typed alternative. Enter or Say sends your action.">
            <div className="turn-row">
              <input placeholder="Say what you would do…" readOnly />
              <button type="button">Say</button>
            </div>
          </Demo>
        </div>
      </section>

      <section className="panel">
        <h2>Ending a call</h2>
        <p>There are three ways, and they all reach the same debrief:</p>
        <ul>
          <li>Press <strong>End call</strong>.</li>
          <li>Say &ldquo;end of call&rdquo; out loud, if voice is on.</li>
          <li>Let the scenario finish on its own — some calls end themselves.</li>
        </ul>
        <div className="guide-demos">
          <Demo label="Ends the call and grades it. You cannot undo this, but you can replay the same case afterwards.">
            <button type="button" className="ghost">End call</button>
          </Demo>
        </div>
        <p className="hint">
          Leaving the page mid-call does not save it — an unfinished call is not
          graded and does not appear in Past calls.
        </p>
      </section>

      <section className="panel">
        <h2>Reading your debrief</h2>
        <p>
          Grading follows the NREMT style: points for the steps you hit, the
          five scene size-up items scored on their own, and critical criteria
          that fail the call outright however well the rest of it went.
        </p>
        <p>
          Sections marked <em>(only sometimes)</em> appear when the call calls
          for them — do not go hunting for one that is not there.
        </p>
        <dl>
          <dt>Pass or Fail, then the points</dt>
          <dd>
            The verdict leads and the number sits underneath, because a single
            critical error fails the call no matter how many points you scored.
            &ldquo;25 / 27&rdquo; on its own could describe a call that killed
            the patient.
          </dd>
          <dt>The summary</dt>
          <dd>A plain-language account of how the call went, before any checklist.</dd>
          <dt>Your debrief <em>(only sometimes)</em></dt>
          <dd>
            What went well, what did not, and what to do differently. Written
            for that specific call; everything below stands on its own without it.
          </dd>
          <dt>Was this a realistic call? <em>(certified reviewers, draft cases only)</em></dt>
          <dd>
            Your verdict on an unreviewed case: approve it into the shared
            library, or reject it with a comment saying why.
          </dd>
          <dt>How the points were reached</dt>
          <dd>The scoring, line by line — what each part was worth and what you earned.</dd>
          <dt>Critical <em>(only sometimes)</em></dt>
          <dd>
            The things that fail a call outright. Each one says what you should
            have done instead. If this section is absent, nothing critical was missed.
          </dd>
          <dt>What to work on</dt>
          <dd>The missed steps, pulled out of the full list so they are not buried.</dd>
          <dt>Scene size-up · n/5</dt>
          <dd>
            Scene safety, number of patients, mechanism, resources, spinal
            precautions. A ✗ means it was never stated out loud.
          </dd>
          <dt>The call, step by step</dt>
          <dd>
            Every expected action marked ✓ hit, ~ partial or ✗ missed, with{' '}
            <em>what you actually said</em> underneath — so you can tell a
            wording problem from a clinical one. Also notes any steps done out
            of sequence, and which turn your first intervention came on.
          </dd>
          <dt>Why these are the right steps <em>(only sometimes)</em></dt>
          <dd>The reasoning, written by the EMT who vetted the case.</dd>
          <dt>What this call turned on</dt>
          <dd>
            The findings the case was built around. <strong>Nothing here costs
            you points</strong> — it is here to be read afterwards, not to be
            narrated during the call.
          </dd>
          <dt>The footer</dt>
          <dd>
            Every page the grading drew on. Each claim traces back to
            EMT-vetted content rather than to a model&rsquo;s opinion.
          </dd>
        </dl>
        <p className="hint">
          <strong>Replay this call</strong> runs the same case again from the
          tone-out. <strong>Run another call</strong> returns you to Pick a call.
        </p>
      </section>
    </div>
  )
}
