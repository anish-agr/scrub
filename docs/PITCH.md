# Pitch, demo and video

Owner: Caiden. Anish speaks it. Fill the [measured] numbers from the success tables on Sunday morning.

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

## Demo video (2 to 3 minutes, required)

Shot list, in order. Record each shot several times and keep the best. Evan edits.

1. Title card (slide 1), 5 seconds.
2. A clinician with busy hands says "hemostat" to the phone. Close-up of the arm picking it, then the hand receiving it handle first, then the gripper letting go.
3. "Scalpel." The scalpel goes to the safe spot, "scalpel down" audible.
4. The return: hemostat in the return spot, back in its slot.
5. Lamp on, glare on the steel, a request still works. Cut to the lighting table on the dashboard.
6. The dental tray (mirror) and the bench tray (pliers).
7. "Count." The readback, then the summary text arriving on the phone.
8. The dashboard: the system diagram (slide 3) and the success tables.
9. Close on the team and the arm.

Record the phone audio clearly: put a second phone or a laptop mic near the speakerphone.

## Perceptron arm video

A separate clip for the robotics track: the arm doing several picks and returns across items and lighting, unedited, with the success table shown at the end.

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

