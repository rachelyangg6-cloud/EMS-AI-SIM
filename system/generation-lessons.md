# Generation lessons

Realism failures found by EMTs reviewing generated calls, in their words. Every
line here was written because a draft got something wrong badly enough to be
rejected, and every line is fed back into the generation prompt.

Not a style guide. A list of specific mistakes not to repeat.

The first entries are not from generated calls — they are the failures found by
playing the hand-written corpus, written down here so the generator starts
knowing them instead of rediscovering them one draft at a time.

- The dispatch must name a person and a complaint, not a task or a topic. "About to administer a medication under protocol" and "Pediatric trauma; child being immobilized after a crash" are teaching frames; a trainee hearing either has nobody to assess.
- Never write the Presentation as "You are…". It is what you see on arrival, in the third person. A second-person frame cannot be narrated when the doors open, and the patient ends up reciting it back.
- State a full numeric set of vitals — RR, pulse, SpO2 and BP — and keep them consistent with the condition. An SpO2 of 97% next to "severe respiratory distress" teaches the wrong reflex, and a blank monitor gives the trainee nothing to react to.
- Vitals must suit the patient's age. A five-month-old does not have a blood pressure of 118/68. If the call is pediatric, say so in the dispatch and pick numbers from that band.
- Every oxygen step names the device AND the flow rate: nasal cannula 2–6 L/min, nonrebreather 12–15 L/min, BVM 15 L/min with a reservoir. "Give oxygen" is not an order anyone can carry out.
- US English spelling throughout — recognize, pediatric, hemorrhage, color, center, gray. The source resource is US and the corpus should not be split across two spellings of the same word.
- Do not write a call with no patient. Confidentiality, documentation, PPE and hand-over lessons are real EMS competencies, but they are not ride-alongs and the simulator has nothing to put on the stretcher.
- Do not write a contingency as a step. "Secure the airway and be ready to ventilate" puts a ventilate intent into the answer key, so the trainee is nudged to bag a patient who is breathing at 22 with a saturation of 97. Write the action the call actually needs — secure the airway and keep it open — and put the contingency in the rationale.
- Never bury the action behind a reason. "Ensure a safe scene, because patients with diabetic emergencies can be agitated" matches nothing the grader can see, so a trainee who sizes up the scene gets no credit. Lead with the action; the because clause belongs in the rationale.
- Every numbered step must classify to an intent. Run python -m ems.cli.rubric_check --generated before saving: a line with no intent is graded on word overlap and can never be hinted.
- Number the steps in the order the call should actually run. The grader reads the numbering as the sequence and marks a time-critical treatment down when it is done after steps listed later, so airway and positioning come before history and documentation.
- Red flags are findings, not lines of dialogue. Write them as what the case turns on — an EMT acts on cold clammy skin, they do not announce it.
