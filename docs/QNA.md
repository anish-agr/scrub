# Judge Q&A

Short, honest answers. Scope: surgical first (operating room tray: scalpel handle, hemostat, Mayo scissors). The robotics bench tray (needle-nose pliers, wire cutters, hex key) is the second setting. No dental tray in the demo. Training and research prototype. No clinical claims.

[measured] means a number we fill from the dashboard tables on Sunday. If it is not filled, say "we are still logging that" and do not guess.

Owners: Anish (arm, training, pitch), Caiden (controller, voice), Brandon (vision, camera), Evan (dashboard, ledger, Devpost). Anyone can start; the owner finishes.

## Technology

| # | Question | Answer | Who |
| --- | --- | --- | --- |
| 1 | How did you fine-tune Isaac 0.5? | We recorded our own demonstrations of each pick and return on the SO-101, then fine-tuned Perceptron's Isaac 0.5 on them. Runs are logged in `docs/TRAINING.md`. Success by item and light is in the dashboard table: [measured]% | Anish |
| 2 | How much data did it need? | [measured] demos per item. The second setting (bench) took [measured] demos and [measured] minutes. The bench needed no new code, only demonstrations and a settings file | Anish |
| 3 | Why a model instead of scripted paths? | Scripts fail when an item sits at an angle or the light changes. The fine-tuned model handles shifts in angle, position and glare. We test it in bright, normal and dim light and report the table, with a 95% range | Anish |
| 4 | What does the sim do? | A MuJoCo SO-101 runs the same controller. We use it to test flows without risking the arm, and as the backup if the real arm fails: `python -m controller.run_all backup` | Caiden |
| 5 | How does the camera work? | One overhead camera with locked exposure and white balance. It feeds two things: a MediaPipe hand tracker and Perceptron's vision API for tray state | Brandon |
| 6 | How does hand tracking work? | MediaPipe finds the open palm about 10 times a second. The controller aims for a point 8 cm short of the palm, moves slowly near it, and waits for a pull or "got it" | Brandon |
| 7 | What does Perceptron vision do for you? | It says which slots are full and whether the return spot holds an instrument. That drives the grasp check, the return check and the camera count | Brandon |
| 8 | How is safety handled? | The arm slows near the hand and stops short of the skin. "Stop", the spacebar or the dashboard button freeze it. Stop skips Gemini and latches until a person resets. Stop latency: [measured] ms | Caiden |
| 9 | What if the hand moves or leaves? | The controller freezes if the hand is lost for more than 0.5 s or the path is blocked, and says "Lost your hand. Holding." It does not retry on its own. A reset carries the item to the safe spot | Caiden |
| 10 | How do you handle sharps? | A scalpel never goes hand to hand. Scrub sets it at a fixed safe spot and says "scalpel down." That matches the operating room habit of passing sharps in a called-out spot. Only the scalpel is marked sharp | Caiden |
| 11 | How does the count work? | The controller keeps a list of what is out. The camera cross-checks it: if they disagree, the count line says so ("Camera also sees the X gone."). Count answers at once, even mid-handover | Caiden |
| 12 | How fast is the voice loop? | Voice response time, first sound: [measured] s. Median request to hand: [measured] s. The dashboard times each handoff | Caiden |
| 13 | How do you use Gemini? | It turns what was said into one action and one item from the current tray, using structured output. It cannot invent an instrument that is not on the tray. If Gemini is slow or down, a local alias match takes over. It also writes the end-of-case summary | Caiden |
| 14 | Why does "stop" skip Gemini? | A round trip to a model is too slow for a stop. "Stop" goes straight to the controller's stop endpoint | Caiden |
| 15 | How do Photon and ElevenLabs fit? | A phone on speaker calls a Photon number. An ElevenLabs agent hears and speaks. Its LLM is our `voice/` server, which calls Gemini and the controller. The summary text goes back on the same Photon thread | Caiden |
| 16 | What does MongoDB do? | Atlas stores every event and every measured trial. The success tables, the count and the case pages read from it. If Atlas is down, events go to a local file and upload later | Evan |
| 17 | Why an SO-101? | It is open source, costs a few hundred dollars, and has a LeRobot driver and a MuJoCo model. It let four people build this in a weekend. The software goes through one arm interface, so a better arm can replace it | Anish |
| 18 | What happens in glare? | We train and test under bright, normal and dim light. The camera locks exposure so the lamp does not make it flicker. Bright-light success: [measured]% (normal: [measured]%) | Brandon |
| 19 | Can it add a new instrument? | Yes. Add it to the tray's settings file, record demos for the new item and retrain. No controller change. Clinic words ("call the hemostat a clamp") are saved as aliases by voice or text | Evan |
| 20 | How reliable is it? | Success by item and light, with number of tries and a 95% range, is on the dashboard: [measured]. We say the small-sample range out loud | Evan |

## Business

| # | Question | Answer | Who |
| --- | --- | --- | --- |
| 21 | Who pays? | Operating rooms and surgical teams first, per tray or room per month. [measured] price after we talk to buyers. Other clinics and labs come later | Anish |
| 22 | Does it replace assistants? | No. It handles passing and counting. That frees scarce assistants to do other work. A surgical tech job stays open about four months | Anish |
| 23 | Has this been done before? | Research labs have built robot scrub nurses, such as RoboNurse-VLA in 2025. None is on the market. Scrub runs the same model across settings on a low-cost arm, returns instruments to slots, tracks the count and passes sharps hands-free | Anish |
| 24 | What does the hardware cost? | The arm costs a few hundred dollars. A medical-grade arm is the later version. [measured] for the full bench kit | Anish |
| 25 | What is the second setting for? | To show a new setting needs only demonstrations and a settings file. The robotics bench has needle-nose pliers, wire cutters and a hex key. It is a proof of reuse, not a separate product | Anish |

## Clinical and regulatory

| # | Question | Answer | Who |
| --- | --- | --- | --- |
| 26 | Would an operating room let this near a patient? | Not today. This is a training and research prototype. It never touches the patient. In a real room it would sit under a sterile drape on a medical-grade arm, after testing | Anish |
| 27 | What about sterility? | We do not claim sterility. A real version needs a draped or sterilizable arm and gripper, validated with clinical staff. That is future work | Anish |
| 28 | Is it FDA approved? | No. It is not a medical device and we make no clinical claims. A real version would need a regulatory path, likely as a device accessory, worked out with experts | Anish |
| 29 | Who is liable if it drops an instrument? | Today nobody, since it is a prototype for training and research. In a real product the maker and the facility would share liability under a contract. That is why every grasp is checked and misses are reported out loud | Anish |
| 30 | Is the data private? | We do not record patients. Events log the items, steps and times, not images of people. Case pages are for the demo. A real clinic would need its own storage and access rules | Evan |
| 31 | Who does the count protect? | It is a second check, not a replacement for the human count. The clinician still owns the official count | Caiden |

## Failure modes

| # | Question | Answer | Who |
| --- | --- | --- | --- |
| 32 | What if it misses a grasp? | It checks the gripper and the camera. On a miss it retries once. On a second miss it says so out loud and does not guess | Caiden |
| 33 | What if the call drops? | The dashboard, tablet and demo console send the same commands. Stop also works from the spacebar | Caiden |
| 34 | What if Wi-Fi is down? | Local voice and buttons still work. "Stop" never needs the network. Cloud pieces (Gemini, Photon, Atlas) pause or queue | Caiden |
| 35 | What if the room is loud? | Operating rooms are loud. The call has noise cancellation, and typed or button backups exist. Real-room speech accuracy: [measured] | Caiden |
| 36 | What if the arm fails? | `python -m controller.run_all backup` switches to the sim arm and plays a scripted full run. We also have a backup video and slides | Anish |
| 37 | What if the camera loses the hand? | The arm holds and says so. The dashboard shows "vision stale" if the tray reading is old | Brandon |

## What's next

| # | Question | Answer | Who |
| --- | --- | --- | --- |
| 38 | What is next? | Test on a medical-grade arm. Then hand over the next instrument before it is asked for, using the step of the procedure. A "likely next" line on the dashboard already suggests it, but does not move the arm | Anish |
| 39 | What would you do with another month? | More demos per item, more lighting setups, a measured stop latency on real hardware, and a talk with an operating room nurse about the workflow | Anish |

## By track

| # | Question | Answer | Who |
| --- | --- | --- | --- |
| 40 | Perceptron Robotics: what is hard here? | Handoffs to a moving hand, glare on steel, a safe path for sharps, and the same model across two trays. We fine-tuned Isaac 0.5 on our own demos and show the table | Anish |
| 41 | Perceptron Perception: what does vision do for you? | Tray state, grasp check, return check and the camera count. Each one gates an arm action | Brandon |
| 42 | Photon: why a phone call? | Clinicians already ask out loud, and a call works with no new app. Photon also carries the summary text on the same thread | Caiden |
| 43 | MLH Gemini: where is Gemini essential? | It turns messy speech ("grab me the kelly") into one valid command from the current tray, and writes the summary | Caiden |
| 44 | MLH MongoDB: what is stored? | Every event and every measured trial. The tables are read from Atlas | Evan |
| 45 | Vultr and GoDaddy: what do you use them for? | Vultr hosts the public judge page. The GoDaddy domain is on the QR code at the table | Evan |
| 46 | DubHacks NEXT: what is the business? | A monthly fee per tray or room, starting with operating rooms. See questions 21 to 25 | Anish |
| 47 | Community Kitchen: how is this a kitchen? | It is the same job as a kitchen assistant: the right tool in your hand at the right time, so you do not have to look away from the work | Anish |
