# Judge Q&A

Short, honest answers. Surgical first: the operating room tray (scalpel handle, hemostat, Mayo scissors). The robotics bench tray (needle-nose pliers, wire cutters, hex key) is the second setting. Research prototype. No clinical claims.

`[measured]` is a number we fill from the dashboard tables on Sunday. If it is not filled, say "we're still logging that" and do not guess. Every outside number here is the same one used in `docs/PITCH.md`, with its source listed there.

Who answers: Anish (arm, training, business), Caiden (controller, voice, safety), Brandon (camera, hand tracking, tray vision), Evan (data, dashboard, tables, hosting). Anyone can start. The owner finishes.

## The problem

| # | Question | Answer | Who |
| --- | --- | --- | --- |
| 1 | How bad is the shortage? | A surgical tech job takes about 120 days to fill (Periop Leader survey, 2024). The US projects about 8,600 openings a year for surgical assistants and technologists (BLS) | Anish |
| 2 | Why does the count matter? | A Mayo Clinic study found an item left inside a patient about once in 5,500 operations. In 62% of those, the count had been called correct. Scrub adds a second check. It does not replace the human count | Caiden |
| 3 | Why the fuss about sharps? | About 385,000 needle and sharps injuries a year to US hospital staff (CDC). Nurses and techs get hurt most often while passing devices. In one study, surgeries that used hands-free passing at least 75% of the time had 35% fewer cuts, glove tears and blood contacts (Stringer, 2009) | Caiden |
| 4 | What does a missing instrument cost? | In a 2024 study of seven operating rooms, instrument problems, mostly missing instruments, delayed a case about 10 minutes on average. Operating room time cost about $36 a minute in California hospitals (JAMA Surgery, 2018). "Check the tray" catches a missing instrument before the case | Anish |

## Technology

| # | Question | Answer | Who |
| --- | --- | --- | --- |
| 5 | How does a request become a motion? | The phone call goes to a Photon number. An ElevenLabs agent hears it. Its language model is our voice server. Gemini turns the words into one action and one item from the current tray. The controller runs the steps: pick, check the grasp, move to the hand or the safe spot, wait for the pull, let go, go home | Caiden |
| 6 | What does the learned model do? | It does the pick and the return. We recorded our own demonstrations on the SO-101 and fine-tuned Perceptron's Isaac 0.5 on them. One model, told in words which item and which direction | Anish |
| 7 | And the move to the hand? | That part is planned, not learned. The hand is in a different place every time, so the arm moves to a point the camera gives it | Anish |
| 8 | Why a model instead of scripted paths? | Scripts break when an item sits at an angle or the light changes. The model learns from varied demos. The table shows how well it holds up: [measured] | Anish |
| 9 | How does hand tracking work? | One overhead camera. MediaPipe finds the open palm about 10 times a second. Calibration turns that into a point for the arm. The arm slows down near the hand and waits for a pull or "got it" | Brandon |
| 10 | What does Perceptron's vision API do? | It finds the instruments and says which slots are full and whether the return spot is holding one. That drives the grasp check, the automatic return, the count check and "check the tray" | Brandon |
| 11 | How do you handle glare? | The camera locks exposure and white balance, so a lamp doesn't make it flicker. Every try is tagged bright, normal or dim. Bright: [measured]%. Normal: [measured]% | Brandon |
| 12 | How do you use Gemini? | Structured output: one action and one item id from the current tray. It can't invent an instrument that isn't there. If Gemini is slow or down, a local word match takes over. It also writes the end-of-case summary and reads texts | Caiden |
| 13 | Why does "stop" skip Gemini? | A round trip to a model is too slow for a stop. "Stop" goes straight to the controller's stop endpoint | Caiden |
| 14 | What happens after "end of case"? | Scrub texts a summary on the same Photon thread: the count first, what was passed, set down or missed, and the median handoff time. With the public page set, a second text links the case replay | Caiden |
| 15 | What does the sim do? | A MuJoCo model of the SO-101 runs the same controller. We test flows on it, and it is our backup if the real arm fails | Caiden |
| 16 | Can clinics use their own words? | Yes. "Kelly" is the hemostat, "Mayo" is the scissors, "Allen key" is the hex key. A clinician can say "call the hemostat a clamp" and Scrub saves it | Caiden |

## Data and training

| # | Question | Answer | Who |
| --- | --- | --- | --- |
| 17 | How much data? | The plan is 20 picks and 10 returns for each operating room instrument, and 15 picks and 10 returns for each bench tool, spread across bright, normal and dim. Recorded so far: [measured] episodes | Anish |
| 18 | How did you fine-tune? | LeRobot records two cameras (side and wrist) and six joint angles at 30 frames a second. The dataset goes to Hugging Face, and Perceptron fine-tunes Isaac 0.5 on it. We get two training runs, so we check every dataset before training | Anish |
| 19 | What did the second tray take? | New demonstrations and one settings file. No code change. Minutes from first bench demo to first bench handoff: [measured] | Anish |
| 20 | How reliable is it? | Success by item and by lighting, with the number of tries and a 95% range, is on the dashboard: [measured]. The range is there so a small sample doesn't look more certain than it is | Evan |
| 21 | Where is the data stored? | Every event and every test goes to MongoDB Atlas. The tables, the count and the case replays read from it. If Atlas is down, events go to a local file and upload later | Evan |
| 22 | How fast is a handoff? | Median request to hand: [measured] seconds. The dashboard times every one | Evan |

## Safety

| # | Question | Answer | Who |
| --- | --- | --- | --- |
| 23 | How do you stop it? | Say "stop", press Space, or press the stop button on any page. It freezes and stays frozen until a person resets it. Stop latency: [measured] ms | Caiden |
| 24 | What if the hand moves away? | If the hand is lost for more than half a second, or something crosses the path, the arm holds still and says so. It doesn't retry on its own. A reset carries the item to the safe spot | Caiden |
| 25 | What if it misses a grasp? | The gripper and the camera both check. It retries once. A second miss, it says so out loud and doesn't guess | Caiden |
| 26 | Can it squeeze too hard? | While we record, the arm stops at the point where the jaws touch the tool plus a small squeeze, instead of pushing into overload. We are still testing the live grip on the real arm | Anish |
| 27 | Can anything else move the arm? | No. Only the controller moves the arm. Voice, vision and the pages only send it requests | Caiden |

## Clinical and regulatory

| # | Question | Answer | Who |
| --- | --- | --- | --- |
| 28 | Would a hospital let this near a patient? | Not today. It is a research prototype and never touches the patient. A real version would sit under a sterile drape on a medical-grade arm, after testing with clinical staff | Anish |
| 29 | Is it FDA cleared? | No. It is not a medical device and we make no clinical claims. A real version needs a regulatory path, worked out with experts. We'd start in training labs, where no patient is involved | Anish |
| 30 | What about sterility? | We don't claim it. A real version needs a draped or sterilizable arm and gripper | Anish |
| 31 | Does it prevent retained items? | No single tool does. Scrub adds a second, camera-checked count. The clinician still owns the official count | Caiden |
| 32 | Is any data private? | We don't record patients. Events log items, steps and times | Evan |

## Business

| # | Question | Answer | Who |
| --- | --- | --- | --- |
| 33 | Who pays? | Surgery centers first, then hospital operating rooms, with training labs as the first site. A monthly fee per operating room. The details are in `docs/NEXT.md` | Anish |
| 34 | What would it cost? | Our planning number is $750 per room per month plus a $1,500 setup. That is an assumption until we talk to buyers | Anish |
| 35 | Does it pay for itself? | With the setup spread over three years, it costs about $792 a room a month. At about $36 a minute of operating room time, that is 22 minutes a month, about one minute a working day. Below that it doesn't pay on time alone. We haven't measured minutes saved yet. That is what a pilot measures first | Anish |
| 36 | Does it replace scrub techs? | No. It passes, puts back and counts, so a scarce tech can focus on the field and the next step | Anish |
| 37 | Has this been done before? | Research labs have built robot scrub nurses, for example RoboNurse-VLA (a 2024 paper), Penelope and Gestonurse. None is on the market as far as we know. Scrub runs on a low-cost arm, over a real phone call, hands to the actual hand, puts items back in their slots and keeps a camera-checked count | Anish |
| 38 | What does the hardware cost? | The SO-101 arm costs a few hundred dollars. A medical-grade arm is the later version. The software talks to the arm through one interface, so it can move | Anish |
| 39 | What's next? | A pilot in a training lab, a medical-grade arm, and talks with operating room nurses. Later, handing over the next instrument before it's asked for. The dashboard already suggests one, but that never moves the arm | Anish |

## Failure modes

| # | Question | Answer | Who |
| --- | --- | --- | --- |
| 40 | What if the call drops? | The dashboard, tablet and demo console send the same commands. Stop also works from the spacebar | Caiden |
| 41 | What if Wi-Fi is down? | The local pages still work and stop never needs the network. Gemini, Photon and Atlas pause or queue | Caiden |
| 42 | Operating rooms are loud. Why voice? | Clinicians already ask out loud with their hands busy. The call has noise handling, and the buttons are a backup. Speech accuracy in a loud room: [measured] | Caiden |
| 43 | What if the camera loses the tray? | The dashboard says "vision stale" and the arm doesn't trust the old reading | Brandon |

## By track

| # | Question | Answer | Who |
| --- | --- | --- | --- |
| 44 | Community Kitchen: why does this fit? | It fills a real staffing gap in health care with a tool anyone at the table can use live | Anish |
| 45 | Perceptron Robotics: what is hard here? | A handoff to a moving hand, glare on steel, sharps on their own path, and one model across two trays. Isaac 0.5 fine-tuned on our own demos | Anish |
| 46 | Perceptron Perception: what does vision decide? | Tray state, the grasp check, the automatic return, the count check and the tray check. Each one gates an arm action | Brandon |
| 47 | Photon: why a phone call? | It needs no new app. The whole case runs on one call, and texts in (restock, what's out) and the summary out use the same thread | Caiden |
| 48 | MLH Gemini: where is it essential? | Messy speech ("grab me the kelly") becomes one valid command, plus the summary and the texts | Caiden |
| 49 | MLH MongoDB Atlas: what is stored? | Every event and test. The tables and case replays read from it | Evan |
| 50 | Vultr and GoDaddy: what for? | The public judge page runs on a Vultr server at our domain, which is on the QR code at the table | Evan |
| 51 | DubHacks NEXT: what is the business? | A monthly fee per operating room, surgery centers first. See questions 33 to 36 | Anish |
