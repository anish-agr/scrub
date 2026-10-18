# Video narration

The words below are the captions and the narration in `video/roughcut.py` (the `BEATS` list). Change a line there and here together. Narration is about 2:20 to 2:40 read at a normal pace; the whole cut must stay under 3:00 (the rough cut prints its length and each beat's seconds).

Record one line per voice memo, quiet room, and name it exactly as in the left column (`python -m video.roughcut --lines` prints the same list). Drop it in `data/video/kit/real/`; it plays under its line on the next rebuild. Lines in quotes with no speaker are said on camera (the ask) and are captioned only over a real take.

Scope: three instruments (scalpel, hemostat, Mayo scissors). No safe spot. No hand tracking: the arm slows down as it nears the handoff point. Picks are skills we taught it (recorded demonstrations), not a trained model. Return on the real arm is manual; the electromagnet return is simulation only and labeled so.

## Title (3 s)

Card: "Scrub. A robot arm that passes surgical instruments when you ask." No one speaks.

## V1 Hemostat

| Memo | Speaker | Line |
| --- | --- | --- |
| V11-Anish-1 | Anish | Surgeons work with a scrub tech who hands them each instrument. Hospitals can't hire enough of them. |
| V11-Anish-2 | Anish | When nobody is there, the surgeon looks away from the patient and searches the tray. |
| (on camera) | lab coat | "Hemostat." |
| V11-Anish-3 | Anish | This is Scrub. You ask out loud. It picks the hemostat with a skill we taught it. |
| V11-Anish-4 | Anish | It slows down as it nears the handoff point and holds the handle out. |
| V11-Anish-5 | Anish | It lets go when you pull, then goes straight home on its own. |

A real Photon call is unconfirmed. Don't say "on the phone" or "phone call" in narration or on a card unless a real call is on video; then Anish-3 can become "You ask out loud, on a phone call." The thermal guard reads motor temperatures every 2 s; if you add a number to the thermal line, use that one.

## V2 Mayo scissors

| Memo | Speaker | Line |
| --- | --- | --- |
| (on camera) | lab coat | "Mayo scissors." |
| V11-Caiden-1 | Caiden | It knows three instruments: the scalpel, the hemostat and the Mayo scissors. |
| V11-Caiden-2 | Caiden | We taught it each pick by moving the arm ourselves. |

## V3 Stop mid-move

| Memo | Speaker | Line |
| --- | --- | --- |
| (on camera) | lab coat | "Stop." |
| V11-Caiden-3 | Caiden | Say stop and the arm freezes where it is. |
| V11-Caiden-4 | Caiden | It stays stopped until someone resets it. Then it finishes the pass. |

## V4 Manual return (labeled "MANUAL RETURN")

| Memo | Speaker | Line |
| --- | --- | --- |
| V11-Evan-1 | Evan | On the real arm, putting a tool back is manual for now. A person sets it back in its slot. |

## Simulated return (sim-return.mp4, labeled "SIMULATED RETURN (electromagnet)")

| Memo | Speaker | Line |
| --- | --- | --- |
| V11-Evan-2 | Evan | In simulation we modeled the return with an electromagnet that picks the tool up and puts it back. |

## V5 Lighting (conditional)

Say this only after the bright, normal and dim tries are logged. The rough cut plays it only when a real `V5` take exists; otherwise the beat is a 3 s TO FILM card with no narration. Cut the beat from the final if the tries aren't logged.

| Memo | Speaker | Line |
| --- | --- | --- |
| V11-Evan-3 | Evan | Operating lights are bright and steel throws glare. We ran handoffs in bright, normal and dim light. |

## V6 Thermal

| Memo | Speaker | Line |
| --- | --- | --- |
| V11-Brandon-1 | Brandon | These motors heat up when they hold a pose. |
| V11-Brandon-2 | Brandon | Scrub watches every motor's temperature, and between requests it folds to rest with the torque off. |

## V7 Dashboard count and count sheet

| Memo | Speaker | Line |
| --- | --- | --- |
| V11-Brandon-3 | Brandon | The dashboard keeps the count of what's out. |
| V11-Brandon-4 | Brandon | It reads the paper count sheet with Perceptron's OCR, with Gemini as a fallback, and shows any mismatch. |

## V8 Tray check

| Memo | Speaker | Line |
| --- | --- | --- |
| V11-Brandon-5 | Brandon | Perceptron's vision checks the tray from one overhead frame and finds all three instruments. |

## V9 Model picks (optional)

Only if a Perceptron model is deployed and a real model pick is on video (0 deployments as of 07:10). Left out of the cut until `V9` exists. If it arrives, this is the one place we say "model trained on our demonstrations"; every other pick stays "a skill we taught it".

| Memo | Speaker | Line |
| --- | --- | --- |
| V11-Caiden-5 | Caiden | These picks run on a model trained on our demonstrations. Every try is in the table. |

## V10 How it works (two plain cards, then the sim)

| Memo | Speaker | Line |
| --- | --- | --- |
| V11-Caiden-6 | Caiden | How it works. Gemini turns what you said into one instrument from the tray. |
| V11-Caiden-7 | Caiden | Perceptron's vision finds it, and the arm runs the skill we taught it. |
| V11-Caiden-8 | Caiden | Our code keeps it in bounds: speed and joint limits, a grasp check before it carries, and release only on a pull. |
| V11-Anish-6 | Anish | Here is the same routine in simulation. |

## Close (end card)

| Memo | Speaker | Line |
| --- | --- | --- |
| V11-Anish-7 | Anish | Scrub never touches the patient. It's a research prototype, not a medical device. |
| V11-Anish-8 | Anish | A clinic version would run under a sterile drape on a medical-grade arm, like today's surgical robots. |
| V11-Anish-9 | Anish | It helps scrub techs. It doesn't replace them. We're Anish, Caiden, Evan and Brandon. This is Scrub. |

## Out of this cut

The safe spot, "never hand to hand", hand tracking, degraded control when a motor goes down, and the case-summary text are all out. Add the text back only if Photon sends a real one on video.
