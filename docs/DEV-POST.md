# Building Scrub: a robot arm that passes surgical instruments by voice

By Team Scrub (Anish, Caiden, Brandon, Evan) at DubHacks '26. Draft for the MLH DEV post after the event. Fill every `[measured]` from the dashboard tables first, or cut the sentence.

## The problem

Surgeons work with a scrub tech who hands them instruments and keeps the count. Hospitals can't hire enough of them. A surgical tech job takes about 120 days to fill ([Periop Leader, 2024](https://www.periopleader.com/survey-staffing-woes-ease-slightly-but-challenges-remain/)).

When nobody is there to pass, the surgeon looks away from the patient, puts down what they're holding, and searches the tray.

The count matters. One Mayo Clinic study found an item left inside a patient about once in 5,500 operations, and most of those counts had been called correct ([Cima et al., 2008](https://pubmed.ncbi.nlm.nih.gov/18589366/)). Sharps matter too. US hospital staff have about 385,000 needle and sharps injuries a year ([CDC](https://www.cdc.gov/sharpssafety/)).

Scrub is our weekend answer. You ask for an instrument out loud. A small open-source arm picks it from the tray, brings it to your open hand handle first, and lets go when you pull. Scalpels go to a safe spot instead. Used tools go back to their slots, and Scrub keeps the count.

## How it fits together

Five parts, built in parallel by four people, talking over a short list of HTTP and WebSocket messages:

1. **Voice.** A phone on speaker calls a Photon number. An ElevenLabs agent hears the words. Its language model is our voice server, where Gemini turns them into one action and one item from the current tray. Clinic words work: "Kelly" is the hemostat, "Mayo" is the scissors. "Stop" skips Gemini and goes straight to the controller.
2. **Vision.** One overhead camera. MediaPipe finds the open hand about 10 times a second. Perceptron's vision API finds the instruments and says which slots are full.
3. **Arm.** An SO-101 runs Perceptron's Isaac 0.5, fine-tuned on our own demonstrations, for the pick and the return. The move to the hand is planned from the camera, because the hand is somewhere new every time.
4. **Controller.** The only thing that moves the arm. It checks every grasp, sends sharps to the safe spot, and freezes on "stop".
5. **Ledger and dashboard.** Every event goes to MongoDB Atlas. The dashboard shows the step, what's out, the handoff time and the success tables.

## Teaching the arm

Hard-coded paths break when a tool sits a little off or the light changes. So we taught the arm from demonstrations.

- A person moves a leader arm. The follower copies it. LeRobot records two cameras (side and wrist) and six joint angles at 30 frames a second.
- Each episode has its exact instruction, like `pick the hemostat` or `return the hemostat`. One model learns every item and both directions.
- The plan: 20 picks and 10 returns for each operating room instrument, 15 picks and 10 returns for each bench tool, across bright, normal and dim light. We recorded [measured] clean episodes.
- The bench tray (needle-nose pliers, wire cutters, hex key) needed new demonstrations and one settings file. No code change. It took [measured] minutes.

## Glare

Operating lights are bright and steel throws glare. With auto exposure, the camera kept changing its gain and the tray went dark around a reflection.

1. At startup we lock exposure and white balance, so a lamp no longer makes the picture flicker.
2. The vision service tags every frame bright, normal or dim from its brightness, and every logged trial carries that tag.
3. We test in all three. Results: bright [measured]%, normal [measured]%, dim [measured]%. Median request to hand: [measured] seconds.

## Safety rules we built in

1. **Sharps never go hand to hand.** Operating rooms pass sharps hands-free for a reason. Scrub sets the scalpel on a fixed safe spot and says "scalpel down."
2. **Every grasp is checked twice.** The gripper position shows whether the jaws closed on something. The camera shows whether the slot is now empty. A miss is retried once, then reported out loud.
3. **Stop is its own path and it latches.** "Stop", the spacebar or the stop button freezes the arm in [measured] ms. It stays frozen until a person resets it.
4. **The hand decides.** The arm slows near the hand. If the hand is lost or something crosses the path, it holds still and says so.
5. **Let go on a pull.** The arm waits with the tool. When you pull, the gripper feels the load change and opens. You can also say "got it."

## What we learned

The useful version of this job is small. Pass the instrument, put it back, keep the count, and never hand someone a blade. Stop has to be its own path, because a round trip to a model is too slow when someone says stop.

## What's next

Surgery centers first, in training labs before any patient. A monthly fee per operating room. At about $36 a minute of operating room time ([JAMA Surgery, 2018](https://jamanetwork.com/journals/jamasurgery/fullarticle/2673385)), Scrub breaks even if it saves a room about 22 minutes a month, and a pilot has to show that. It helps scrub techs. It doesn't replace them. Scrub is a research prototype with no clinical claims.

The code, the recording tools and the tests are open source in our repo.
