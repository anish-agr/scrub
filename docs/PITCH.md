# Pitch, demo and video

Owner: Anish. Fill the [measured] numbers from the success tables on Sunday morning.

## The pitch

About 2 minutes 30 seconds of speaking. The demo runs at the same time so both fit within 3 minutes. One person speaks. Teammates run the arm and the trays.

> In a dental office or an operating room, doctors work with an assistant who hands them instruments. Clinics cannot hire enough assistants. Two out of three dentists who are recruiting say finding one is very or extremely hard. A surgical tech job stays open about four months.
>
> When nobody is there, the doctor turns away from the patient. They put down what they are holding. They search the tray.
>
> This is Scrub. The clinician asks for what they need out loud. Scrub picks the tool from the tray. It brings the tool to their open hand, handle first. It lets go when they take it.
>
> Scalpels never pass hand to hand. Scrub places them in a fixed safe spot. That follows standard operating room safety rules for sharps.
>
> When a doctor finishes with an instrument, they place it in the return spot. Scrub returns it to its slot. Scrub also tracks the count so nothing stays behind.
>
> We taught Scrub from our own demonstrations. We fine-tuned Perceptron's Isaac model on them. Clinic lights are bright. Shiny steel throws harsh glare. We trained and tested under bright, normal and dim light. Our success rate is [measured]% under normal light and [measured]% under bright glare. The median handoff takes [measured] seconds.
>
> The exact same system works across three settings. You see the operating room tray here. We also have a dental tray and a robotics bench tray. Each setting uses its own demonstrations. None of them needed new code. Adding the bench setting took [measured] minutes.
>
> Scrub runs on an open-source arm that costs a few hundred dollars. The software connects through one clean interface, so it is ready for a medical-grade arm. We are starting with dental offices.

## The demo

The judge asking for an instrument is the moment that sells it. We practice this step the most.

**Setup:** operating room tray on the blue towel. Desk lamp turned off. Dashboard facing the judge. Phone on speaker connected to Scrub's phone number.

| Time | What is said | What happens |
| --- | --- | --- |
| 0:00 | Clinic staffing problem | Teammate stands as clinician with hands busy |
| 0:30 | "This is Scrub." | Teammate says "hemostat" to the phone. Scrub answers on speaker. The arm delivers the hemostat handle first. Teammate pulls and the gripper opens. Dashboard shows [measured] seconds |
| 0:50 | Sharps safe spot | Teammate says "scalpel." Scrub places it in the safe spot and announces "scalpel down" |
| 1:05 | "Try it." | The judge asks for scissors out loud. Scrub delivers them to the judge's open hand |
| 1:20 | Taking items back | Teammate sets the hemostat in the return spot. Scrub says "returning the hemostat" and returns it to its slot |
| 1:40 | Harsh lighting test | Turn on the lamp right over the tray. Steel reflects glare. A request still succeeds. Point to the dashboard lighting table |
| 2:00 | Three settings | Swap to the dental tray and ask for the mirror. Swap to the bench tray and ask for the pliers |
| 2:30 | Count and summary | Say "count." Scrub reads back what is out. The case ends and a summary text arrives on the phone |
| 3:00 | Questions | Entire team answers |

For a judge with only one minute, run the 0:30, 1:05 and 2:30 steps.

## Demo video (2 to 3 minutes, required)

Shot list in order. Record each shot several times and keep the cleanest take. Evan edits.

1. Title card (slide 1), 5 seconds.
2. A clinician with busy hands says "hemostat" to the speakerphone. Close-up of the arm picking it, the hand receiving it handle first, and the gripper opening on pull.
3. "Scalpel." The scalpel moves to the safe spot. Scrub says "scalpel down."
4. The return: hemostat placed in the return spot, then returned to its slot.
5. Lamp turns on. Glare shows on the steel. A handoff still succeeds. Cut to the lighting table on the dashboard.
6. The dental tray (mouth mirror) and the bench tray (pliers).
7. "Count." The voice readback, then the summary text arriving on the phone screen.
8. The dashboard: system diagram and live success tables.
9. Close on the team and the arm.

Record the phone audio clearly. Place a second phone or a laptop microphone right next to the speakerphone.

## Perceptron arm video

A separate clip for the robotics track. The arm performs several picks and returns across items and lighting without edits. Show the dashboard success table at the end.

## Judge questions and answers

| Question | Answer |
| --- | --- |
| Has this been done before? | Research labs have built robot scrub nurses, like RoboNurse-VLA in 2025. None is on the market. Scrub runs one model across three settings on a low-cost arm. It puts instruments back in their slots, tracks the count, passes sharps hands-free, and handles bright glare |
| Would a clinic let this near a patient? | It never touches the patient. In a clinic it sits under a sterile drape on a medical-grade arm. Dental offices come first because sterile rules are simpler |
| What if it drops something or misses? | Every grasp is checked twice. The arm checks gripper closure and the overhead camera checks the slot. If a grasp fails, it retries once. If it misses again, it reports it out loud. Grasp check accuracy is [measured]% |
| What if the person moves their hand? | An overhead camera tracks the hand at 10 Hz. The arm updates its target to stay 8 cm short of the palm. If the hand leaves or an arm blocks the path, the robot freezes in place within [measured] ms |
| Why voice? Operating rooms are loud | Clinicians already ask for tools out loud. Scrub runs on a phone call with noise cancellation. A spacebar or foot pedal acts as an instant backup stop |
| How fast is it? | The median request-to-hand time is [measured] seconds. The dashboard displays the timer for each handoff |
| How much data did it need? | We recorded 25 demos per item, for 225 total. Adding the bench setting took [measured] minutes of demonstration time |
| Why use Perceptron's model instead of scripted paths? | Scripted motions fail when an item sits at an angle or lighting changes. The fine-tuned model handles shifts in angle, position, and glare. The success table shows [measured]% reliability |
| How does safety work? | The arm slows down near the hand. It stops short of the skin. The spacebar, voice command, or dashboard button stops the arm instantly in [measured] ms. Stop latches until an operator resets it |
| Who pays for this? | Dental practices first. They pay a monthly subscription per chair. It costs less than covering one unfilled assistant shift |
| Does it replace assistants? | No. It handles passing and counting. That frees scarce assistants to support more chairs and focus on patient care |
| What is next? | We plan to test on a medical-grade arm. We also plan to hand instruments before the doctor asks, based on the procedural step |
