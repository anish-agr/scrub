# Surgeon idea addendum (read after BRIEF.md)

Concept: the SO-101 as a **surgical assistant** for training and the operating room support role. It is a hackathon
demo, so it uses props only: plastic or 3D-printed instruments (scalpel handle with no blade, forceps, scissors,
clamps, needle driver), gauze sponges, a foam suture pad, a cardboard laparoscopic box trainer, and a toy patient.
No real sharps near people. The UI must say clearly that it is a training/research prototype, not for clinical use.

Real problems to anchor on (cite carefully, the research agent fills in numbers in SURGEON_RESEARCH.md):
- Retained surgical items (sponges, instruments left inside patients) are a "never event". Manual counts fail.
- Shortage of surgical technologists / scrub nurses. Surgeons wait on instrument handoffs.
- Laparoscopic camera holding is tedious work for a human assistant (products like AutoLap, AESOP did this).
- Surgical skill assessment (OSATS / GEARS scores) is slow and subjective. Datasets like JIGSAWS label gestures
  (G1 reach for needle, G2 position needle, G3 push needle through tissue, ... G11 drop suture).
- Tremor and motion scaling are what make teleoperated surgery (da Vinci) precise.

SO-101 reality: about 0.3 kg payload, about 0.38 m reach, mm-level repeatability is NOT guaranteed (expect around 5 mm).
Lean on perception, verification, voice and UI, and keep the physical motion to one robust primitive
(pick an instrument from a fixed tray slot and present it handle-first into an open palm zone).

Perceptron use: detection of instruments (few-shot exemplars, one photo per instrument), OCR of tray tags,
hand/palm detection for the handoff, video Q&A + clips for surgical phase recognition and skill scoring,
tracking instrument tips over time. Photon: text the circulating nurse / attending. Gemini: voice intent.
Tiger Data: instrument and motion time series. Backboard: surgeon preference cards remembered.

Visual direction for the surgical set: clinical but premium. Each prototype still gets its own identity
(surgical green/teal drapes, OR monitor dark UIs, medical device HMI, training-app brights), not one template.
Files are numbered 24 and up. Same rules as BRIEF.md (single HTML, mock data, alive in 2s, STOP, comments header).

Track framing: the "Let's Get Cookin'" theme does NOT require cooking. Community Kitchen = "Build technology that helps
people thrive" (accessibility, healthcare, equity). Pitch the surgeon assistant as healthcare access / patient safety /
training more surgeons. Do not force food or kitchen imagery into these prototypes.
