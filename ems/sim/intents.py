"""Classify EMS utterances into intent tags — deterministic, no LLM.

The grader has to decide whether what the EMT said corresponds to a line in a
scenario's ``## Correct actions``. Both sides are free English written by
different people ("non-rebreather at 15 liters" vs. "supplemental oxygen at
15 L/min via NRB"), so raw string matching is useless and word overlap can't
tell an NRB from a BVM — a distinction that is the whole point of the call.

So both sides run through the same regex table and are compared as intent sets.
Anything the table doesn't recognize falls back to token overlap in
``ems.sim.grade``, so an unusual action line still gets graded, just vaguely.

The table is deliberately hand-written and reviewable: an EMT should be able to
read it and say whether it's right.
"""

import re

# ── the table ────────────────────────────────────────────────────────────────
# Each intent maps to patterns that mean "this is happening". Order is
# irrelevant; an utterance may carry any number of intents.

_TABLE: dict[str, list[str]] = {
    # scene size-up (the five NREMT items)
    "scene-safety": [
        r"danger zone", r"\\bupwind\\b", r"\\bstag(e|ing)\\b",
        r"park the ambulance", r"\\d{2,3} feet\\b", r"approach the scene",
        r"scene (is |appears )?safe", r"safety of the scene", r"scene safety",
        r"is (the |it )?safe to (enter|approach)", r"ensure .{0,20}scene .{0,20}safe",
        r"stage(d|ing)? (until|for)", r"danger(ous)? scene", r"hazard",
    ],
    "bsi": [
        r"\bbsi\b", r"\bppe\b", r"standard precautions", r"body substance isolation",
        r"\bglove", r"eye protection", r"face shield", r"\bgown\b", r"\bmask up\b",
    ],
    "patient-count": [
        r"(number|how many) of patients", r"how many patients", r"number of patients",
        r"single patient", r"one patient", r"multiple patients", r"additional patients",
        r"\bmci\b", r"mass casualty",
    ],
    "moi-noi": [
        r"\bmoi\b", r"\bnoi\b", r"mechanism of injury", r"nature of (the )?illness",
        r"what happened", r"how (did|was) .{0,20}(injur|hurt)",
    ],
    "additional-resources": [
        r"additional (resources|units|help)", r"more (units|hands|help)",
        r"call for (another|a second|additional)", r"request (fire|police|pd|law)",
        # The corpus asks for a second *ambulance* more often than it says
        # "additional units", which is the phrasing the table was written from.
        r"(request|call for|need)[^.]{0,25}\b(ambulance|bus|rig|engine|rescue)\b",
        r"\bfire department\b", r"extrication", r"\bmutual aid\b",
        # ALS is an additional resource, so asking for it satisfies the item.
        r"\bals\b", r"advanced life support", r"\bparamedic",
    ],

    # assessment
    "general-impression": [
        r"general impression", r"primary (assessment|survey)", r"initial assessment",
        # The resource writes it "A-B-Cs"; \babcs?\b does not survive the hyphens,
        # so every scenario quoting the source went ungraded on its own words.
        r"\ba-?b-?cs?\b", r"life threat",
    ],
    "mental-status": [
        r"mental status", r"\bavpu\b", r"level of consciousness", r"\bloc\b", r"\bgcs\b",
        r"alert and orient", r"\ba&ox?\d?\b", r"responsive to (verbal|pain)",
    ],
    "breathing-assess": [
        r"(assess|check|look at|evaluate)[^.]{0,25}breathing",
        r"(rate|depth|adequacy) of (respiration|breathing)", r"respiratory (rate|effort)",
        r"chest rise", r"breath sounds", r"lung sounds", r"auscultat",
        # The book says "listen to both sides of the chest". The table only had
        # the words a paraphrase would reach for.
        r"\blisten\b[^.]{0,25}\b(both sides|chest|lungs?|breath)\b",
        r"work of breathing", r"accessory muscle",
        # "Listen to both sides of the chest" is how the chest trauma source
        # phrases it throughout, and it names neither breath sounds nor
        # auscultation — so every scenario using the resource's own words for
        # the single most important assessment in chest trauma went ungraded.
        r"listen\w*[^.]{0,25}(chest|lung|both sides|each side)",
        # As with the pulse: naming it is asking for it.
        r"\brespirations?\b", r"\brr\b",
    ],
    "pulse-check": [
        r"(check|assess|feel|palpate)[^.]{0,20}pulse", r"radial pulse", r"carotid pulse",
        r"pulse check", r"\bperfusion\b", r"capillary refill",
        # Naming the number counts as asking for it: "what is the pulse", or just
        # "pulse". Requiring a verb meant a trainee could ask three times and
        # never be given a heart rate the scenario had all along.
        # "pulse ox" is a saturation, not a pulse, so it is excluded here.
        r"\bpulse\b(?!\s*(?:ox|oximet))", r"\bheart rate\b", r"\bhr\b",
    ],
    # Umbrella; the three below say *which* number the EMT went after, which is
    # what decides whether the monitor may show it.
    "vitals": [
        r"vital signs", r"\bvitals\b", r"blood pressure", r"\bbp\b", r"\bspo2\b",
        r"pulse ox", r"oximet", r"\bbaseline vitals\b", r"\betco2\b", r"\bcapnograph",
    ],
    "vitals-full": [r"vital signs", r"\bvitals\b", r"full set of vitals", r"baseline vitals"],
    "vitals-bp": [r"blood pressure", r"\bbp\b", r"\bcuff\b"],
    "vitals-spo2": [
        r"\bspo2\b", r"\bsao2\b", r"pulse ox", r"oximet", r"\bsats?\b", r"saturation",
    ],
    "glucose-check": [
        r"blood (glucose|sugar)", r"\bbgl\b", r"glucometer", r"finger ?stick",
    ],
    "sample-history": [
        r"\bsample\b", r"(get|take|obtain)[^.]{0,20}history", r"medical history",
        r"allerg", r"medications? (list|do you take|is he|is she)",
        r"last (oral intake|meal|ate)", r"events leading",
        # History gets asked for, not only "taken": nineteen corpus lines open
        # "Ask about ..." or "Ask the wife about ..." and matched nothing.
        r"\bask(s|ing)?\b[^.]{0,45}\b(history|medications?|allerg|reaction|last|previous|prior|whether|about)\b",
        r"\bask\w*\b[^.]{0,45}\b(what|when|how)\b[^.]{0,40}\b(was|were|took|takes|happened|seemed|changed)\b",
    ],
    "opqrst": [
        r"\bopqrst\b", r"describe the pain", r"pain scale", r"(scale )?(of )?1 to 10",
        r"what makes it (better|worse)", r"provoke", r"radiat", r"onset of",
    ],
    # Actions with a wiki page and a place in the corpus that the table simply
    # had no category for. Found by writing a stroke draft and discovering that
    # "perform a stroke scale", "take a temperature" and "ask when he was last
    # known to be well" all matched nothing at all — 8 of that draft's 15 steps
    # were invisible, and no rewording could have saved them.
    # Naming the working impression out loud. 79 of the corpus's unmatched
    # rubric lines begin "recognize…", and no category covered any of them —
    # yet saying "this looks like anaphylaxis" is a real action, part of every
    # radio report, and the thing most rubric lines are actually asking for.
    "recognize-condition": [
        r"\b(recogniz|identif|suspect)\w*\b",
        r"\bthis (looks|sounds|presents) like\b", r"\bconsistent with\b",
        r"\btreat (this|it|him|her|them) as\b", r"\bworking (impression|diagnosis)\b",
        r"\bmy impression is\b", r"\bthis is (an?|likely|probably)\b",
        r"\b(rule|ruling) (out|in)\b",
    ],
    # Talking to the people on the call. Distinct from the radio report: this is
    # what you say to the patient, the family and the bystander who is about to
    # do the wrong thing.
    "explain-to-patient": [
        r"\bexplain (to|that|why|what)\b", r"\breassure\b",
        # The gerund, and only with an object. "Keep reassuring the patient" is
        # this intent; "do not be reassured by the 99% reading" is a caution
        # about pulse oximetry in carbon monoxide poisoning and must not match.
        r"\breassur(e|es|ing|ance)\b\s*(the|him|her|them|his|their)\b",
        r"\btell (the|her|him|them) (patient|family|mother|father|wife|husband|why|what)\b",
        r"\b(persuade|convince) (the|her|him|them)\b",
        r"\bstop (the )?(coworker|colleague|bystander|friend|family|mother|father)\b",
    ],
    # Keeping the patient from coming to further harm — restraint, seizure
    # precautions, moving them away from the hazard.
    "protect-patient": [
        r"protect (the |him|her|them)\w*\s*(from|against)", r"\brestrain\b",
        r"\bpad (the|around)\b", r"move (the )?(patient|him|her|them) (away|to safety|out of)",
        r"prevent (further )?(injury|harm|self[- ]injury)",
    ],
    # Checking the drug before it goes in — the rights, the expiry, the kit.
    "medication-check": [
        r"expir(ation|y|ed)", r"prescribed (to|for) (this|the) patient",
        r"check the (medication|drug|dose|label|name)",
        r"(verify|confirm|inspect)[^.]{0,30}(medication|dose|volume|components|kit)",
        r"\bsecond provider\b", r"\bfive rights\b", r"\bright (patient|dose|route|medication)\b",
        r"\bdiscolou?r(ed|ation)\b", r"\bcloudy\b",
    ],
    "pupils": [
        r"\bpupils?\b", r"\bperrla?\b", r"\breactive to light\b",
    ],
    "ecg": [
        r"\d{1,2}[- ]lead", r"\becg\b", r"\bekg\b", r"\bcardiac monitor\b",
    ],
    # Getting the patient out and onto something, which for a cardiac patient is
    # itself a treatment decision — exertion worsens the ischemia.
    "patient-movement": [
        r"stair chair", r"\bscoop\b", r"long (spine )?board", r"\bstretcher\b",
        r"\bcarry (him|her|them|the patient)\b", r"do not let (him|her|them) walk",
        r"\bextricat\w*", r"\blog ?roll\b",
    ],
    # After a needlestick or a splash: wash it, report it, get it followed up.
    "exposure-response": [
        r"exposure (site|report|control|process)", r"\bneedle ?stick\b",
        r"wash the (exposure|site|area)", r"report the exposure",
        r"designated (infection control )?officer", r"\bpost[- ]exposure\b",
    ],
    # Bring the bottle, the pump, the lamp. What the receiving hospital cannot
    # get any other way.
    "collect-evidence": [
        r"take the (bottle|container|lamp|pill|medication|product|injector|device)",
        r"bring (the )?(bottle|container|medication|pills?|sample|vomitus)",
        r"search the (medicine cabinet|garbage|trash|house|room|bag)",
        r"\bsave (the |any )?(vomitus|pill|container)",
        r"look for (other |empty )?(bottles?|containers?)",
    ],
    # Undressing and decontaminating the patient, and the rig afterwards.
    "decontaminate": [
        r"\bdecontaminat\w*", r"remove (the |his |her |their )?(contaminated )?(clothing|jeans|jewelry|shirt)",
        r"\bbrush(ing)? (off|at)\b", r"\birrigat\w*", r"cut (the )?(clothing|clothes)",
        r"wash (the )?(skin|patient|area)",
    ],
    # How you speak to this particular patient — a frightened child, someone who
    # will not understand "MI". Distinct from explaining a decision.
    "therapeutic-communication": [
        r"at (his|her|their) (own )?level", r"plain language", r"simple(,| and)? appropriate choices",
        r"\bcoach (him|her|them)\b", r"offer[^.]{0,20}choices",
        r"do not ask[^.]{0,30}(jargon|abbreviation)", r"\bage[- ]appropriate\b",
    ],
    "air-medical": [
        r"\bhelicopters?\b", r"\bair (medical|rescue|ambulance)\b",
        r"\baeromedical\b", r"\blanding zone\b",
        r"\bflight (crew|personnel|medics?|nurses?)\b",
        r"\btail rotor\b", r"\bfly (her|him|them|the patient)\b",
    ],
    "handover-report": [
        r"field diagnosis", r"\bhand[- ]?over\b", r"transfer of care",
        r"transfer\w*\s+(?:\w+\s+){0,2}care\b",
        r"repeat the digits", r"give assessment information",
        r"\bradio report\b", r"\bverbal report\b",
        r"obtain your release", r"release from the (hospital|emergency department)",
    ],
    "stroke-scale": [
        r"stroke scale", r"\bcincinnati\b", r"\bfast[- ]?ed\b", r"\bbe[- ]?fast\b",
        r"facial droop", r"arm drift", r"\bpronator drift\b",
    ],
    "temperature": [
        r"\btemperature\b", r"\btemp\b", r"\bfebrile\b", r"\bthermometer\b",
        r"take (a|her|his|their) temp",
    ],
    "onset-time": [
        r"last (known|seen) (to be )?(well|normal)", r"time of onset", r"onset time",
        r"when did (it|the symptoms?|this) (start|begin)",
        r"what time (did|were|was)[^.]{0,24}(start|begin|last)",
        r"how long (has|have)[^.]{0,20}(been|going on)",
    ],
    "hospital-notify": [
        r"(notify|alert|call|pre[- ]?notify|radio) (the )?(receiving )?(hospital|ed|emergency department|facility)",
        r"stroke alert", r"trauma alert", r"call (it|this) in as a",
        r"tell the (hospital|receiving)",
    ],
    # Examining the abdomen, which is its own skill with its own rules: the
    # painful quadrant last, and a pulsating mass felt once and never again.
    # `physical-exam` matched "palpate the abdomen" but not "palpate the
    # abdominal quadrants", which is how every abdominal call actually words it.
    "abdominal-exam": [
        r"palpate the abdom\w*", r"abdominal quadrants?", r"palpate (each|all four) quadrant",
        r"inspect the abdom\w*", r"\bguarding\b", r"\brigidity\b",
        r"pulsating mass",
    ],
    # Never give anything by mouth to a patient with an abdominal complaint.
    # A real order, and one that inverts when medical direction authorizes
    # aspirin on an epigastric pain that might be cardiac.
    "nothing-by-mouth": [
        r"nothing by mouth", r"\bnpo\b", r"nothing to (eat|drink)",
        r"no(t|thing)? .{0,12}(by|per) mouth", r"do not (give|allow) .{0,20}(eat|drink|orally)",
    ],
    # The questions a female patient of childbearing years is owed when the
    # complaint is abdominal. Kept out of `sample-history` deliberately: folding
    # them in would credit a trainee who said "SAMPLE history" with questions
    # they never asked, and an ectopic pregnancy is what goes unfound.
    "menstrual-history": [
        r"\bmenstrua\w*", r"\bperiod (is |was )?(late|normal|due)", r"last period",
        r"\bcould (you|she) be pregnant\b", r"possibility of pregnancy",
        r"vaginal bleed\w*", r"childbearing (years|age)",
    ],
    "physical-exam": [
        r"(head[- ]to[- ]toe|rapid|focused|secondary|detailed)[^.]{0,15}(exam|assessment|survey)",
        r"physical exam", r"\bdcap[- ]?btls\b", r"palpate the (abdomen|chest|neck)",
        # Examining one region is still a physical exam. The table carried the
        # names of the exams but not the act of examining a body part.
        r"\bexamine\b[^.]{0,20}\b(head|neck|chest|abdomen|back|pelvis|extremit|arm|leg|hand|foot|forehead|conjunctiva|eye|scalp|mouth)\b",
        r"\bassess (the )?(neck|head|scalp|chest wall|abdomen|pelvis|back)\b",
        r"expose (the )?(patient|chest)",
        # Looking the patient over for what they are wearing or carrying. Nothing
        # matched these before, so a trainee who read the medical ID bracelet on
        # scene got no credit for it — reported from a hypoglycemia call where the
        # bracelet was the point.
        r"medical (id|alert|identification)", r"\bmedic[- ]?alert\b",
        r"(id|alert|identification) (bracelet|necklace|tag|jewel?ry|card)",
        r"insulin pump", r"glucose meter", r"\bpill bottles?\b",
        r"compare\w*\s+[^.]{0,40}(with|to|against)\s+the\s+(un(injured|affected)|other|opposite|good)",
        r"(feel|palpat\w+)\s+(along|over|down)\s+the",
        r"palpat\w+[^.]{0,25}\b(length of|entire|whole)\b[^.]{0,15}spine",
    ],
    "reassess": [
        r"\breassess", r"re-?evaluat", r"repeat (the )?vitals",
        r"(recheck|check again)", r"trend",
        # "Monitor her airway continuously en route" is reassessment, said the
        # way the book says it.
        r"\bmonitor\b[^.]{0,45}\b(continuously|en route|closely|every|repeatedly)\b",
    ],

    # airway and oxygenation
    "airway-open": [
        r"open the airway", r"head[- ]tilt", r"chin[- ]lift", r"jaw[- ]thrust",
        r"(manage|secure|maintain|patent|ensure|establish)[^.]{0,15}airway",
        r"airway is (open|clear|patent)", r"\bopa\b", r"\bnpa\b",
        r"oropharyngeal airway", r"nasopharyngeal airway", r"airway adjunct",
    ],
    "suction": [r"suction", r"\byankauer\b", r"clear the (airway|mouth) of"],
    "oxygen": [
        r"\boxygen\b", r"\bo2\b", r"supplemental o", r"\bl/?min\b", r"liters? per minute",
    ],
    "oxygen-nc": [r"nasal cannula", r"\bnc\b(?![a-z])", r"\bcannula\b"],
    "oxygen-nrb": [
        r"non[- ]?rebreather", r"\bnrb\b", r"rebreather mask", r"\bnon rebreather\b",
    ],
    "oxygen-bvm": [
        r"bag[- ]valve", r"\bbvm\b", r"bag[- ]?mask", r"positive[- ]pressure ventilat",
        r"\bppv\b", r"assist(ed|ing)? ventilation", r"assist (his|her|their|the patient'?s) breathing",
    ],
    "ventilate": [
        r"ventilat", r"\bbreaths?/(min|minute)\b", r"\d+\s*(breaths?|vents?) per minute",
        r"bag (him|her|them|the patient)",
    ],

    # interventions
    "position": [
        r"position of comfort", r"recovery position",
        r"(position|place|put|roll|turn)\w*\s+(him|her|them|the patient)[^.]{0,25}\bon (his|her|their|the) side\b",
        r"lateral recumbent",
        r"(head down|pelvis raised|pelvis elevated|hips elevated)",
        r"(on|onto) (his|her|their) left side",
        r"lower (her )?legs and keep them together", r"(sit|sitting)[^.]{0,15}(up|upright)",
        r"fowler", r"supine", r"left lateral", r"\btripod\b", r"lay (him|her|them) (flat|down)",
        r"elevate the (legs|head)", r"head (of the bed )?(at|to|up) \d{1,2} degrees",
        r"\bhead\b[^.]{0,20}\d{1,2} degrees",
        r"as a (single )?unit", r"move the body as a unit", r"log[- ]?roll",
        r"keep\s+(him|her|them|the patient)\s+(at rest|still)",
        r"(lean|leaning) forward",
    ],
    "spinal-motion-restriction": [
        r"spinal (motion restriction|precautions|immobiliz)", r"\bsmr\b",
        r"manual\w*\s+in[- ]?line\s+stabiliz",
        r"manual\w*\s+stabiliz\w*[^.]{0,20}\b(head|neck|c[- ]?spine|cervical)\b",
        # Naming the anatomy is the usual phrasing but not the only one: "Keep
        # manual stabilization until the patient is fully secured" is spinal
        # care with no anatomy word in reach. Requiring one dropped that line
        # silently when this pattern was tightened for source 33. The lookahead
        # keeps out what the tightening was actually defending against —
        # "manually stabilize the forearm", which is splinting.
        r"manual\w*\s+stabiliz\w*(?![^.]{0,40}\b(forearm|upper arm|arm|leg|limb|wrist|ankle|knee|femur|humerus|hand|foot|elbow|shoulder|pelvis|hip)\b)",
        r"c[- ]?collar", r"cervical collar",
        r"backboard", r"stabiliz\w*\s+(the|his|her|their)\s+(head|neck|c[- ]?spine)",
        r"(limit|restrict|stop)\w*\s+[^.]{0,25}\b(spine|spinal|head|neck)\b[^.]{0,15}\b(movement|moving|still)\b",
        r"(stop|avoid) moving (his|her|their|your) (head|neck|spine)",
        r"(vacuum mattress|scoop stretcher|orthopedic stretcher)",
        r"secure\s+(the\s+patient|him|her|them)?\s*(to|onto)\s+the\s+(long\s+)?(spine\s+)?board",
        r"long spine board", r"scoop[- ]?style stretcher",
    ],
    "bleeding-control": [
        r"direct pressure", r"tourniquet", r"control (the )?bleeding", r"hemorrhage control",
        r"pressure dressing", r"wound packing", r"occlusive dressing",
    ],
    "medication-assist": [
        r"assist[^.]{0,25}(inhaler|medication|epi|nitro)", r"\bmdi\b", r"metered[- ]dose",
        r"\bepi[- ]?pen\b", r"auto[- ]?injector", r"nitroglycerin", r"\bnitro\b",
        r"\baspirin\b", r"oral glucose", r"\bnaloxone\b", r"\bnarcan\b",
        r"administer[^.]{0,20}(albuterol|epinephrine|glucose|aspirin)",
    ],
    "cpr": [
        r"\bcpr\b", r"chest compressions?", r"start compressions", r"cardiac arrest care",
    ],
    "aed": [r"\baed\b", r"defibrillat", r"apply (the )?pads", r"analyze the rhythm"],
    "thermal-care": [
        r"(keep|maintain)[^.]{0,20}warm", r"passive (re)?warming", r"prevent (heat loss|hypothermia)",
        r"active cooling", r"cool the patient", r"remove[^.]{0,20}(wet clothing|from the heat)",
        # A blanket warms only when it is being used to warm. Bare \bblanket\b
        # also matched "a folded blanket between her legs", which is splint
        # padding — and, being singular, missed "cover him with blankets"
        # entirely. Fourth plural of this shape to need fixing.
        r"(cover|wrap|warm|insulat)\w*[^.]{0,25}\bblankets?\b",
        r"cold pack", r"ice pack", r"apply (a )?cold",
        # Source 35 is the first source where thermal care *is* the treatment
        # rather than a comfort measure, and it brought vocabulary nothing had:
        # a vapor barrier, cutting clothing away, wetting and fanning a heat
        # stroke patient, and knowing when to stop.
        r"vapor barrier",
        r"cut(ting)? away[^.]{0,30}cloth",
        r"remov\w*[^.]{0,25}insulating (layers?|cloth)",
        r"\bfan(ning|s)?\s+(him|her|them|the patient)\b",
        r"wet\w*\s+(him|her|them|the patient|the skin)\b[^.]{0,15}\bdown\b",
        r"wet\w*\s+(his|her|their|the)\s+skin",
        r"(stop|cease|halt)\w*\s+cooling",
        r"(evaporative|convective) cooling",
        r"(cold[- ]water immersion|immersive cooling)",
        r"moist towels?",
        r"off the cold (floor|ground|tile)",
    ],

    # disposition and admin
    "als": [
        r"\bals\b", r"advanced life support", r"\bparamedic", r"\bintercept\b",
        r"upgrade the response",
    ],
    "transport": [
        r"\btransport\b", r"(to|nearest)[^.]{0,20}(hospital|trauma center|facility)",
        r"load (and go|the patient)", r"\bpriority (transport|1|one)\b", r"\bexpedite\b",
    ],
    "medical-direction": [
        r"medical (direction|control|command)", r"contact (the )?(doctor|physician|base)",
        r"online medical",
    ],
    "consent-refusal": [
        r"\bconsent\b", r"\brefus", r"right to refuse", r"implied consent",
        r"against medical advice", r"\bama\b",
    ],
    "documentation": [
        r"\bdocument", r"\bpcr\b", r"patient care report", r"hand[- ]?off report",
        r"\bradio report\b", r"notify the (hospital|receiving)",
        r"(call|notify|contact|alert)\w*\s+(the\s+)?(trauma cent(er|re)|receiving|hospital|ed|emergency department)",
        r"(early|advance|incomplete) report", r"arrival time", r"\beta\b",
    ],

    # ── musculoskeletal (source 32) ──────────────────────────────────────────
    #
    # Source 32 arrived with 40% of its rubric lines carrying no intent at all,
    # because the table had never needed a word for splinting. `pulse-check` was
    # the only musculoskeletal thing in it.

    #: The check that brackets every splint in the source — before, after, and
    #: again en route. Deliberately broad on how it is said: "check CSM", "check
    #: circulation sensation and movement", "can you feel me touching your toes".
    "distal-csm-check": [
        r"\bcsm\b",
        r"circulation,? sensation,? and (motor|movement)",
        r"(check|assess|reassess|recheck)\w*\s+(the\s+)?(distal|circulation|pulses?|sensation|movement|feeling)"
        r"[^.]{0,40}\b(distal|below|past|beyond|foot|feet|hands?|fingers?|toes?|wrist|ankle|extremit(y|ies)|limbs?)\b",
        # `radial` is deliberately absent: taking a radial pulse is how source
        # 13 teaches measuring a rate, not a distal check after a splint. A real
        # distal check still matches on the verb pattern above.
        r"\b(distal|pedal|posterior tibial|dorsalis pedis)\s+(pulse|circulation|function)",
        r"(feel|sense|wiggle)\s+(your|the|his|her)?\s*(fingers?|toes?)",
        r"\bsix\s+p'?s\b",
        r"grip strength",
        r"(sensation|movement|feeling)[^.]{0,30}\ball four\b",
    ],
    #: Any splint, by device or by act. Excludes the traction splint, which has
    #: its own entry because its indications are narrow and its misuse is a
    #: critical error rather than a lost point.
    "splint": [
        # Splinting has to be something done, not something listed. "Check all
        # interventions (oxygen, bleeding control, collar/splints)" is a
        # reassessment line, and "working around the splints" is an exam line;
        # a bare \bsplint made both of them demand a splint from the trainee.
        # `full[- ]body splint` and `as a … splint` are kept deliberately — on a
        # long board the board *is* the splint (src32-s10, src34-s04).
        r"\bsplint(ed|ing|s)?\s+(the|his|her|their|it|him)\b",
        r"(apply|applies|applied|applying|place|placing|placed|secure|securing|use|using|improvis\w+)\b[^.]{0,30}\bsplint",
        r"full[- ]body splint",
        r"\bas a\b[^.]{0,20}\bsplint",
        r"\bsplint(ed|ing)\b",
        r"immobiliz\w*\s+(the\s+)?(\w+\s+){0,2}(injur\w+|fracture|limb|extremity|arm|leg|forearm|ankle|knee|joint|wrist|thigh|hand|foot)",
        r"(manual\w*\s+)?stabiliz\w*\s+(the\s+)?(\w+\s+){0,2}(injur\w+|limb|extremity|arm|leg|forearm|ankle|knee|joint|wrist|thigh|site)",
        r"(place|lower|tie|secure|rest)\s+(the\s+)?(limb|leg|arm|ankle|foot)\s+[^.]{0,20}\bpillow",
        r"pillow (lengthwise )?under the",
        r"tie the pillow",
        r"(rigid|padded|vacuum|formable|board|pillow|soft|traction)\s+splint",
        r"padded board",
        # "bind them together" is the commoner phrasing and was missed, which
        # left the src34-s02 pelvic-binding step carrying no splint intent.
        r"bind (the |her |his |their )?(legs|them) together",
        r"secure the (limb|leg|arm) to",
        r"\bpad the voids?\b",
        r"position of function",
    ],
    #: The femur splint. Separate from `splint` because "apply a traction splint"
    #: over a pelvis, hip or knee injury is a different mistake from splinting
    #: badly, and a scenario needs to be able to forbid it by name.
    "traction-splint": [
        r"traction splint", r"\bhare\b", r"\bsager\b", r"fernotrac", r"kendrick",
        r"bipolar|unipolar", r"ankle hitch", r"ischial (strap|securing)",
        r"mechanical traction",
    ],
    #: Realigning an angulated long bone, and the manual traction that holds it.
    #: Not the same as the traction splint: this is hands, not a device.
    "manual-traction": [
        r"manual traction", r"gentle traction", r"realign", r"re-?align",
        r"straighten\w*\s+(the\s+)?(angulat|deform|limb|extremity|arm|leg)",
        r"traction (along|in the direction of) the",
        # "anatomic position" alone is not traction. Source 5 uses the phrase
        # for the anatomical reference posture — "Base the description on
        # anatomic position" — so an aligning verb and a preposition of motion
        # have to be there. `in` as well as `to`: src32-s10 aligns limbs *in* it.
        r"(align|realign|return|restore|bring|move|place)\w*\s+[^.]{0,40}\b(in|into|to)\s+(the\s+)?anatomic(al)? position",
    ],
    "sling-and-swathe": [
        r"sling", r"swathe", r"triangular bandage",
    ],
    #: Closing an unstable pelvis. Kept apart from `splint` because it is done
    #: on the pelvis rather than a limb, and because it is indicated on
    #: deformity or instability regardless of whether shock has appeared.
    "pelvic-wrap": [
        r"pelvic (wrap|binder|sheet|splint)", r"wrap the pelvis", r"bind the pelvis",
        r"greater trochanter",
    ],

    # ── head and spine (source 33) ────────────────────────────────────────────

    #: Scoring and — the part that matters — re-scoring the Glasgow Coma Scale.
    #: The source is explicit that a single number is somewhat subjective and
    #: that the trend is what counts: a fall of two points is critical. So the
    #: patterns take the recalculation as readily as the first calculation.
    #: Leaving a helmet on is as much a decision as taking it off, and the
    #: source grades both — so the patterns take either.
    "helmet-removal": [
        # Not a bare `helmet`: src11-s10 has the EMT donning one as PPE on a
        # highway scene, which is not this decision at all.
        r"(remove|removing|removal of|leave|leaving|keep|take off)\w*\s+(the\s+)?helmet",
        r"helmet\s+(on|off|in place|stays|remains)",
        r"(motorcycle|football|hockey|lacrosse|sport\w*|bicycle|ski)\s+helmet",
        r"face guard", r"chin strap", r"shoulder pads",
    ],
    #: The five questions that decide whether the spine is restricted at all.
    "nexus-spinal-assessment": [
        r"\bnexus\b",
        r"(reliable|unreliable)\b[^.]{0,30}(patient|him|her|them)|patient is (reliable|unreliable)",
        r"establish\w*\s+[^.]{0,30}\b(reliable|not intoxicated|sober)\b",
        r"distracting injur",
        r"midline\s+(spinal|neck|back|cervical)?\s*(pain|tenderness)",
        r"focal neurologic",
    ],
    #: Field triage — deciding the destination against the red and yellow
    #: criteria. Distinct from `transport`, which only says the patient is going
    #: somewhere, and from `recognize-condition`, which fires on the verb
    #: regardless of what is being recognized.
    "trauma-triage": [
        # Every pattern here needs triage vocabulary in it. An earlier draft
        # matched any "systolic below 90" and any "meets criteria", which swept
        # up the nitroglycerin contraindication in src18-s02 and src20-s02 and the
        # burn-center criteria in src30-s06 — none of which are field triage.
        r"\b(red|yellow)\b[^.]{0,20}\bcriteri",
        r"triage criteri|trauma triage|field triage",
        r"(meets?|meeting|does not meet)\b[^.]{0,25}\b(red|yellow|triage)\b[^.]{0,20}criteri",
        r"trauma cent(er|re)\b[^.]{0,40}\b(rather than|instead of|not the|bypass)",
        r"(rather than|instead of|bypass\w*)\b[^.]{0,40}\btrauma cent(er|re)",
        r"(pulse|heart rate)[^.]{0,25}(higher|greater|more) than[^.]{0,15}systolic",
        r"systolic[^.]{0,20}\b(below|under)\b[^.]{0,10}\b110\b",
        r"70 plus twice|threshold for (his|her|their) age|below the threshold",
        r"pediatric[- ]capable",
        r"highest[- ]level trauma cent",
    ],
    #: Keeping a parent or caregiver with the patient. A child who is frightened
    #: and separated is harder to assess, and the source asks that families
    #: travel together where the ambulance allows it. Deliberately narrow: it
    #: needs a family word AND a word about them coming along, so "his mother
    #: says he fell" and the rest of the history taken from relatives do not
    #: match.
    "family-presence": [
        r"(bring|take|allow|let|have|keep)\w*\b[^.]{0,30}\b(mother|father|mom|dad|parent|caregiver|famil|guardian)\w*\b[^.]{0,40}\b(with|along|come|ride|travel|in the ambulance|accompany|beside|present)",
        r"\b(mother|father|mom|dad|parent|caregiver|famil|guardian)\w*\b[^.]{0,30}\b(ride|rides|travel|comes? (with|along)|accompany|accompanies)\b",
        r"(do not|don't|avoid)\b[^.]{0,25}\bseparat\w*\b[^.]{0,30}\b(mother|father|parent|caregiver|famil|guardian|child)",
        r"transport (the )?famil\w* together",
        r"\bwith\b[^.]{0,15}\b(mother|father|mom|dad|parent|caregiver|guardian)\b[^.]{0,20}\b(beside|alongside|next to|present)",
    ],
    #: Moving a patient as though the movement itself could kill them, because
    #: in a cold one it can: low temperature lowers the ventricular fibrillation
    #: threshold and rough handling can set off a fatal dysrhythmia. Deliberately
    #: does not match "palpate gently" — this is handling, not touch.
    "gentle-handling": [
        r"handl\w*\s+(the patient|him|her|them)?\s*gently",
        r"gentle\s+handling",
        r"(avoid|without|no)\s+rough handling",
        r"rough handling",
        r"gently\s+(move|lift|roll|transfer)",
        r"(move|lift|roll|transfer)\w*\s+(him|her|them|the patient)\s+gently",
    ],
    #: Rings, jewelry and boots off before the limb swells around them. Already
    #: earned by the source 30 burn scenarios; source 35 adds frostbite and
    #: snakebite, where the swelling is the whole reason for the hurry.
    "remove-constriction": [
        r"remov\w*\s+[^.]{0,35}\b(rings?|jewel\w+|bracelets?|anklets?|watch|boots?|socks?|straps?)\b",
        r"\b(rings?|jewelry|bracelets?)\b[^.]{0,30}\bbefore\b[^.]{0,25}swell",
        r"loosen\w*\s+[^.]{0,30}\b(clothing|ties|belts?|collars?)\b",
    ],
    #: Getting the patient down the mountain, which for high-altitude cerebral
    #: edema is the treatment rather than the transport. Anchored to altitude
    #: words: an earlier draft matched "carry her down in a stair chair".
    "descent": [
        r"\bdescen[dt]\w*",
        r"(get|move|take|bring|carry)\w*\s+(him|her|them|the patient)\s+(down|to a lower)[^.]{0,30}(altitude|mountain|elevation)",
        r"lower altitude",
    ],
    #: Fluids by mouth — warm ones for a cold-stressed patient, small sips for
    #: heat exhaustion. The mirror of `nothing-by-mouth`, which already existed.
    "oral-fluids": [
        r"(give|offer|provid\w+|allow)\w*\s+[^.]{0,35}\b(sips?|water|sports drink|oral fluids?|warm liquids?)\b",
        r"\bsmall sips\b",
        r"\bwarm (liquids?|fluids?|drinks?)\b",
        r"rehydrat\w*",
    ],
    #: Hands on the baby during a birth. Every pattern needs a birth object,
    #: because "deliver" also means delivering back slaps — src9-s07 says
    #: "supporting the head, and deliver 5 back slaps", which an earlier draft
    #: read as an obstetric step.
    "assist-delivery": [
        r"support\w*\s+[^.]{0,30}\b(head|trunk|pelvis)\b[^.]{0,40}\b(delivers\b|delivery of the|birth|crown\w*)",
        r"\b(head|shoulder|trunk|pelvis)\b[^.]{0,25}\bas it delivers\b",
        r"aid\w*\s+(in\s+)?the (birth|delivery) of",
        r"keep\w*\s+the (infant|baby)\s+level",
        r"(stop|not to)\s+push\w*|\bpant\b",
        r"perineum|between the vagina and anus",
        r"prevent\w*\s+[^.]{0,25}(explosive|uncontrolled) (delivery|expulsion)",
        r"push\w*\s+up\s+on\s+the\s+(presenting part|baby|head|buttocks)",
        r"check\w*\s+(whether|if)[^.]{0,25}\bplacenta\b",
        r"(deliver|delivery) of the placenta",
    ],
    #: The umbilical cord — checking it at the neck, when to clamp and cut, and
    #: watching a cut end for bleeding.
    "cord-care": [
        r"\bcord\b[^.]{0,30}(around|wrapped)[^.]{0,20}neck",
        r"(clamp|cut)\w*\s+[^.]{0,25}\bcord\b",
        r"\bcord\b[^.]{0,25}(stops? )?pulsat",
        r"cut end of the (umbilical )?cord",
        r"another clamp",
    ],
    #: Heat loss in a newborn drops glucose and impairs oxygen carriage, so
    #: drying and wrapping are treatment rather than comfort. Distinct from
    #: `thermal-care`, which is about a patient losing heat to an environment.
    #: Drying needs a towel or blanket nearby: src35-s07 dries a chest for AED
    #: pads, which is not warming anybody.
    "newborn-warming": [
        r"dry\w*\s+(the\s+)?(baby|infant|neonate|him|her)\b[^.]{0,45}(towel|blanket|swaddl|warm|dry one)",
        r"discard\w*\s+(the\s+)?wet\s+(towel|blanket|linen)",
        r"(cover|cap|put a cap)\w*\s+[^.]{0,25}(baby'?s?|infant'?s?|his|her)\s+head",
        r"skin to skin",
        r"heat\w*\s+the (patient )?compartment",
        r"wrap\w*\s+(the\s+)?(baby|infant|neonate|him|her)\b[^.]{0,30}(dry|warm|blanket|towel)",
    ],
    #: A pad over the vaginal opening, which is the only thing that ever goes
    #: there — the source repeats "do not place anything in the vagina" in
    #: four separate places.
    "perineal-pad": [
        r"sanitary (napkin|pad)",
        r"\bpad\b[^.]{0,25}vaginal opening",
    ],
    #: Making the uterus contract after delivery, which is what stops the
    #: bleeding. Needs a massage word or the hand placement: src21-s09 notes
    #: fundal height in a cardiac arrest and is not massaging anything.
    "uterine-massage": [
        r"massag\w*[^.]{0,25}(uterus|fundus)",
        r"(uterus|fundus)[^.]{0,25}massag",
        r"grapefruit[- ]sized",
        r"uterine massage",
        r"(cup|place)\w*\s+(one|the other|your)\s+hand[^.]{0,60}(fundus|pubic bone)",
    ],
    #: Scoring the newborn. A record rather than a trigger — resuscitation is
    #: decided on tone, breathing and heart rate and starts before any score.
    "apgar": [r"\bapgar\b"],
    #: Pads and passed tissue travel with the patient. Evidence of blood loss
    #: and material the hospital needs, not tidying up.
    "specimen-collection": [
        r"(collect|save|bring|keep)\w*\s+[^.]{0,30}\b(pads?|tissue|specimen)\b",
        r"blood[- ]soaked pads?",
    ],
    #: Finding out what normal looks like for *this* patient. Traditional norms
    #: are often not normal for a patient with special healthcare needs, and the
    #: patient or caregiver is usually the only source of the baseline. The
    #: corpus has been writing this since source 10 with nothing to grade it.
    "establish-baseline": [
        r"what (is|'s) (different|changed|normal)",
        r"what (is|'s) normal for (him|her|them|this patient)",
        r"(ask|asking)\w*\s+[^.]{0,40}\b(baseline|normal for)\b",
        r"has changed (today|since)",
    ],
    #: Working the machine rather than the patient — power, batteries, caps,
    #: tape, and the circuit. Source 37 is full of it; src21-s10 already had it
    #: for an LVAD.
    "device-troubleshoot": [
        r"(plug|plugg\w+)\s+(the|it|unit)[^.]{0,30}(socket|outlet|inverter|ac source)",
        r"(replace|change|swap)\w*\s+[^.]{0,20}batter",
        r"spare batter|alternate batter",
        r"(cap|capping)\w*\s+the tube",
        r"secure\w*\s+[^.]{0,25}(with tape|to (his|her|their) body)",
        r"look\w*\s+(along|at)\s+the (circuit|tubing|line)[^.]{0,30}(kink|wheel|clear)",
        r"take the tension off|tug\w*\s+on the",
        r"read\w*\s+the (control panel|display|alarm)",
    ],
    #: Turning the environment down for a patient who cannot filter it. Calm
    #: creates calm, and a show of force is counterproductive here. Deliberately
    #: does not match moving a patient away from a crowd for infection control,
    #: which is what src24-s05 does.
    "sensory-calm": [
        r"(send|clear|disperse)\w*\s+[^.]{0,35}(bystanders?|the other children|unnecessary (adults|personnel|people))",
        r"turn (off|down)\w*\s+the\s+[\w ]{0,20}lights?\b",
        r"do not tell (him|her|them)[^.]{0,15}calm down",
        r"(one|a single) (person|responder|provider)\s+(approach|make direct contact)",
        r"do not ask (him|her|them)[^.]{0,25}(to stop|stop rocking|flapping|stimming)",
        r"tell\w*\s+(him|her|them)\s+(exactly\s+)?what you (are going to|will) do",
        r"begin the (interaction|assessment) where",
        r"take a break",
        r"\b(give|offer|hand)\w*\s+(him|her|them|the child)\s+(a |the )?(toy|teddy|stuffed)",
    ],
    #: The reporting obligation, and the discipline around it: suspicion goes to
    #: the agency and never to the scene. Narrower than `documentation`, which
    #: src17-s08 uses for record-keeping ethics.
    "mandated-report": [
        r"report\w*\s+[^.]{0,60}(mandated|state hotline|appropriate (government )?agency|social service)",
        r"notify\w*\s+law enforcement",
        r"using the words suspected and possible",
        r"do not (tell|indicate|reveal|accuse)[^.]{0,45}(suspect|suspicion)",
    ],
    #: Covering a wound. Eleven approved lines across eight sources apply a
    #: dressing or a bandage and none of them graded — a category the corpus had
    #: been writing since source 28 with nothing to see it. `bleeding-control`
    #: already covers the occlusive dressing and the pressure that stops
    #: bleeding; this is the covering itself.
    "dressing": [
        r"(apply|appli\w+|cover|covering|place|placing|wrap|wrapping|dress)\w*\s+[^.]{0,40}\b(sterile\s+)?dressings?\b",
        r"\bbandag(e|es|ed|ing)\b",
        r"(dry sterile|moist|hemostatic|trauma|burn) dressing",
        r"burn sheet",
    ],
    "glasgow-coma-scale": [
        r"glasgow", r"\bgcs\b",
        r"coma scale",
    ],
}

_COMPILED = {
    intent: [re.compile(p, re.IGNORECASE) for p in patterns]
    for intent, patterns in _TABLE.items()
}

#: Ways of naming a saturation *reading*. These contain the word "oxygen" but
#: are a measurement, not a treatment.
#:
#: "what is the respiratory rate, pulse oxygen and blood pressure" scored two
#: critical `oxygen-device-missing` errors in a real session — the rule that
#: exists to catch a genuinely dangerous omission fired on someone asking for a
#: pulse ox, and took the score to 0. The oxygen family is now matched against
#: the text with these phrases removed, so asking for a number never reads as
#: ordering a gas.
_SATURATION_PHRASE_RE = re.compile(
    r"\bpulse\s*ox(?:imetry|imeter|ygen)?\b"
    r"|\boxygen\s*(?:saturation|sats?|level)\b"
    r"|\bo2\s*(?:saturation|sats?|level)\b",
    re.IGNORECASE,
)

#: Intents whose patterns must not see a saturation phrase.
_OXYGEN_FAMILY = frozenset({"oxygen", "oxygen-nc", "oxygen-nrb", "oxygen-bvm"})

INTENTS = tuple(_TABLE)

#: The five items the NREMT scene size-up is scored on.
SIZE_UP_ITEMS = (
    "scene-safety",
    "bsi",
    "patient-count",
    "moi-noi",
    "additional-resources",
)

#: Oxygen delivery devices. Naming two different ones for the same action is a
#: clinical disagreement, not a wording difference.
OXYGEN_DEVICES = ("oxygen-nc", "oxygen-nrb", "oxygen-bvm")

#: Accepted flow rate range in L/min for each device, per the standing rule that
#: every oxygen order must name a device *and* a rate.
DEVICE_FLOW_RANGE = {
    "oxygen-nc": (2, 6),
    "oxygen-nrb": (12, 15),
    "oxygen-bvm": (15, 15),
}

#: The four intents that each name one number. Three or more of them in a single
#: breath is a request for the whole set.
_NAMED_VITALS = frozenset({"pulse-check", "breathing-assess", "vitals-bp", "vitals-spo2"})

#: Vital signs the EMT has to go and get. Skin color, work of breathing,
#: posture and level of consciousness are deliberately absent: you can see those
#: from the doorway, so the sim never withholds them.
GATED_VITALS = ("rr", "hr", "spo2", "bp")

#: Which numbers an intent earns the EMT. You do not see a blood pressure you
#: never took.
VITAL_REVEALS = {
    "vitals-full": ("rr", "hr", "spo2", "bp"),
    "vitals-bp": ("bp",),
    "vitals-spo2": ("spo2",),
    "pulse-check": ("hr",),
    "breathing-assess": ("rr",),
}

#: Intents that gather information rather than change anything. Answering one of
#: these with "Done." claims the sim carried out an instruction that was really a
#: question, which is how a trainee learns to distrust everything it says.
ASSESSMENT_INTENTS = frozenset({
    "abdominal-exam", "breathing-assess", "general-impression", "glucose-check",
    "menstrual-history", "mental-status", "moi-noi", "opqrst", "patient-count",
    "physical-exam", "pulse-check", "reassess", "sample-history", "scene-safety",
    "vitals", "vitals-bp", "vitals-full", "vitals-spo2",
})


#: Asking, narrated rather than spoken: "ask him if he has any heart history".
#:
#: A trainee describing what they would do is as common as one saying the words,
#: and the two mean the same thing. Without this the narrated form has no
#: interrogative opening word, so it read as an instruction, earned a `RESULT`,
#: and came back "Done." — a question the patient was never asked, and one no
#: persona could answer, because `RESULT` never reaches a persona.
#:
#: `ask` alone would be too greedy. "Ask for ALS" and "ask dispatch for a second
#: unit" are radio traffic, not questions put to the patient, so what may follow
#: is listed rather than left open.
_NARRATED_ASK_RE = re.compile(
    r"^\s*(?:ask|find out|inquire)\b\s*"
    r"(?:him|her|them|the (?:patient|wife|husband|mother|father|family|bystander)|"
    r"about|if|whether|what|when|where|why|how|which)\b",
    re.IGNORECASE,
)

_QUESTION_RE = re.compile(
    r"\?\s*$"
    r"|^\s*(?:what|where|when|why|how|who|which|is|are|was|were|does|do|did|can|could|"
    r"should|would|has|have|any|tell me)\b",
    re.IGNORECASE,
)


def is_question(text: str) -> bool:
    """Whether the EMT asked rather than acted.

    Two shapes count: the question itself ("does he have any heart history?")
    and the narration of asking it ("ask him if he has any heart history").
    """
    text = (text or "").strip()
    return bool(_QUESTION_RE.search(text) or _NARRATED_ASK_RE.match(text))


def is_action(text: str) -> bool:
    """Whether this turn does something, as opposed to asking or looking.

    Shape first, then intent: "what do I do" carries no intent at all but is
    plainly not an instruction, and answering it "Done." is how a trainee learns
    to distrust everything the sim says.
    """
    if is_question(text):
        return False
    intents = classify(text)
    return bool(intents - ASSESSMENT_INTENTS) if intents else True


#: Intents whose omission is never merely a lost point.
CRITICAL_INTENTS = frozenset(
    {"airway-open", "oxygen-bvm", "ventilate", "suction", "bleeding-control", "cpr"}
)

_FLOW_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:l|liters?)\s*(?:/|\s+per\s+)?\s*min", re.IGNORECASE)
_LITERS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:l\b|liters?\b)", re.IGNORECASE)

# A prohibition is only a prohibition when the negation opens the line. Mid-line
# negations ("do NOT withhold oxygen") are usually positive guidance, and
# "Do not wait — immediately begin PPV" is an instruction to act, so only the
# clause before the first dash/semicolon/period is treated as forbidden.
_PROHIBITION_RE = re.compile(r"^\s*(?:do not|don't|never|avoid)\b(.*)$", re.IGNORECASE)
_CLAUSE_SPLIT_RE = re.compile(r"\s*[—;.]|\s+-\s+")


def classify(text: str) -> frozenset[str]:
    """Return the intent tags present in a line of English.

    Works on either side of the comparison: an EMT's spoken turn or a scenario's
    ``## Correct actions`` line.
    """
    if not text:
        return frozenset()
    without_saturation = _SATURATION_PHRASE_RE.sub(" ", text)
    found = {
        intent for intent, pats in _COMPILED.items()
        if any(p.search(without_saturation if intent in _OXYGEN_FAMILY else text)
               for p in pats)
    }
    # A named device implies oxygen even when the word never appears.
    if found & set(OXYGEN_DEVICES):
        found.add("oxygen")
    # Likewise, asking for one specific number is asking for vitals.
    if found & {"vitals-full", "vitals-bp", "vitals-spo2"}:
        found.add("vitals")
    # Naming most of the set *is* asking for a full set, even without the words
    # "vital signs". "Pulse, respiratory rate, SpO2 and blood pressure" was being
    # scored as three separate requests and failing the "full set" rubric line.
    if len(found & _NAMED_VITALS) >= 3:
        found |= {"vitals", "vitals-full"}
    # Recognition only counts when it is the whole step. "Recognize inadequate
    # breathing *and begin assisted ventilation*" is a ventilation step; leaving
    # the tag on diluted its coverage, so a correct answer stopped being a full
    # hit and a scripted perfect call could no longer score 100.
    if "recognize-condition" in found and len(found) > 1:
        found.discard("recognize-condition")
    return frozenset(found)


def revealed_vitals(intents: frozenset[str]) -> frozenset[str]:
    """The gated vitals these intents entitle the EMT to know."""
    return frozenset(
        key for intent in intents for key in VITAL_REVEALS.get(intent, ())
    )


#: Prohibitions whose object is an abstraction rather than an action. "Do not
#: give ipecac" forbids something the trainee could do; "Do not delay
#: epinephrine to finish the history" forbids a *tendency*, and is the
#: commentary shape a reviewer objected to. The first is a step; the second is
#: an ordering rule that belongs in the numbering.
_ABSTRACT_PROHIBITION = re.compile(
    r"^\s*(do not|don't|never|avoid)\s+"
    r"(delay|assume|hesitate|forget|neglect|underestimate|rely|be\b|let\b|allow)",
    re.IGNORECASE,
)


def is_prohibition(action_line: str) -> bool:
    """Does this line forbid something, whatever the something is?

    `prohibited_intents` returns the intents being forbidden, which is empty
    when the object has no category — "Do NOT give syrup of ipecac" forbids a
    drug the table does not know. The line is still a legitimate step written in
    a legitimate form, and 39 of the corpus's lines are this shape, so the
    authoring gate asks the shape question rather than the intent question.
    """
    if _ABSTRACT_PROHIBITION.match(action_line):
        return False
    return bool(_PROHIBITION_RE.match(action_line.strip()))


def prohibited_intents(action_line: str) -> frozenset[str]:
    """Intents an action line forbids, for lines that open with a negation.

    ``"Do NOT begin positive pressure ventilation while there is vomitus…"``
    yields ``{oxygen-bvm, ventilate}``. ``"Do not wait — immediately begin
    ventilation"`` yields nothing, because only the clause before the dash is
    read as the prohibition and "wait" carries no intent.
    """
    match = _PROHIBITION_RE.match(action_line.strip())
    if not match:
        return frozenset()
    return classify(_CLAUSE_SPLIT_RE.split(match.group(1), maxsplit=1)[0])


#: Words that open a subordinate clause naming a *reference point* rather than
#: an instruction. "…again after administering nitroglycerin" says when to
#: recheck; it does not administer anything.
_SUBORDINATE_RE = re.compile(
    r"\b(?:after|once|before|when|whenever|while|following|since|until)\b",
    re.IGNORECASE,
)


def spoken_intents(text: str) -> frozenset[str]:
    """What the EMT *did*, dropping anything they only referred to.

    `classify` reads a whole line at once, so a drug named anywhere in it counts
    as given. That cost an EMT a critical error for saying "I will check his
    vitals again after administering nitroglycerin" — a plan to reassess, scored
    as assisting with a contraindicated drug for the second time. The word was
    there; the act was not.

    Only a subordinate clause that *follows* a main clause is dropped, and only
    when there is a main clause to fall back on, so an instruction never
    disappears:

        "I'll recheck vitals after giving nitro"  → the recheck, not the nitro
        "Give him nitro after you check the BP"   → still gives nitro
        "assist him with his nitroglycerin"       → unchanged

    This is the same move `prohibited_intents` already makes for "Do not wait —
    immediately begin ventilation": read the clause that carries the verb, not
    every word in the sentence.
    """
    text = (text or "").strip()
    match = _SUBORDINATE_RE.search(text)
    if not match:
        return classify(text)
    main = text[: match.start()].strip()
    # Clause-initial ("After giving nitro, recheck") has no main clause before
    # the marker, and nothing to prefer — read the line whole, as before.
    if not main:
        return classify(text)
    return classify(main)


def flow_rate(text: str) -> float | None:
    """The oxygen flow rate in L/min named in the text, if any."""
    match = _FLOW_RE.search(text) or _LITERS_RE.search(text)
    return float(match.group(1)) if match else None


def named_device(intents: frozenset[str]) -> str | None:
    """The oxygen delivery device named, or None if the intents name none."""
    for device in OXYGEN_DEVICES:
        if device in intents:
            return device
    return None
