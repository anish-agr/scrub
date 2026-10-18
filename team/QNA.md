# Judge Q&A

Short, true answers. Three instruments: scalpel, hemostat, Mayo scissors. Research prototype, no clinical claims.

Our own numbers come only from `team/FACTS-0718.md` (ledger, dataset, logs). If a number isn't there, say "we didn't measure that" and don't guess. Outside numbers are the ones sourced in `team/PITCH.md` and `team/CONTEXT.md` Part 1, section 4.

Who answers: Anish (arm, training, business), Caiden (voice, station, safety), Brandon (vision), Evan (data, hosting). Anyone can start; the owner finishes.

## The hard ones

| # | Question | Answer | Who |
| --- | --- | --- | --- |
| 1 | Is the model fine-tuned? What runs the pick? | The pick you see is a skill we taught it. We recorded our own demonstrations of each pick on this arm with a leader arm. When you ask for an instrument, the arm plays the average of those demonstrations, speed-capped. We also started a Perceptron training run on the same demonstrations. That's separate: no model was deployed when we filmed, so no pick in the video or at the table is a model pick | Anish |
| 2 | Why no hand tracking? | The camera frame rate is too low to track a moving hand safely. Our wrist camera runs at about 22 frames a second and we wanted 30. So the arm doesn't chase the hand. It goes to a fixed handoff point, slows as it nears it, and holds the instrument out until you pull | Caiden |
| 3 | What about sterility? | Scrub never touches the patient and is a research prototype. A clinic version would run under a sterile drape on a medical-grade arm, like today's surgical robots, with trays and tools sterilized as usual. We don't claim it's sterile | Anish |
| 4 | What happens if it gets hot? | It reads every motor's temperature every 2 seconds. The page warns at 55 C. At 60 C it stops the run, goes home and turns its motors off. It can run again once every motor is back to 50 C. Above 52 C its moves also take 1.6 times longer, and the gripper eases open at 62 C. Holding a tool still is what heats the motors most, so it doesn't hold longer than it has to | Caiden |
| 5 | How fast is it? | Only say a number that's in `team/FACTS-0718.md` with its source. If it isn't there: "We didn't time it end to end today." Don't quote the 2 AM fake-arm voice timings as the arm's speed | Caiden |

## How it works

| # | Question | Answer | Who |
| --- | --- | --- | --- |
| 6 | How does a request become a motion? | You say the instrument's name. The voice server matches it on the laptop and tells the station to run that instrument's skill. The station sends every motion through the arm's guards: speed cap, joint range, gripper and temperature | Caiden |
| 7 | Where does Gemini come in? | On the full controller path, Gemini turns messy phrasing ("grab me the kelly") into one command from the tray. On the arm today, plain instrument names are matched locally, so the arm starts without a model round trip. Gemini is also the fallback when Perceptron OCR fails | Caiden |
| 8 | How does it know you've taken it? | It holds the handle out and watches the gripper load, the jaw and the arm joints. A pull that moves any of them, held for a fraction of a second, means you've got it. Then it lets go. "Let go" or "got it" works too. After it opens, it closes the jaw to check the tool is gone; if something stops the jaw, it offers again | Caiden |
| 9 | What happens after the handoff? | It goes straight home on its own and turns its motors off | Caiden |
| 10 | Does it put tools back? | On the real arm, no. A person puts them back, and the video labels that manual. The video shows a return in simulation, modeled as an electromagnet pickup and labeled as simulation | Evan |
| 11 | What does Perceptron's vision API do? | Detect finds the instruments in a tray photo; OCR reads the printed count sheet, with Gemini as the fallback. Both are tested on rendered props. Say a real-tray result only if shots 7 and 8 were recorded | Brandon |
| 12 | What does the sim do? | A MuJoCo model of the SO-101 plays the same routine for the video and as our backup. It doesn't mirror the real arm live | Caiden |
| 13 | How much data? | The number of recorded demonstrations per instrument comes from `team/FACTS-0718.md`. Don't guess | Anish |
| 14 | Where is the data stored? | Arm telemetry and saved demonstrations go to MongoDB Atlas. The public page on Vultr reads from it | Evan |

## Safety

| # | Question | Answer | Who |
| --- | --- | --- | --- |
| 15 | How do you stop it? | Say "stop" and it freezes where it is, motors on, still holding. "Continue" picks up where it left off; "return to home" sends it home. KILL (Esc on the station page, or say "kill") cuts the motors at once | Caiden |
| 16 | How fast can it move? | Each joint's peak speed is capped at 45 degrees a second, and each control step can move a joint at most 15 degrees. Every goal is kept inside the joint's calibrated range | Caiden |
| 17 | Can it squeeze too hard? | When the jaw stalls on a tool, it holds at the contact point plus a small squeeze instead of pushing into overload. It eases open if the gripper gets too hot | Anish |
| 18 | What if nobody takes the tool? | After 45 seconds it goes home holding it and turns its motors off | Caiden |
| 19 | Can anything else move the arm? | Only the station sends motion to the arm. Voice and the pages send it requests | Caiden |

## Clinical and regulatory

| # | Question | Answer | Who |
| --- | --- | --- | --- |
| 20 | Would a hospital let this near a patient? | Not today. It's a research prototype and never touches the patient. We'd start in surgical training labs, where there's no patient | Anish |
| 21 | Is it FDA cleared? | No. It's not a medical device and we make no clinical claims. A real version needs a regulatory path, worked out with experts | Anish |
| 22 | Does it prevent retained items? | No. A Mayo Clinic study found an item left inside about once in 5,500 operations, and in 62% of those the count had been called correct. A camera-checked count could add a second check. The clinician owns the count | Caiden |
| 23 | Is any data private? | We don't record patients. Telemetry logs joints, temperatures, events and times | Evan |

## The problem and the business

| # | Question | Answer | Who |
| --- | --- | --- | --- |
| 24 | How bad is the shortage? | A surgical tech job takes about 120 days to fill (Periop Leader, 2024). The US projects about 8,600 openings a year for surgical assistants and technologists (BLS) | Anish |
| 25 | Why sharps? | About 385,000 needle and sharps injuries a year to US hospital staff (CDC), most often while passing devices. We don't hand the scalpel at the table today | Caiden |
| 26 | Who pays, and how much? | Surgical training labs first, then surgery centers. Our planning number is $750 per room per month plus $1,500 setup. That's an assumption until we talk to buyers | Anish |
| 27 | Does it pay for itself? | With setup spread over three years it's about $792 a room a month. At about $36 an operating room minute (JAMA Surgery, 2018), that's 22 minutes a month. We haven't measured minutes saved. A pilot would measure that first | Anish |
| 28 | Does it replace scrub techs? | No. It hands over instruments so a scarce tech can focus on the field | Anish |
| 29 | Has this been done before? | Research robots, for example RoboNurse-VLA (a 2024 paper). Ours runs on an open-source arm that costs a few hundred dollars | Anish |
| 30 | What's next? | A medical-grade arm, a model pick once a deployment passes real tries, and talks with operating room nurses | Anish |

## By track

| # | Question | Answer | Who |
| --- | --- | --- | --- |
| 31 | Community Kitchen: why does this fit? | It's aimed at a staffing gap in health care, with a tool you can try at the table by talking to it | Anish |
| 32 | Perceptron Robotics: what's hard here? | Handing a steel instrument to a person, on a low-cost arm, safely. We collected our own demonstrations, taught the picks from them, and wrote the guards around the arm. The training run is separate and shown as its job id and state | Anish |
| 33 | Perceptron Perception: what does vision decide? | Detect checks the tray and OCR reads the count sheet. Show the shot 7 and 8 recordings with their latency | Brandon |
| 34 | Photon: why a phone call? | It needs no new app. Say we took a real call only if it's on video and logged | Caiden |
| 35 | MLH MongoDB Atlas: what's stored? | Arm telemetry and saved demonstrations | Evan |
| 36 | MLH Vultr: what for? | The public judge page runs on a Vultr server | Evan |
| 37 | DubHacks NEXT: what's the business? | A monthly fee per room, training labs then surgery centers. See 26 and 27 | Anish |
