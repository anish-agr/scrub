# Surgeon Assistant: Buildout Ideas (product and company)

Status: brainstorm for DubHacks 2026 team. Training/research prototype framing only; no clinical claims (see SURGEON_RESEARCH.md section 6).
Inputs: prototypes/SURGEON_BRIEF.md, SURGEON_RESEARCH.md, BACKLOG.md Lane S, prototypes 01-34 (esp. 24 Scrub Nurse, 26 Scope Holder, 28 SutureCoach, 29 OR Case Board, 32 Tray Setup, 34 Be the Surgeon; plus 03 Episode Studio, 11 Arena, 16 Memory, 18 Pill Check, 21 Fleet, 23 Skill Store).

Scoring (each 1-5): **Feas** = technical feasibility with SO-101-class hardware in 12 months (5 = easy). **Pull** = market pull / urgency (5 = strong). **Reg** = regulatory burden (1 = light, 5 = heavy; lower is better). Scores are team judgement, not measured.

Light web research used (verify before quoting):
- SPD: ~40% of a sterile processing tech's time goes to tray assembly and labor is ~80% of SPD budgets; startups already exist (RIF Robotics, PacR). [HPN](https://www.hpnonline.com/sterile-processing/article/55263086/automation-in-the-sterile-processing-department), [Wellstar Catalyst on RIF](https://catalyst.wellstar.org/casestudies/rif-robotics/)
- Count software is clearable: SurgiCount+ (RFID sponge counting + AI blood-loss estimation) got a Class II 510(k), product code PBZ, March 2026. [Innolitics K252282](https://fda.innolitics.com/device/K252282)
- Surgical simulation market estimated ~$3.9B (2025) growing ~15% CAGR; estimates vary widely by source. [Towards Healthcare](https://www.towardshealthcare.com/insights/surgical-simulation-market-sizing)
- Already in repo research: RSI ~$2.4B/yr, handoffs ~7.7% of OR time in one study, 42.9% first-year surgical tech turnover.

---

## 1. Product directions (30)

### A. OR assistance
| # | Direction | Who pays | Reusable from hackathon | Feas | Pull | Reg |
|---|---|---|---|---|---|---|
| 1 | **Robotic scrub assistant**: voice request, handle-first handoff on palm gate (the 24 build) | Hospital OR / surgery center capex | Entire handoff stack: detector, palm gate, voice NLU, STOP | 2 | 4 | 5 |
| 2 | **Instrument-anticipation display (no arm)**: screen/AR that predicts and highlights the next instrument from the preference card | OR service line, scrub tech teams | Prefs/Markov, tray map, console UI (24, 32) | 4 | 3 | 3 |
| 3 | **Laparoscope holder, vision-steered** (26): keeps tool tips centered about a trocar pivot | Hospital; competes with AutoLap/FreeHand class | Tip tracking, steadiness score, voice | 2 | 3 | 5 |
| 4 | **Tray setup / back-table assistant**: reads the preference card, lays out Mayo tray, verifies each slot (32) | OR, ASC chains | OCR, few-shot detect, slot verify | 3 | 4 | 3 |
| 5 | **Third-hand retractor / suction holder** for open cases | Hospital | Bimanual future, voice, zone safety | 1 | 3 | 5 |
| 6 | **Specimen & suture-pack runner**: moves labeled specimens, tracks chain of custody | Pathology + OR | Verify step, OCR, Photon alerts | 3 | 3 | 3 |

### B. Sterile processing (SPD)
| 7 | **Tray assembly + inspection cell**: arm picks instruments from bins into set per count sheet, camera flags missing/damaged | Health systems, reprocessing contractors | Detector, count ledger, verify, preference/set cards | 3 | 5 | 2 |
| 8 | **Instrument ID and set-reconciliation camera station (no arm)**: drop a returned tray, get a pass/fail against the set list | SPD managers | Few-shot detect, ledger, OCR of tray tags | 5 | 4 | 2 |
| 9 | **Loaner / vendor tray check-in**: photograph, auto-count, flag mismatches before it reaches the OR | Hospital supply chain, device reps | Same as 8 | 5 | 3 | 1 |
| 10 | **Instrument wear / damage triage**: vision grading of jaws, tips, hinges for repair routing | SPD, repair vendors | Detection, Episode Studio style labeling | 3 | 3 | 2 |

### C. Training / education
| 11 | **SutureCoach**: JIGSAWS-style gesture segmentation + OSATS-like scoring on a foam pad, arm demonstrates expert motion (28) | Surgical residency programs, med schools, ST/tech programs | Video Q&A scoring, replay, skill library | 4 | 4 | 1 |
| 12 | **Robotic "patient and scrub partner" for scrub-tech students**: students practice calling for instruments and being handed them; arm plays surgeon or tech | Surgical technology programs (about 430 US programs) | 24, 34 game mode | 4 | 3 | 1 |
| 13 | **Box-trainer upgrade kit**: add camera + scoring to the $50 cardboard/plastic trainers residents already own | Residents, program directors, ACS/ASE style programs | Scoring pipeline, mobile UI | 5 | 4 | 1 |
| 14 | **Be the Surgeon competency exam**: scored handoff-call test for new scrub nurses | Hospital education depts | 34 scoring, Wilson CI eval | 4 | 3 | 1 |
| 15 | **Mentor-in-a-box**: arm physically guides a trainee's hand/tool along an expert path (haptic teaching) | Training programs, simulation centers | Teleop leader arm, replay, skill library | 3 | 3 | 2 |

### D. Safety / compliance
| 16 | **Count Guardian**: continuous sponge/instrument ledger that locks "close" until reconciled (BACKLOG S6) | Hospital patient safety / risk mgmt, malpractice insurers | Ledger, detector, Photon, timeline | 3 | 5 | 4 |
| 17 | **Sterile-field guardian**: camera detects contamination events (hand crossing line, dropped item), logs and prompts | Infection prevention depts | Zones editor (S10), multilook tick | 3 | 4 | 3 |
| 18 | **Timeout / checklist verifier**: listens and watches that WHO checklist steps actually happen | Quality dept, accreditation | Voice, phase recognition (29), OCR | 3 | 3 | 3 |
| 19 | **Medico-legal black box**: tamper-evident, privacy-scrubbed case record for disputed counts | Insurers, hospital counsel | Recorder, replay, timeline | 3 | 3 | 2 |

### E. Analytics / data
| 20 | **OR efficiency analytics** (29): handoff latency, turnover, phase durations from ceiling video | OR directors; ties to throughput revenue | Phase recognition, Tiger Data time series | 4 | 4 | 2 |
| 21 | **Preference-card optimizer**: find unused instruments per surgeon/case, shrink trays, cut reprocessing | Supply chain, SPD, CFOs | Prefs memory, ledger | 4 | 4 | 1 |
| 22 | **Surgeon skill benchmarking / coaching from real cases** (video) | Departments, device makers, payers | SutureCoach scorer, video Q&A | 3 | 3 | 3 |
| 23 | **Embodied-surgery dataset licensing**: de-identified handoff + tool-tip trajectories for robot learning labs | Robotics/foundation-model labs | Episode Studio, dataset doctor, recorder | 3 | 3 | 2 |

### F. Veterinary
| 24 | **Vet clinic scrub assistant and count system**: 1-2 person surgical teams, no scrub tech at all | Vet practices (emergency, spay/neuter high-volume clinics, shelters) | Entire 24/32/16 stack | 3 | 4 | 1 |
| 25 | **Shelter spay/neuter throughput kit**: tray setup + count + surgeon-solo assistant | Shelter networks, nonprofits, grants | Same | 3 | 3 | 1 |

### G. Global health / low-resource
| 26 | **Surgical-camp kit**: ruggedized tray verification + count + remote-mentor video (volunteer teams with a single scrub nurse) | NGOs (Mercy Ships style), WHO programs, grants | Telepresence (20), count ledger, offline mode | 3 | 3 | 1 |
| 27 | **Tele-mentored training station** with phone + cheap arm, expert coaches remotely and arm replays the move | Medical schools in LMICs, NGOs | 20 Reach Remote, 28 | 3 | 3 | 1 |

### H. Military / field
| 28 | **Forward-surgical-team assistant**: instrument handoff and counts with limited staff, offline, low power | DoD (SBIR/CDMRP), allied militaries | Offline perception, STOP/watchdog | 2 | 3 | 4 |
| 29 | **Casualty-care procedure trainer** (TCCC skills: tourniquet, packing) with scoring | Military training commands, EMS academies | SutureCoach scoring | 4 | 3 | 1 |

### I. Adjacent non-medical markets
| 30 | **Pharmacy compounding verifier** (sterile IV prep, check vial/label/volume, record) | Hospital & outsourcing pharmacies | Pill Check (18), OCR, verify, ledger | 3 | 4 | 3 |
| 31 | **Lab automation bench assistant** (hand pipettes/tubes, track plates, protocol memory) | Academic & biotech labs, core facilities | Skill library, task composer (14), memory (16) | 4 | 4 | 1 |
| 32 | **Electronics rework / soldering assistant** (hold board, present parts, count reels) | Repair shops, prototyping labs, defense electronics | Palm gate, detection, voice | 3 | 3 | 1 |
| 33 | **Dental assistant** (chairside instrument pass, four-handed dentistry; tray setup per procedure card) | DSOs, dental schools | 24 + 32 nearly one-to-one; dentistry has an acute assistant shortage | 3 | 4 | 3 |
| 34 | **Cleanroom / semiconductor tool-and-wafer-case tracker** | Fabs | Ledger, verify | 2 | 2 | 1 |

Quick reading of the table: the sweet spot (high pull, low reg, feasible) is **7/8 (SPD), 11/13 (training), 21 (preference-card analytics), 24 (veterinary), 31 (lab)**. The hackathon's most dramatic demo (1, 3) is the hardest and heaviest to commercialize.

---

## 2. Platform and moat thesis

**One-sentence thesis:** the company that owns the *verified, labeled record of what happened with every instrument in every case* owns the thing nobody else has, and the arm is just one of many sensors and actuators that produce it.

1. **Data flywheel.** Every handoff (request, instrument, slot, palm pose, latency, success, retry) and every count (item seen in/out, time, who) is a labeled episode. Episode Studio (03) cleans it, Arena (11) scores it, fine-tunes get better, more deployments follow. Moat is *labels with outcomes* (verified handoff, reconciled count), which video scraped from the web lacks. Honest caveat: SO-101-class data does not transfer to better hardware for free; the durable assets are perception labels (instrument ID, hand/palm, phase) and task/preference data, which are embodiment-independent.
2. **Preference-card memory.** Per-surgeon, per-procedure instrument order and quirks (Backboard memory, Markov fallback). Becomes switching cost: a surgeon's cards live in your system. Extend to the supply-chain side (card optimizer, direction 21), which gives a CFO-grade ROI story with no robot.
3. **Skill library.** Named, evaluated primitives (`handoff`, `return_to_tray`, `present_count_tray`, `hold_scope`) with Wilson-CI evals, safety ratings and calibration checks (Skill Store 23). Skills are versioned, signed, and gated per site. Sell skills as software updates.
4. **Hardware-agnostic layer.** `ArmBackend` interface (A1) + camera service + policy client means the same product runs on SO-101, a Franka/UR/xArm, or a purpose-built arm. Position the software as the product and the arm as a BOM line. Cheap arm is a *wedge* (training, vet, labs, SPD bins), not the end state in the OR.
5. **Trust layer as a moat.** Zones, palm gate, watchdog, STOP, audit trail and replay (A6, S3, S10, A8) are what regulators and hospital risk committees buy. Competitors can copy a demo; a validated safety case plus site evidence is slow to copy.
6. **Network effects, small but real:** shared skill evals, shared instrument-ID few-shot libraries (one photo per instrument; vendors' catalogs), benchmark data across sites.

---

## 3. Three company shapes

### Shape 1: "SPD automation company" (back-of-house first)
- **Thesis:** The sterile processing department is the most automatable corner of the hospital: fixed bins, known instrument catalogs, repetitive tray assembly (~40% of tech time), severe turnover, and no patient contact, so a far lighter regulatory path than the OR. Competitors exist (RIF Robotics, PacR), so win by being cheap, software-led and retrofit: a camera-first inspection station that later gains an arm.
- **First product:** Set-reconciliation camera station (direction 8), then a low-cost pick-and-assemble cell for the 20 most common sets.
- **First customer:** One mid-size community hospital or a reprocessing contractor with a 15-20 person SPD; pilot paid by the SPD/supply chain budget.
- **18-month milestone:** 3 paying sites, >99% verified tray accuracy on 10 set types over 5,000 trays, documented minutes saved per tray, one arm cell assembling real (non-sterile, then reprocessed) sets under supervision, $300-500K ARR.

### Shape 2: "Surgical training hardware + SaaS"
- **Thesis:** Training has the lowest regulatory burden, an eager institutional buyer (programs must document competency), and a rising, subjective-scoring pain (OSATS/GEARS rater bottleneck). Sell a $500-2,000 camera-and-arm box trainer kit plus a per-seat scoring subscription. The arm demonstrates, the camera scores, the dashboard shows progress; this naturally builds the labeled skill dataset.
- **First product:** SutureCoach on existing box trainers (direction 13), arm demo as premium tier.
- **First customer:** One surgical-technology program and one general surgery residency simulation lab (the same trainees later become OR buyers/influencers).
- **18-month milestone:** 10 programs, 300 active learners, a validation study showing score agreement with expert raters (correlation with blinded OSATS) submitted for publication, $200-400K ARR, and a program-director advisory board.

### Shape 3: "OR perception software that later adds an arm"
- **Thesis:** Start with ceiling/tray cameras and software (count ledger, phase timeline, preference-card analytics, tray setup verification) sold as an OR quality and efficiency product, with a clean regulatory strategy (non-device analytics first, then a cleared adjunct like the SurgiCount+ precedent). Collect the largest labeled OR corpus, then introduce the arm as the actuator once perception, trust and site relationships exist.
- **First product:** OR Case Board + preference-card optimizer (directions 20-21), count verification as the second module.
- **First customer:** A single ambulatory surgery center chain (fast procurement, throughput-driven, fewer committees).
- **18-month milestone:** 5 ORs live, 2,000 cases recorded with privacy controls, a measured reduction in tray size / reprocessing cost for a pilot service line, pre-submission meeting with FDA for the count module, first arm handoff pilot in simulation lab.

**Recommendation matrix:** Shape 2 is fastest to revenue and safest; Shape 1 has the clearest ROI and hiring-pain narrative; Shape 3 has the biggest end-state but longest road. A defensible plan is Shape 2 for hackathon-to-first-revenue, with Shape 1 or 3 as the funded follow-on.

---

## 4. Technical roadmap

### Harden after the hackathon
| Area | Today (SO-101) | Next | Why |
|---|---|---|---|
| Accuracy / hardware | ~5 mm repeatability, 0.3 kg, 0.38 m reach | Evaluate a stiffer arm (e.g., 6-DoF with encoders, or an upgraded SO-ARM/Koch-class, or industrial cobot) behind the same `ArmBackend`; add wrist camera + closed-loop visual servoing | Handoffs need cm, not mm; closed-loop beats open-loop |
| Gripper | 3D-printed tips | Instrument-specific passive-compliance fingers; **autoclavable** tips (PEEK/PPSU, stainless sleeves) and a quick-swap tool changer; a handle-side cradle that always presents handle-first | Sterility and grip on ring handles |
| Sterility | Props only | Sterile arm drape + sterile adapter interface (like robotic-surgery drapes), wipeable enclosure, defined sterile/non-sterile zones, no sterile items touching the base | Prerequisite for any real OR use |
| Force/contact | None | Motor-current-based contact detection, then a wrist force/torque or tactile sensor; hard force limits at the palm handoff; compliant release | Safety; also enables suturing/retraction research |
| Bimanual | Single arm | Two SO-101-class arms (ALOHA-style) for pass-and-hold, tray reorganization, scope + tool | Unlocks scope holding and retraction |
| Perception | Perceptron few-shot, mock fixtures | Multi-view depth, tray-slot fiducials, glove/skin tone / lighting robustness, drape glare, mask occlusion tests | The real failure source |
| Safety case | Palm gate, STOP, watchdog | Documented hazard analysis (ISO 14971), IEC 60601-1/-1-2 electrical safety, software lifecycle (IEC 62304), cybersecurity, fault-injection tests | Needed for any regulated path |
| Learning | ACT/SmolVLA, scripted poses | Larger demo sets (S8), eval harness with CIs (S9), sim-to-real for tray layouts | Reliability numbers investors respect |
| Data/privacy | Mock data | De-identification (faces blurred, audio redacted), on-prem edge inference, HIPAA/BAA, audit logs | Hospital procurement gate |

### Open research questions
1. What is the minimal handoff success rate and latency that surgeons *actually* accept versus a human tech (Gestonurse reported ~0.83 s slower; where is the threshold)?
2. Can few-shot (one photo) detection reliably identify hundreds of near-identical instruments (forceps variants) under drape glare and blood?
3. Can anticipation (next-instrument prediction) from phase + preference card beat voice requests in time-to-instrument, and does it generalize across surgeons?
4. How well does video-LLM skill scoring correlate with expert OSATS/GEARS ratings, and is it robust to camera placement and tool type? (The 95-100% literature numbers are usually on small, within-dataset benchmarks.)
5. How to guarantee safe contact with a human hand under perception failure (hardware-limited force/torque vs. software gates)?
6. Does robot-demonstrated expert motion improve learning compared to video alone? (A real RCT-grade question and publishable.)
7. Can a policy trained on a cheap arm transfer to a better arm with small adaptation, and what is the data cost?
8. What is the right evidence pathway: de novo vs 510(k) with predicates (count adjuncts, camera holders), and what is the intended-use wording that keeps early products outside device regulation (training, analytics)? Talk to a regulatory consultant early.
9. Human factors: do surgeons trust a silent arm, and does the arm's presence change team communication?

---

## 5. Five "what if" ideas that make a judge or investor lean in

1. **"The flight data recorder for the operating room."** Every case produces a privacy-safe, tamper-evident replay of every instrument and count. Insurers discount malpractice premiums for sites that run it; a disputed retained-item case is resolved by replay, not memory. Pitch: patient safety becomes provable, and the payer is the insurer, not the OR budget. (Builds on 16, 19, 29.)
2. **"Surgery school in a shoebox."** A $500 kit (camera + printed trainer + optional SO-101) puts expert-scored practice into every residency and every low-resource medical school; the arm *physically demonstrates* the expert motion and a remote mentor can drive it from a phone. Pitch: training more surgeons where there are none, directly on the Community Kitchen "technology that helps people thrive" track. (28, 20, 22.)
3. **"The preference card that learns."** The system observes what each surgeon *actually* uses, shrinks the tray by 20-30% (claim only after measuring), and writes the card itself. A hard-dollar ROI (fewer reprocessed instruments, less SPD labor) on day one, with no robot and no FDA, and it quietly collects the dataset for the robot. Investors like the wedge that pays for the moonshot. (32, 21, S7.)
4. **"A robot that never touches the patient."** Reframe safety as the product: the arm lives only on the back table and in SPD, handling instruments, never the patient or the sterile field's human. Pitch regulators and nurses with "augments, never replaces," and show the palm gate, STOP and zones as the headline feature rather than a footnote. A judge worried about safety becomes the advocate. (24, S3, S10.)
5. **"Skill library as an app store for physical expertise."** A master scrub tech, vet tech or lab scientist demonstrates a procedure ten times via teleop; it becomes an evaluated, rated, purchasable skill that runs on any arm (23, 13, 14). Revenue share to the experts. Pitch: the hospital shortage becomes a marketplace of codified expertise, with the veterinary clinic or the field-hospital NGO as the first underserved buyers and the DoD as the exit-scale buyer.

---

## Top 3 recommendations (also in summary)
1. **Lead with training (SutureCoach/box-trainer kit, direction 11/13)** as the commercial wedge: lowest regulatory burden, institutional buyer, builds the labeled skill dataset; use the OR scrub-nurse arm as the pitch-day wow factor.
2. **Pair it with the camera-only count and tray verification line (7/8/16/21)**: real ROI and patient-safety story, SPD/ASC buyers, and no arm required. This is the bridge to the arm.
3. **Position the long-term company as a hardware-agnostic safety-and-data platform** (preference-card memory, skill library, audit replay), with vet and dental as the first low-friction places to deploy the arm after the OR is de-risked.

## Caveats
- Market sizes cited are third-party estimates that disagree by 5-10x; do not put a single TAM number on a slide without citing it.
- Competitors in each category (RIF Robotics, PacR for SPD; AutoLap/FreeHand for scope holding; existing RFID count vendors; da Vinci for robotic surgery) should be researched in depth before an investor conversation.
- All regulatory notes are starting hypotheses, not legal advice.
