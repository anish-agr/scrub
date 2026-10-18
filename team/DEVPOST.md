# Devpost text

Final text for Sun Oct 18. Submit by 9:30 AM (the form locks at 10:00). Paste from **Project name** through **Built with**; leave this note and the track list out of the text fields. Every claim was checked against the code and logs at 07:20 (`team/FACTS-0718.md`). If something changes before 9:30, change the sentence or cut it.

## Tracks to enter, with the proof each needs

- **Community Kitchen (title).** The whole project.
- **Perceptron Robotics.** The arm on video. The picks are taught skills (replays of our own recorded demonstrations) and each clip is labeled that way. Training, said plainly: no fine-tuning job was submitted; 0 jobs and 0 deployments at 07:20, so there is no job id.
- **Perceptron Perception.** The tray check and the OCR read on video, with the latency on screen. Until that is filmed, the only proof is rendered props (count sheet read correctly 5 of 5, 1.8 to 2.3 s, `docs/INTEGRATION.md`).
- **Photon.** The call on +1 785 867 1047, on video. Not confirmed at 07:20: a voice turn moved the real arm at 07:02:14, but no log shows it came over the phone. A person checks the Photon "Recent calls" or ElevenLabs "Call history" for 07:00 to 07:03. Don't claim the call until that or a filmed call exists.
- **DubHacks NEXT.** The business case in `docs/BUSINESS.md`.
- **MLH Gemini API.** Words to one command from the tray's fixed list.
- **MLH MongoDB Atlas.** The event log and the arm temperature log.
- **MLH Vultr.** The public judge page at http://144.202.95.111/, after the redeploy.
- Not entered: Tiger Data, Backboard, GoDaddy.

## Project name

Scrub

## Tagline

A robot arm that passes surgical instruments when you ask out loud.

## Inspiration

Surgeons work with a scrub tech who hands them instruments and keeps the count. Hospitals can't hire enough of them: a surgical tech job takes about 120 days to fill ([Periop Leader, 2024](https://www.periopleader.com/survey-staffing-woes-ease-slightly-but-challenges-remain/)). When nobody is there, the surgeon looks away from the patient, puts down what they're holding and searches the tray.

The count and the sharps matter too. One Mayo Clinic study found an item left inside a patient about once in 5,500 operations, and most of those counts had been called correct ([Cima et al., 2008](https://pubmed.ncbi.nlm.nih.gov/18589366/)). US hospital staff have about 385,000 needle and sharps injuries a year ([CDC](https://www.cdc.gov/sharpssafety/)).

## What it does

You ask for an instrument out loud. The tray holds a scalpel, a hemostat and Mayo scissors. Scrub's SO-101 arm picks the one you named, holds it out at the handoff point, lets go when you pull it or say "let go", and goes straight home on its own. Say "stop" and it freezes where it is.

Plain names work, and so do the names people use in the room: "Kelly" is the hemostat, "Mayo" is the scissors.

On the real arm, each pick is a skill we taught it: a replay of demonstrations we recorded with a leader arm. In the simulation, our controller runs the flow and slows the arm down for the last stretch to the handoff point.

In the video, putting an instrument back on the tray is simulated (an electromagnet pickup) and labeled that way. On the real arm a person puts it back.

Scrub is a research prototype. It never touches the patient and makes no clinical claims.

## How we built it

**Voice.** A call reaches an ElevenLabs voice agent, and its language model is our voice server. Gemini turns the words into one command from the tray's fixed list, so it can't ask for an instrument that isn't there. Known instrument names and "stop" are matched locally and skip Gemini. With the real arm connected, every turn is matched locally, so the reply comes back in about 20 to 100 ms.

**Arm.** Perceptron gave us the SO-101 and a pre-trained model to fine-tune. We recorded 29 demonstration episodes (24 usable). We didn't get to a fine-tuning run, so the real arm replays the averaged demonstrations for each instrument through our own station program, which owns the motors and the safety checks.

**Simulation.** A MuJoCo model of the SO-101 runs our controller's flow: pick, check the grasp, carry, slow down near the handoff point, release on the pull, go home.

**Vision.** Perceptron's vision API reads the tray and, with OCR, the printed count sheet.

**Ledger.** Every event goes to MongoDB Atlas, along with the arm's motor temperatures. The public page runs on a Vultr server.

**Safety.**
- "Stop" freezes the arm where it is. In the controller it stays frozen until someone resets it.
- The arm checks motor temperatures every couple of seconds. At 60 C it goes home and turns the motors off, and it waits for them to cool before it runs again.
- Every move is speed-capped. On the real arm the peak joint speed is 45 degrees a second, and moves take 1.6 times longer once a motor passes 52 C.
- In the controller, every joint command is clamped to the arm's limits, and the grasp is checked before the arm carries anything.
- It lets go when you pull the instrument or tell it to.

## Challenges

The camera frame rate was too low to follow a moving hand, so we dropped hand tracking. The handoff point is fixed, and in the controller the arm slows down as it gets close.

The servos heat up when they hold a pose. We logged motor temperatures to Atlas while recording and set the cool-down rule from that data.

We had one arm and four people. The arm, camera, voice and log are separate programs that share a short list of messages, and the simulation let us test the whole flow while the real arm was busy recording.

## Accomplishments

- The real arm handed a scalpel to a person twice this morning (06:39 and 07:02); the 07:02 one was asked for by voice. Both times it let go when the hand took it, checked the jaw was empty and went home.
- The controller's full flow runs on the simulated arm, with the same stop path as the real one.
- A phone-ready voice agent that turns speech into one command from the tray, with a local fast path for "stop".

## What we learned

The useful version of this job is small: pass the instrument and let the person decide when to take it. Stop has to be its own path, because a round trip to a model is too slow when someone says stop.

## What's next

Fine-tune Perceptron's model on our demonstrations so the arm finds the instrument instead of replaying a path. Then training labs, with no patients, before surgery centers, as a monthly fee per operating room. At about $36 a minute of operating room time ([JAMA Surgery, 2018](https://jamanetwork.com/journals/jamasurgery/fullarticle/2673385)), Scrub breaks even if it saves a room about 22 minutes a month. We haven't measured that, so a pilot comes first.

On sterility: Scrub never touches the patient and is a research prototype. A clinic version would run under a sterile drape on a medical-grade arm, like today's surgical robots, with trays and tools sterilized as usual. We don't claim it's sterile.

## Built with

Python, FastAPI, TypeScript, HTML, JavaScript, LeRobot, SO-101, MuJoCo, Perceptron, Gemini, ElevenLabs, Photon, MongoDB Atlas, Vultr

## Video

Script and shots: `team/VIDEO-SCRIPT.md` and `team/HANDOFF-7AM.md`. Upload unlisted to YouTube by 9:00 AM and paste the link in the form. Label every real-arm pick as a taught skill and the return as "SIMULATED RETURN (electromagnet)".

## DEV post (after the event, not part of the form)

Title: Building Scrub: a robot arm that passes surgical instruments by voice. Write it from the final Devpost text above, with no claim that isn't in it.
