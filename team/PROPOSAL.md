> Scope change Sat Oct 17 6:30 PM: surgical first, the robotics bench is the second setting, dental is dropped. See team/LEFT.md.

# Scrub: a robot assistant that passes instruments

DubHacks '26

## Summary

Scrub is a robot arm that works as a second pair of hands. A clinician asks for an instrument out loud, and Scrub picks it from the tray and holds it out handle first at the clinician's side. It lets go when they take it. When they're done, they set the instrument down in the return spot and Scrub puts it back in its slot. Scalpels never go hand to hand: Scrub places them in a fixed safe spot, the way operating room staff pass sharps. Scrub keeps a running count of every instrument out and reads back what's missing before the case ends.

Scrub talks back. The voice runs over a real phone call on speaker, so everyone at the table hears the request and the answer.

We show the same system in three settings:

1. **Operating room:** scalpel handle, hemostat, Mayo scissors.
2. **Dental office:** mouth mirror, explorer, cotton pliers.
3. **Robotics lab bench:** needle-nose pliers, wire cutters, hex key.

One fine-tuned model and one codebase run all three. Each setting is a tray of three items and its own demonstrations. Adding a setting needs no new code.

**Tracks:**

- **Title:** Community Kitchen
- **Sponsored:** Perceptron Robotics, Perceptron Perception, Photon
- **Non-sponsored:** DubHacks NEXT, MLH Gemini API, MLH Vultr, MLH MongoDB Atlas, MLH GoDaddy Registry, MLH Commit Fellowship, MLH DEV writing challenge

## The problem

Dentists and surgeons work with an assistant whose job includes handing them instruments. Clinics can't hire enough of these assistants, and when nobody is there, the clinician turns away from the patient, puts down what they're holding, and searches the tray.

| Who | The number | Source |
| --- | --- | --- |
| Dental assistants | 69% of dentists recruiting assistants call it "extremely" (40.1%) or "very" (29.1%) challenging, Q3 2025 | ADA Health Policy Institute, via Becker's Dental |
| Dental practices | In any given month, 4 in 10 practices are trying to hire assistants or hygienists | ADA Health Policy Institute |
| Surgical technologists | A surgical tech job takes about 120 days to fill, versus 77 for a nurse. Accredited training programs fell from over 500 to about 430 | OR Manager 2024, via Becker's Hospital Review |
| US physicians | Projected shortage of 13,500 to 86,000 by 2036, including 10,100 to 19,900 surgeons | AAMC |
| Canada | 5.9 million adults have no regular family doctor or nurse practitioner | OurCare 2025, Canadian Medical Association |

The assistant numbers are the gap Scrub fills. The doctor numbers show why a clinician's time is too scarce to spend searching a tray.

The same problem shows up on a technical bench. A technician holding a circuit board or a motor has to set it down every time they need a different tool. Robotics labs, repair shops and makerspaces lose that time on every swap.

## What Scrub does

### Passing an instrument

1. The clinician says what they need: "scalpel," "hemostat," "scissors."
2. Scrub answers on the speakerphone ("hemostat coming"), picks the hemostat from its slot, and checks the grasp.
3. The camera finds the clinician's open hand, and the arm brings the instrument to it, handle first.
4. The clinician takes it. Scrub feels the pull in the gripper and lets go. They can also say "got it."
5. The arm goes back home and the count updates.

The handoff adapts to the person. The clinician holds out an open hand wherever is comfortable, and a hand tracker on the overhead camera finds where it is. The arm brings the instrument to a point a few centimeters short of the palm, with the handle turned toward it, and waits there for the clinician to close their hand. If the hand moves, the target moves with it. If the hand is out of the arm's reach, Scrub holds at the closest point it can reach and says "a little closer."

Scrub also remembers each clinician. Their usual hand height and side are saved, so the arm starts heading to the right place before the hand is fully out.

Avoiding the person:
- The arm only enters a marked handoff region above the table edge. It never moves toward anything outside it.
- It approaches slowly and stops short of the palm instead of pushing into the hand.
- If the tracker loses the hand, or sees an arm or body crossing the path, the arm stops where it is.

### Sharps

The scalpel never goes hand to hand. Scrub places it in a fixed safe spot on the table and says "scalpel down." The clinician picks it up from there. This follows AORN's guidance for operating rooms: pass sharps hands-free, one at a time, and call it out when one is placed.

### Taking instruments back

When the clinician is done with an instrument, they set it in the return spot, an empty area beside the tray. The camera sees it, Scrub says "returning the hemostat," picks it up, and puts it back in its slot. The count marks it as back.

### The count

Scrub tracks every instrument that leaves and returns. Say "count" and it reads back what's still out: "Two out: hemostat and scissors." When the case ends, the same phone thread gets a text summary of what was used and anything missing. Operating rooms already run instrument counts as a safety check, because a tool left behind is a serious error. Scrub keeps that count automatically.

### Talking to Scrub

The clinician talks the way they would to an assistant. Plain names always work. Scrub also understands the names clinicians actually use. For example, surgeons often call a hemostat a "Kelly," which is the name of a common type of hemostat clamp. Supporting both is a short list of extra words per item, not extra code.

Commands:

- an item name: hand it over
- "return": take back what's in the return spot
- "count": read back what's out
- "stop": freeze the arm immediately

The spacebar on the laptop is also a stop key, standing in for the foot pedal a real clinic would use.

### How commands work, with Gemini

1. ElevenLabs turns what the clinician says on the Photon call into text as they speak.
2. That text goes to the Gemini API with the current setting's item list (each item's name, its other names and whether it's sharp) and the five actions Scrub can take: hand over an item, return, count, stop, and "didn't understand."
3. Gemini picks exactly one action and one item from that list, using structured output. It can't invent an item that isn't on the tray. "Grab me the Kelly" and "hemostat please" both become "hand over: hemostat."
4. "Stop" skips Gemini entirely. The voice agent checks for that word first so the arm freezes with no delay.
5. If Gemini returns "didn't understand," or names an item that isn't on the tray, Scrub asks back on the call: "Which instrument?"
6. Gemini also writes the end-of-case text from the ledger: what was used, how many times, and anything still out.

Gemini only turns words into a command. It never moves the arm. Every command still goes through the controller and its safety rules.

## How it works

Seven parts run on one laptop. Perceptron, Photon, ElevenLabs and Gemini run in the cloud. Only the controller moves the arm.

| Part | Job | Built with |
| --- | --- | --- |
| Camera | Grabs frames from the overhead camera with exposure locked so bright light doesn't throw it off | Python, OpenCV |
| Perception | Finds each item on the tray and in the return spot; confirms a slot is empty after a pick; feeds the count | Perceptron vision API |
| Hand tracker | Finds the clinician's open hand many times a second and turns its position into a target for the arm; saves each clinician's usual hand position | MediaPipe hand tracking, a one-time camera-to-arm calibration |
| Voice agent | Answers the phone call, turns speech into a command, speaks replies, texts the end-of-case summary | Photon 2.0 (phone number for the call and texts), ElevenLabs for the voice, Gemini to turn speech into a command and write the summary |
| Policy | Sends camera images, arm position and a text instruction ("pick the hemostat") to the fine-tuned Isaac 0.5 model and plays back the movements it returns | Perceptron's fine-tuning and inference endpoints, LeRobot tools |
| Controller | Runs each request step by step and enforces the safety rules | Python service |
| Ledger and dashboard | Logs every item out and back with timestamps and request-to-hand time; shows the live camera, the count and the results | MongoDB Atlas, a web page |

### One request, start to finish

1. **Hear it.** The voice agent turns "hemostat" into a request and sends it to the controller.
2. **Find it.** The controller checks the latest tray view. If the hemostat isn't there, Scrub says so.
3. **Pick it.** The policy runs "pick the hemostat."
4. **Check the grasp.** Two checks: the gripper stopped before closing all the way, so something is in it, and the camera sees the slot empty. If either fails, Scrub retries once, then says it missed.
5. **Hand it over, or set it down.** For regular items, the hand tracker locates the clinician's open hand, and the arm moves to just short of the palm, handle first, at reduced speed. The scalpel goes to the safe spot.
6. **Let go.** Release when the gripper feels a pull, or when the clinician says "got it." If nobody takes it within 30 seconds, it goes back to its slot.
7. **Log it.** The ledger marks the item out with its request-to-hand time. The arm returns home.

### Settings

Each setting is a small file: the three items, their slots, which one is sharp, and the words people use for each. At the start we pick which setting is running from the dashboard. Switching settings means swapping the tray and picking the new file.

### Safety rules in the controller

- The arm moves between home, the tray, the safe spot and the return spot, and enters the handoff region only to meet a tracked hand.
- Slow speed inside the handoff region, stopping a few centimeters short of the palm.
- Stop if the hand is lost or something crosses the path.
- Stop on "stop," the spacebar or the dashboard button, from any step.
- Scrub never hands over a sharp.
- If the model stops sending movements, the arm holds still and Scrub reports a problem.

## Why Scrub stands out

- **It does a real job people can't hire for.** The staffing numbers come from the ADA, the AAMC and operating room surveys.
- **It talks.** Asking out loud is how clinicians already work. Judges hear the whole exchange on speaker.
- **It generalizes.** One model, one codebase, three settings, swapped live in front of the judge.
- **It follows real clinical practice.** Sharps go hands-free, instruments are counted out and back, items come back to their slots.
- **It works under operating room lighting.** Surgical lights deliver 40,000 to 160,000 lux under the IEC 60601-2-41 standard, and steel instruments throw glare. Scrub is trained and tested under bright, normal and dim light, with the success rate shown for each.
- **It's affordable.** It runs on an open-source arm that costs a few hundred dollars. The software talks to the arm through one interface, so a clinic version runs on a medical-grade arm.
- **It keeps the clinician in control.** Fully autonomous dental and surgical robots need years of approval. An assistant that passes and counts instruments, and never touches the patient, can reach clinics sooner.

## Tracks

### Title track: Community Kitchen

Community Kitchen covers health, accessibility and assistive technology. Scrub fills a health care staffing gap, which is the core of this track. The rubric is Functionality 30%, Track applicability 30%, Design 20%, Creativity 20%, each scored out of 8.

| Rubric line | Weight | How Scrub earns a high score |
| --- | --- | --- |
| Functionality | 30% | A judge asks for an instrument and gets it, live, every time. The success-rate tables back it up |
| Track applicability | 30% | The pitch opens and closes on clinic staffing, with sourced numbers |
| Design | 20% | A clean dashboard with the live camera, the count and handoff times; a tidy table with real instruments on a blue towel |
| Creativity | 20% | Voice on a live phone call, three settings on one system, sharps handled hands-free, the automatic count, measured lighting robustness |

### Sponsored side tracks we're entering

#### Perceptron Robotics

- **What they want:** take their pre-trained checkpoint on the SO-101 arm, collect our own demonstrations, and fine-tune it for a new task. Judged on creativity, task difficulty and technical execution. A short video of the working arm is required.
- **Requirements:**
    - the interest form before Saturday 10:30 AM (slots announced at noon)
    - the workshop Saturday 12:30 to 1:15 in HUB 334
    - shared arm time, about 20 teams on 5 arms
- **What we build:** one language-conditioned policy covering 9 items in 3 settings, for both handing out and putting back. It's trained on our own demos under three lighting setups.
- **Why the task is hard:**
    - thin, shiny instruments
    - picking by the handle so it's offered handle first
    - placing items back in their exact slots
    - glare from bright light
    - one model across three settings
- **What we show them:**
    - the live handoff and return
    - success rates by item and by lighting
    - the dataset and fine-tuned model on the Hugging Face Hub
    - the required arm video

#### Perceptron Perception

- **What they want:** creative, useful applications of their vision models through the API, out of the box: object localization, OCR, captioning, tracking, finding events in video. No fine-tuning expected.
- **What we use it for:**
    1. **Tray view:** where each instrument is and which slots are empty.
    2. **Grasp check:** confirms the slot is empty after a pick.
    3. **Returns:** spots an instrument set down in the return spot and names it, which triggers the return.
    4. **The count:** compares the tray and return spot against the starting tray to list what's out.
- **What we show them:** the dashboard with live boxes on every instrument. "Count" answered straight from the camera. A return triggered by setting an instrument down.

#### Photon

- **What they want:** an agent built on Photon 2.0 and live on at least one Photon channel (iMessage, SMS, WhatsApp, phone calls and others). Judged on vision, craft, depth and traction. They call out voice agents on a phone number that remember the call when the conversation moves to text. Prizes: $700 for the winner, $300 for the runner-up, and a separate $400 for the best voice agent.
- **Requirements:**
    - a Photon 2.0 project with a phone number
    - voice calls run on that number, connected to a voice service (ElevenLabs)
    - texts go to the same number's thread
- **What we build:**
    - **During the case:** the clinician calls Scrub's Photon number, and the call stays on speaker. Every request and every reply goes through that call, so the whole table hears it.
    - **After the case:** the same thread gets a text with the count, the instruments used and anything still out. This is the call-to-text memory Photon asks for.
    - **Restocking:** staff can text "add a second hemostat to the surgical tray," and Scrub logs it.
- **What we show them:** a judge calls the number on speaker, asks for an instrument, watches it arrive, then gets the summary text on their own phone.
- **Best voice agent:** the speakerphone demo is a voice agent running a physical robot through a real call, which also enters us for the separate $400 prize.

### Sponsored side tracks we're not entering

We can enter only three. These are the ones we left out and what it would take to enter each.

| Track | What they want | Prize | Why we left it out |
| --- | --- | --- | --- |
| Cloudforce | A tiny separate agent built in UW's Purple: 2 to 3 questions in, one personal result out, no login. Posted on social. Judged on live engagement at the table, with a +10% bonus for a LinkedIn post tagging Cloudforce and UW | $1,000 most viral, $500 most interesting, $500 raffle where every entry is a ticket | It has nothing to do with Scrub and would take one of our three sponsored slots. Our sponsored slots go to the tracks Scrub can win |
| SideShift | The strongest startup idea of the weekend, any stack. They like ideas with a clear way to reach people | $1,500 + work trial, $500 + interview, interview | Scrub has a strong startup story, but DubHacks NEXT judges the same story without using a sponsored slot. SideShift is our swap if the Photon call isn't working by Saturday 8 PM |
| VEYZL | An AI project audited by VEYZL on every pull request, with proof the findings changed what shipped | Not announced | An audit of an agent that moves a physical arm would fit. With no prize announced, it's worth less than our three |
| T-Mobile | Better phone shopping and plan recommendations on their mock data, in one of five directions | Jetson Orin Nano Super, Plaud NotePin S, 6 months Claude Pro | Phone shopping has no connection to Scrub |
| SpaceXAI | A project built on space data, made with Cursor, using the Grok Imagine or Voice API | Cursor keyboards, names sent to SpaceXAI recruiting, an Owala raffle | Space data has no connection to Scrub |

### Non-sponsored side tracks and the work we'll do for each

MLH tracks are judged from the Devpost page, so the write-up names each one and shows where it's used.

| Track | Prize | What we'll do |
| --- | --- | --- |
| DubHacks NEXT | $200 + a guaranteed interview for NEXT Batch 6; second place gets the interview | Judged in person on a real problem, a clear user, revenue potential and iteration over the weekend. We'll pitch dental offices as the first customer, priced as a monthly fee per chair. We'll show the iteration with numbers: success rate after fine-tuning run 1 versus run 2, and how long the third setting took to add |
| MLH Gemini API | MLH swag | Gemini turns each spoken request into a command, including names like "Kelly," and writes the end-of-case summary that Photon texts |
| MLH Vultr | M5Stack Tab5 | Host the dashboard and the backend on a Vultr server so anyone with the link can see the live count and results. Keep a Vultr GPU ready for fine-tuning if Perceptron's endpoint is busy |
| MLH MongoDB Atlas | M5Stack IoT kit | Store the instrument ledger, every request and handoff time, and the test results that fill the success tables |
| MLH GoDaddy Registry | Gift card | Register a domain for the dashboard and point it at the Vultr server. Put it on Devpost |
| MLH Commit Fellowship | An interview for the Commit Fellowship + a copy of The Lean Startup | Tick it on Devpost and fill in MLH's supplemental form at mlh.link/commit-fellowship-form |
| MLH DEV writing challenge | $100 | After the event, publish a post on DEV about building Scrub: the data collection, the lighting tests and what we learned |

## The pitch

About 2 minutes 30 seconds of speaking, said while the demo runs so pitch and demo fit in 3 minutes. One person speaks; the others run the arm and the trays.

> In a dental office or an operating room, the doctor works with an assistant who hands them instruments. Clinics can't hire enough of them. Two out of three dentists who are recruiting say finding one is very or extremely hard, and a surgical tech job stays open about four months.
>
> When nobody is there, the doctor turns away from the patient, puts down what they're holding, and searches the tray.
>
> This is Scrub. The doctor asks for what they need, and Scrub hands it over, handle first, and lets go when they take it. Scalpels go to a safe spot instead of hand to hand, the way operating rooms pass sharps. When an instrument is done, it goes back in its slot, and Scrub keeps the count so nothing gets left behind.
>
> We taught it from our own demonstrations and fine-tuned Perceptron's Isaac model on them. Operating lights are extremely bright and steel throws glare, so we trained and tested under bright, normal and dim light. Here's the success rate for each.
>
> The same system works anywhere someone needs a second pair of hands. You've seen the operating room. Here's a dental office, and here's a robotics lab. Each one is a new tray and new demonstrations, with no new code.
>
> Scrub runs on an open-source arm that costs a few hundred dollars, and the software is ready for a medical-grade arm. We're starting with dental offices.

## The demo

The judge asking for an instrument themselves is the moment that sells it, so we practice that step the most.

**Setup:** the operating room tray on the blue towel, the lamp off, the dashboard facing the judge, a phone on speaker connected to Scrub's number.

| Time | What's said | What happens |
| --- | --- | --- |
| 0:00 | The staffing numbers | A teammate stands as the clinician, hands busy |
| 0:30 | "This is Scrub." | Teammate says "hemostat." Scrub answers on speaker, and the hemostat arrives handle first. Teammate takes it and the gripper lets go. The dashboard shows the time |
| 0:50 | The sharps line | "Scalpel." Scrub places it in the safe spot and says "scalpel down" |
| 1:05 | "Try it." | The judge asks for the scissors out loud. They get them |
| 1:20 | The return line | The teammate sets the hemostat in the return spot. Scrub says "returning the hemostat" and puts it back in its slot |
| 1:40 | The lighting line | Lamp on, aimed at the tray. Glare appears and another request works. Point at the lighting table |
| 2:00 | The three-settings line | Swap to the dental tray, ask for the mirror. Swap to the bench tray, ask for the pliers |
| 2:30 | The close | "Count." Scrub reads back what's out, and the summary text arrives |
| 3:00 | Questions | Everyone |

For a judge with only a minute or two, run the 0:30, 1:05 and 2:30 steps.

## Feasibility

Everything here uses hardware Perceptron provides plus things we already own. The software parts are standard pieces, and the hard robotics work is in our team's research area.

| Piece | Difficulty | Hours | What makes it doable | Backup if it struggles |
| --- | --- | --- | --- | --- |
| Pick and hand out 9 items | Hard | Arm time plus 2 hours of setup | Fine-tuning a pre-trained model is what the track is built for. Anish works on robot learning | Drop to the operating room tray alone. Three items is still a full demo |
| Put items back in their slots | Hard | Arm time | Same model, more demos, same training run | The clinician returns items to the tray by hand and Scrub counts them |
| Voice on a Photon call | Medium | 4 to 6 | Photon publishes a step-by-step guide for connecting ElevenLabs to a phone number | The same commands typed on the dashboard, spoken back through the laptop |
| Turning speech into commands | Easy | 1 to 2 | Gemini with a short item list per setting | Exact item names only |
| Tray view and count | Medium | 4 to 6 | Object localization is what Perceptron's vision API does | Count from the controller's own log of what it handed out and took back |
| Hand tracking and moving to the person's hand | Medium | 6 to 8 | A local hand tracker (MediaPipe) finds the palm many times a second; the camera is calibrated to the arm once, so a palm position becomes an arm target | Use the clinician's saved usual position, so the arm goes to their spot and waits |
| Release on pull | Medium | 2 | The arm's motors report load; confirm at the workshop | Release on "got it" |
| Controller and safety | Medium | 6 to 8 | A step-by-step loop, built and tested on a fake arm before the real one | None needed; this is plain code |
| Dashboard and ledger | Easy | 4 to 6 | Standard web page and database | A simpler page with the count only |
| Lighting robustness | Medium | Mostly recording time | Record in three lighting setups and vary images in training | Show the normal and bright results only |
| Arm time | The real limit | About 4 hours needed | Two people per slot, recording in priority order | Operating room set first, so a complete demo exists early |

**Data and arm time:** about 15 hand-out demos and 10 put-back demos per item, so 75 per setting and about 225 in total. Two people can record about 60 demos an hour, so that's roughly 4 hours of arm time across our slots.

**Team time:** the software adds up to about 25 to 35 hours of work. Across four people over 21 hours, with Claude and Codex helping, that leaves room for testing and rehearsal.

**What we confirm at the workshop:**
- slot length and whether we can get overnight time
- that the gripper reports load
- how long a fine-tuning run takes

The plan works either way: everything waiting on an answer has a backup in the table above.

## Data and training

### One demonstration

- **Hand out:** the arm starts at home with the item in its slot. It picks the item by the handle and lifts it into the carry pose. The move to the person's hand is planned from the hand tracker's position, not learned, so it adapts to wherever the hand is. For the scalpel, it places it in the safe spot instead. The demo ends with the item held still. Releasing isn't part of it, because the controller opens the gripper on a pull.
- **Put back:** the item lies in the return spot. The arm picks it and places it in its slot.
- Each demo is saved with its instruction, such as "pick the hemostat" or "return the hemostat," so one model learns every item and both directions.

### What changes between demos

- the item's exact position and angle in its slot and in the return spot
- the lighting: a third each in bright, normal and dim
- which other items are on the tray

### Recording order

| Order | Setting | Items | Demos | Arm time |
| --- | --- | --- | --- | --- |
| 1 | Operating room | Scalpel handle, hemostat, Mayo scissors | 75 | About 1 hour 15 minutes |
| 2 | Dental office | Mouth mirror, explorer, cotton pliers | 75 | About 1 hour 15 minutes |
| 3 | Robotics bench | Needle-nose pliers, wire cutters, hex key | 75 | About 1 hour 15 minutes |

Two people per slot: one moves the leader arm, one resets the tray and keeps the log.

### Fine-tuning

1. **Run 1:** right after the operating room set, to see early whether grasps work.
2. **Run 2:** all three settings together, so one model covers everything.
3. If an item fails often after run 1, record 10 more demos of it before run 2.

### Item placement

Instruments lie flat on the tray, spaced apart, in the same slot every time. If a thin instrument is hard to grip flat, a folded strip of towel under its handle lifts it slightly so the gripper can close around it. The handle has to sit where the gripper can reach.

### Testing

| Test | Tries | What we record |
| --- | --- | --- |
| Operating room items in all three lighting setups | 10 per item per setup (90) | Success, retries, request-to-hand time |
| Dental and bench items in normal and bright light | 5 per item per setup (60) | Success, retries |
| Put-back for every item | 5 per item (45) | Success |
| Adding the bench setting | Once | Minutes from the first bench demo to the first working bench handoff |

These results fill the tables on the dashboard, in the pitch and on Devpost.

## Lighting

Surgical lights deliver 40,000 to 160,000 lux at their reference distance under IEC 60601-2-41. A normal room is a few hundred lux. A bright lamp close to the tray won't reach surgical levels, but it reproduces the glare off steel, which is what the camera has to handle.

| Setup | How we make it |
| --- | --- |
| Bright | The brightest lamp we have, close to the tray and angled so steel shines |
| Normal | Room lights only |
| Dim | Lamp off and some room lights off |

How Scrub handles it:

1. **Record in all three.** About a third of the demos in each, so the model never depends on one look.
2. **Vary images during training.** Random brightness, contrast and color changes during fine-tuning.
3. **Lock the camera.** Fixed exposure and white balance, so turning on the lamp doesn't change how the camera sees everything else.
4. **Matte background.** A blue towel under the tray, like a surgical drape, cuts reflections off the table.
5. **Measure it.** A free lux-meter phone app reads the light level for each setup, shown on the dashboard.

## Build timeline

Five workstreams run in parallel from 12:30 Saturday and meet at five checkpoints.

| Stream | Sat 12:30 to 6 PM | Sat 6 to 11 PM | Overnight, 11 PM to 6 AM | Sun 6 to 10 AM |
| --- | --- | --- | --- | --- |
| Arm and training | Workshop, arm setup, tray positions fixed, operating room demos | Fine-tuning run 1, dental demos, first real handoff | Bench demos (timed), fine-tuning run 2, extra demos for weak items | Tests and success tables, the arm video, a recorded backup run |
| Perception | Camera with locked exposure, tray view from the vision API | Grasp check, return-spot detection | The count from tray and return spot | Freeze, support tests |
| Voice | Photon number live, ElevenLabs voice on the call | Gemini commands, spoken replies, the end-of-case text | Faster replies, sharps call-outs | Freeze, rehearsal |
| Controller and dashboard | Request steps on a fake arm, stop key, speed limit | Retry, release on pull, put-back flow, handoff timer, MongoDB ledger | Full runs end to end; dashboard on Vultr with the domain | Freeze, rehearsal |
| Pitch and Devpost | Pitch draft, DubHacks NEXT pricing | Devpost draft by 10:30 PM | Devpost text, README | Demo video, final Devpost by 9:30 AM |

### Checkpoints

1. **Sat 6:00 PM:** a spoken request on the Photon call runs through every step on a fake arm and shows on the dashboard.
2. **Sat 10:30 PM:** Devpost draft submitted with overview and tracks. First real handoff on the run 1 model.
3. **Sun 2:00 AM:** all three settings trained, and put-back working.
4. **Sun 6:00 AM:** feature freeze. Run tests, fill the tables, rehearse.
5. **Sun 9:30 AM:** demo video uploaded, repo public with a README, final Devpost submitted. It locks at 10:00.

### Overnight

The HUB closes overnight. The workspace is Gates Center G01 from 11 PM, and sleeping there isn't allowed. Anyone heading home around midnight takes work that runs on its own, like a fine-tuning run or a test batch.

## From demo to clinic

| Question | How it's handled |
| --- | --- |
| Sterility | The arm works under a sterile plastic drape, the way surgical robots are draped today. Trays and instruments go through normal sterilization |
| Medical-grade hardware | The software talks to the arm through one interface, so it moves onto a medical-grade arm with force limits and certified parts |
| Safety around people | A bounded handoff region, slow approach that stops short of the palm, stop when the hand is lost, gripper force limits, stop by voice, foot pedal or button. Scrub never touches the patient |
| Sharps | Never hand to hand. Placed in a safe spot and announced, following AORN guidance |
| Regulation | An instrument-passing assistant that never touches the patient is a lower-risk device than a robot that operates. The path is FDA clearance in the US and Health Canada licensing, starting with dental offices |
| Loud rooms | Voice, plus a foot pedal for stop and next |
| Different words per clinic | Each clinic edits its own word list, with no code changes |

---

# Team notes (not for judges)

## What already exists

Robot scrub nurses are an active research area. We found no instrument-passing robot on the market. Know these before judging. If a Perceptron judge mentions RoboNurse-VLA, name it and list what's different.

| System | What it does | Status |
| --- | --- | --- |
| Penelope (2000s) | Voice-controlled robot scrub tech with a magnetic gripper on a cart | Early product attempt; reported as awaiting FDA approval; voice struggled in noisy rooms |
| Gestonurse (2012) | Passes instruments on hand gestures; 95% of gestures recognized | Research |
| Automated scrub nurse robot (2025) | Inserts the next instrument into the surgical port after the surgeon withdraws one | Research, built for the scrub nurse shortage |
| RoboNurse-VLA (CUHK, 2025) | Vision-language-action model that hands over instruments on voice command | Research, the closest to Scrub |
| Voice-interactive VLA scrub nurse (2026) | Fine-tuned model hands over and takes back instruments on voice command | Research; missed grasps were the main failure, which is why we check every grasp |
| LLM scrub nurse with counting (2026) | Speech and vision for handoff, sorting and counting | Research |
| Perceptive (2024) | Fully autonomous robot that performed a dental procedure | Company; a different job, since it does the procedure. US approval expected to take years |

What's different about Scrub:
- three settings on one system
- a cheap open-source arm
- voice over a real phone call
- put-back to the exact slot
- the automatic count
- sharps handled hands-free
- measured lighting robustness

## Judge questions and answers

| Question | Answer |
| --- | --- |
| Hasn't this been done? | Research labs have built robot scrub nurses, most recently RoboNurse-VLA in 2025. None is on the market. We run one system across three settings on a cheap arm, put instruments back, keep the count, handle sharps hands-free, and measured it under harsh light |
| Would a hospital let this near a patient? | It never touches the patient. In a clinic it runs under a sterile drape on a medical-grade arm, like today's surgical robots. Dental offices come first because the sterile procedure is simpler |
| What if it drops something or misses? | Every grasp is checked twice. On a miss it retries once, then says so |
| Why voice? Operating rooms are loud | Voice is how clinicians already ask for instruments. A foot pedal backs it up |
| How fast is it? | About [measured] seconds from request to hand, shown on the dashboard |
| How much data did it need? | About 25 demos per item, 225 total. Adding the bench setting took [measured] |
| Why Perceptron's model and not a script? | A scripted grasp breaks when an item sits at a new angle or the light changes. The fine-tuned model handles both, and the success table shows it |
| Who pays? | Dental practices first, a monthly fee per chair, less than covering an unfilled assistant shift |
| Does it replace assistants? | It covers instrument passing and counting, so the assistants a clinic has can cover more chairs |
| What's next? | A medical-grade arm, and handing the next instrument before it's asked for, based on the step of the procedure |

## Questions for the Perceptron workshop (Sat 12:30, HUB 334)

- How long is each team's arm slot, and can we book time overnight?
- Can we bring our own tray, lamp, towel and instruments to the arm station?
- Can we read the gripper motor's load, for release on pull?
- How long does a fine-tuning run take, and how many demos per item do they suggest?
- Does the fine-tuning pipeline support image changes like brightness and contrast?
- Can one model take a different text instruction per item?
- How fast is inference per movement chunk, and does it run only on their endpoint?
- How do we call the vision API (keys, rate limits)?
- Will the arm be at our table for judging, or do we demo at their station?

## What to bring

Already have:
- [ ] Surgical kit: scalpel handle (blade off), hemostat, Mayo scissors
- [ ] Bench tools: needle-nose pliers, wire cutters, hex key
- [ ] Nitrile gloves in a couple of sizes
- [ ] Boxes or trays for the three settings

Need:
- [ ] Dental mirror, explorer and cotton pliers (cheap kits at drugstores and online)
- [ ] A blue towel for under the trays
- [ ] The brightest lamp we have
- [ ] Painter's tape to mark where each tray and item sits, so positions match the training demos
- [ ] A phone on speaker for the Photon call
- [ ] A power strip and an extension cord, because the arm, a lamp and four laptops need more outlets than one table has
- [ ] Laptop and phone chargers
- [ ] A USB webcam, only if Perceptron's setup has no overhead camera

## Sources

- ADA Health Policy Institute, dental workforce shortages: https://www.ada.org/resources/research/health-policy-institute/dental-practice-research/dental-workforce-shortages
- Becker's Dental, Q3 2025 recruiting data: https://beckersdental.com/staffing-issues/40712-1-3-of-dentists-continuing-to-recruit-dental-hygienists-and-assistants.html
- Becker's Hospital Review, the surgical technologist shortage: https://www.beckershospitalreview.com/academic-medical-center/academic-medical-centers-workforce/the-surgical-technologist-shortage-explained/
- AAMC, projected physician shortage: https://www.aamc.org/news/press-releases/new-aamc-report-shows-continuing-projected-physician-shortage
- CMA, OurCare 2025: https://www.cma.ca/latest-stories/national-survey-59-million-canada-still-without-regular-doctor
- Getinge, IEC 60601-2-41 surgical light requirements: https://www.getinge.com/dam/hospital/documents/english/maquet-surgical-lights-iec-standard-flyer-en-global.pdf
- AORN, cutting sharps injuries: https://www.aorn.org/outpatient-surgery/article/2019-October-5-ways-to-slash-sharps-injuries
- Penelope: https://reliasmedia.com/articles/3871-will-robot-penelope-replace-a-scrub-nurse
- Gestonurse: https://www.springermedicine.com/gestonurse-a-robotic-surgical-nurse-for-handling-surgical-instru/21860572
- Automated scrub nurse robot, 2025: https://pubmed.ncbi.nlm.nih.gov/40478472/
- RoboNurse-VLA, 2025: https://arxiv.org/abs/2409.19590
- Voice-interactive VLA scrub nurse, 2026: https://link.springer.com/article/10.1007/s11701-026-03866-9
- LLM-embedded robotic scrub nurse, 2026: https://advanced.onlinelibrary.wiley.com/doi/10.1002/aisy.202500483
- Perceptive, first fully automated dental procedure: https://www.businesswire.com/news/home/20240730980575/en/5689014
- Photon ElevenLabs voice guide: https://photon.codes/docs/beta/cookbooks/voice/elevenlabs
- DubHacks '26 hacker guide: https://dubhacks.notion.site/The-DubHacks-26-Hacker-Guide-15dff32c1d7e83748aac8154036aa658
