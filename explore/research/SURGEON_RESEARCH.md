# Surgical Assistant Research: SO-101 Context

## 1. Retained Surgical Items: Incidence, Cost, and Prevention Technology

### Incidence and Patient Impact
Retained surgical items (RSIs) occur in approximately **1 in 5,500 to 18,760 inpatient surgeries**. Sponges account for **34% of retained items**, making them the most common object left inside patients. RSIs are classified as a "never event" by healthcare regulators and carry serious consequences: patients with RSIs experience **2.14% higher mortality**, excess hospital stays averaging **2.08 days**, and excess costs of **$13,315 per incident**.

### Financial Burden
The financial impact is staggering. A single retained surgical item can cost a facility approximately **$525,000–$600,000**, including corrective surgery, legal fees, and malpractice claims ranging from **$150,000 to $5 million per incident**. Nationally, retained surgical items cost the healthcare system an estimated **$2.4 billion annually**.

### Why Manual Counts Fail
Manual sponge and instrument counts remain the standard prevention method but are inherently unreliable. Contributing factors include: surgeon distractions, communication failures between team members, poor count documentation, and inconsistent counting protocols. In laparoscopic surgery, limited visualization of body cavities compounds the difficulty.

### Existing Technology Solutions

**RFID Sponges:** Surgical sponges embedded with passive high-frequency RFID tags can be tracked without line-of-sight, making counts faster and more accurate. [ORLocate RFID-enabled System for Surgical Sponges and Instruments Gets FDA Clearance](https://www.rfidjournal.com/?p=83676)

**Barcode and Radio-Opaque Markers:** Sponges and instruments are tagged with barcodes or radio-opaque markers for imaging verification. These methods require additional steps (scanning, X-rays) and do not eliminate the need for manual counting.

**Regulatory Framework:** Retained surgical items are reportable as serious events by The Joint Commission and the National Quality Forum. No national reporting system exists, limiting data accuracy.

Sources:
- [Retained Surgical Items: Cost and Prevention](https://www.beckershospitalreview.com/quality/the-high-cost-of-inaction-retained-surgical-sponges-are-draining-hospital-finances-and-harming-reputations/)
- [Retained Surgical Sponges Cost-Benefit Analysis](https://pubmed.ncbi.nlm.nih.gov/25081938/)
- [Risk Factors and Preventive Strategies for RSIs](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8276389/)


## 2. Surgical Technologist and Scrub Nurse Shortage (US 2024–2026)

### Current Workforce Numbers
As of 2025, there were **117,460 employed surgical technologists** in the US (Bureau of Labor Statistics). This workforce is critically understaffed relative to surgical demand.

### Shortage Severity
- **Turnover Crisis (UNCONFIRMED, don't use on stage):** 42.9% first-year turnover and 55.6% 90-day turnover among surgical technologists. The comb found no source for surgical techs; the only 42.9% found is a circulating-nurse rate in one cardiovascular OR
- **Staffing Delays:** Filling a surgical technologist position takes an average of **120 days**
- **Exodus Trend:** 28% of technicians plan to leave their role by end of 2025, with **42% citing pay and benefits as the primary driver**
- **Training Pipeline Decline:** Accredited surgical technology programs have decreased from over 500 to approximately 430 programs, narrowing the supply pipeline

### Workload Pressures
68% of surgical technologists report increased demand for surgical care, indicating rising pressure on an already-strained workforce.

### Impact of Instrument Handoffs on OR Efficiency
Surgical instrument handoffs consume significant operative time:
- **Single handoff impact:** Increases operative time by 3.89 minutes (knee arthroplasty) to 6.20 minutes (hip arthroplasty)
- **Multiple handoffs:** Two or more handoffs increase operative time by 15.99–18.52 minutes
- **Staff handoff frequency (scrub nurse SHIFT handoffs, not instrument passes; never say "instrument handoffs"):** In one study, 74 handoffs occurred across 2919 minutes of OR time, totaling 225.2 minutes (7.7% of operative time)
- **Interruptions:** 45.1% of handoffs were interrupted or delayed due to competing activities

Sources:
- [Surgical Technologist Shortage Explained](https://www.beckershospitalreview.com/academic-medical-center/academic-medical-centers-workforce/the-surgical-technologist-shortage-explained/)
- [Staffing Shortages Strain US Healthcare Technicians](https://www.staffingindustry.com/news/global-daily-news/staffing-shortages-strain-us-healthcare-technicians)


## 3. Prior Robotic Scrub Nurse Research and Laparoscopic Camera Holders

### Robotic Scrub Nurse Systems

**Gestonurse (Purdue University)**
Developed by Juan Pablo Wachs at Purdue University in collaboration with Indiana University School of Medicine, Gestonurse was the first multimodal robotic scrub nurse to assist surgeons. It recognizes hand gestures and voice commands, mapping them to surgical instruments in a tray. Key performance metrics: **95% gesture recognition accuracy** and only **0.83 seconds slower** on average compared to human task performance. Gestonurse tracks instruments in use and reduces risk of instrument retention.

Sources:
- [Gestonurse: A Robotic Scrub Nurse that Understands Hand Gestures](https://www.iceira.ntu.edu.tw/en/research-direction/309-gestonurse)
- [Rethink Robotics: Juan Pablo Wachs](https://engineering.purdue.edu/IE/rethinkIE/wachs)

**Penelope (Columbia University)**
Developed by Dr. Michael R. Treat at Columbia University, Penelope is a wheeled cart with a robotic arm that automatically unpacks sterile instrument cases and arranges instruments likely to be needed. It responds to surgeon voice commands and uses visual processing to retrieve and return instruments. Penelope can anticipate surgeon preferences and assists in maintaining accurate instrument counts. Clinical testing occurred at New York-Presbyterian Hospital.

Sources:
- [Penelope, the Surgical Robot Assistant](https://we-make-money-not-art.com/penelope_the_su/)
- [Will Robot Penelope Replace a Scrub Nurse?](https://reliasmedia.com/articles/3871-will-robot-penelope-replace-a-scrub-nurse)

### Laparoscopic Camera Holder Systems

**AESOP (Automated Endoscopic System for Optimal Positioning)**
Developed in the 1990s with NASA funding, AESOP was one of the first robotic camera holders for laparoscopic surgery. The AESOP 2000 (1996) featured voice control, allowing surgeons to adjust the laparoscope with spoken commands, freeing the assistant's hands.

**FreeHand**
FreeHand uses head-mounted infrared sensors and an activation pedal, allowing surgeons to control the laparoscope through natural head movements. Clinical research demonstrated: **36-minute reduction in operative time**, trend toward fewer adverse events, shorter hospital stays, and reduced post-operative clinic visits.

**AutoLap**
AutoLap uses image-based steering, a novel method for robotic camera control studied in randomized controlled trials to improve efficiency and user experience in routine laparoscopic procedures.

### What These Systems Lacked
Prior systems focused narrowly on single tasks (camera holding or instrument retrieval) but did not integrate gesture recognition, anticipatory instrument selection, or comprehensive skill assessment. Most relied on single modalities (voice or head motion) rather than multimodal input. Clinical adoption was limited due to cost, interface complexity, and lack of training benefit integration.

Sources:
- [Comparison of Laparoscopic Procedures With AutoLap](https://clinicaltrials.gov/study/NCT02934542)
- [Robotic Camera Holder Assists Laparoscopic Surgery](https://mobile.hospimedica.com/surgical-techniques/articles/294720608/robotic-camera-holder-assists-laparoscopic-surgery.amp.html)
- [FreeHand Reduces Operating Time](https://buildingbetterhealthcare.com/freehand-robotic-camera-holder-reduces-operating-time-in-laparoscopic-surgery--143580)


## 4. Surgical Skill Assessment: OSATS, GEARS, JIGSAWS, and Automated Video Assessment

### OSATS (Objective Structured Assessment of Technical Skills)
OSATS assesses six dimensions: Respect for Tissue, Time & Motion, Instrument Handling, Flow of Operation, Knowledge of Instruments, and Overall Score. Each dimension is scored on a **1–5 ordinal scale**, yielding a total score range of **20–100 points** (General rating: 6–30; Specific technical skills: 14–70). OSATS is feasible for use in the operating room but has reported inter-rater reliability challenges.

Sources:
- [Using OSATS Global Rating Scale](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3574562/)

### GEARS (Global Evaluative Assessment of Robotic Skills)
GEARS is a validated robotic surgery adaptation of laparoscopic assessment tools, specifically designed to evaluate robotic and force control parameters. Key findings: GEARS differentiates skill levels with excellent construct validity, correlates with improved patient outcomes, and can be assessed by non-expert raters with good inter-rater reliability. GEARS correlates with automated performance metrics.

Sources:
- [External Validation of GEARS](https://vivo.weill.cornell.edu/display/pubid25609318)
- [SurgSkill-Bench: Multimodal Surgical Skill Assessment](https://arxiv.org/pdf/2608.30872)

### JIGSAWS Dataset and Gesture Vocabulary (G1–G15)
The JHU-ISI Gesture and Skill Assessment Working Set (JIGSAWS) is a public benchmark surgical activity dataset. Eight surgeons with varying expertise perform three surgical tasks on the da Vinci Surgical System and provide 15 low-level gesture labels—the smallest intentional action units toward a specific goal.

**JIGSAWS Gesture Vocabulary:**

| Gesture | Description |
|---------|-------------|
| G1 | Reaching for needle with right hand |
| G2 | Positioning needle |
| G3 | Pushing needle through tissue |
| G4 | Transferring needle from left to right |
| G5 | Moving to center with needle in grip |
| G6 | Pulling suture with left hand |
| G7 | Pulling suture with right hand (no video data) |
| G8 | Orienting needle |
| G9 | Using right hand to help tighten suture |
| G10 | Loosening more suture |
| G11 | Dropping suture at end and moving to end points |
| G12 | Reaching for needle with left hand |
| G13 | Making C loop around right hand |
| G14 | Reaching for needle with right hand |
| G15 | Pulling suture with both hands |

Note: G7 has no associated video data; only 14 gesture labels are available in practice.

Sources:
- [Joint Surgical Gesture and Task Classification](https://arxiv.org/pdf/1805.00721)
- [Gesture Recognition in Robotic Surgery: a Review](https://arxiv.org/pdf/2102.00027)
- [JIGSAWS Dataset](https://cirl.lcsr.jhu.edu/wp-content/uploads/2015/11/JIGSAWS.pdf)

### Automated Video Assessment Research
Deep learning approaches enable objective, scalable surgical skill assessment. Research has demonstrated:

- **High Accuracy:** Inflated 3D ConvNet models achieve **95.1%–100% accuracy** in skill classification from surgical video snippets
- **Dual Assessment:** Systems provide both summative assessment (overall skill rating) and formative assessment (visual heatmaps highlighting features correlated with performance)
- **Scalability:** Automated video analysis offers a scalable alternative to expert observation, reducing labor and cost
- **Current Limitation:** Training models require large annotated surgical video datasets, which remain scarce in practice

Sources:
- [Video-based Surgical Skill Assessment Using 3D CNNs](https://arxiv.org/pdf/1903.02306)
- [Deep Learning for Video-based Assessment of Surgical Skills](https://dspace.rpi.edu/items/26bc67d0-5ce2-4de4-8fa6-00c811e63de4)


## 5. Hackathon Context: Winners, Judge Criteria, and Pitch Strategy

### Past Hackathon Medical Robot Winners (2023–2024)

**2023 TAU MedTech Hackathon (Tel Aviv University)**
- **1st Place – OReye:** Computer vision solution for operating room safety and team stress reduction
- **2nd Place – Mommies:** Maternal health wellness app for peripartum depression detection
- **3rd Place – ABC3D:** Personalized breast reduction surgical planning using AI

**2024 World Robot Contest**
Beijing Institute of Technology's "MicroMedical Smart Control" portable positioning surgical robot won the Innovation and Creativity Group in the Coexisting-Cooperative-Cognitive Robots championship.

**2025 KUKA Innovation Award (Medical Robotics Challenge 2.0)**
Five finalist teams are developing robotic solutions including: gentler spinal surgery, vascular disease screening, robotic orthopedic assistance, and portable MRI-control robots.

Sources:
- [Winners of TAU MedTech Hackathon](https://en-med.tau.ac.il/node/8164)
- [BIT's Surgical Robot Scores Top Award at 2024 World Robot Contest](https://english.bit.edu.cn/2024-09/20/c_1023727.htm)
- [KUKA Innovation Award 2025](https://www.kuka.com/en-gb/company/press/news/2024/08/finalisten-innovation-award-2025)

### Judge Evaluation Criteria for Surgical Robots

Judges assess entries on **innovation, application, and design** in how robots improve procedures (faster recovery, smaller scars, less blood loss, less pain, earlier return to work, shorter hospital stays). Working prototypes are preferred, but designs and plans are considered. However, judges emphasize the following challenges and expectations:

**Safety:** Robots must demonstrate failsafe mechanisms, collision detection, and motion limits. Prior incidents of uncontrolled robotic motion create high scrutiny of control systems.

**Clinical Validity:** Claims must be evidence-based. Hackathon prototypes cannot make clinical efficacy claims without pilot data. Judges expect realistic limitations acknowledgment.

**Sterility and Material Compatibility:** Humanoid systems lack autoclavable components, which is a **critical barrier to OR use**. Any robot intended for the OR must address sterilization without impairing sensor function or calibration. Training prototypes using non-sterile props (plastic instruments, foam pads) avoid this barrier.

**Regulatory Pathway:** IDEAL Robotics framework guides surgical robot evaluation through preclinical, comparative, and monitoring stages. Judges expect applicants to understand the development stage their prototype occupies.

Sources:
- [Surgical Robot Challenge 2025](https://www.hamlynsymposium.org/surgical-robot-challenge-2025/)
- [New Framework for Surgical Robot Evaluation](https://www.uclhospitals.brc.nihr.ac.uk/news/new-framework-outlines-how-develop-evaluate-and-monitor-surgical-robots)
- [In Vivo Feasibility of Humanoid Robots in Surgery](https://arxiv.org/pdf/2607.07972)

### 30-Second Pitch for SO-101 (Training Context)

**"SO-101 is a training prototype that simulates a robotic scrub nurse for surgical education. It demonstrates multimodal gesture recognition for instrument handoff, tracks surgical items to prevent retention errors, and uses video analysis to score trainee skill in real time. This accelerates surgical technologist training while reinforcing patient safety protocols in a risk-free environment."**

---

## 6. Top 5 Risky Claims to Avoid on Stage

1. **"This robot eliminates retained surgical items."** – RSIs have multifactorial causes (communication, attention, procedure complexity). No single device guarantees prevention. Safer claim: "Augments manual counting with redundant instrument tracking."

2. **"FDA clearance path is straightforward."** – Surgical robots require extensive validation, clinical trials, and may fall into novel device categories. Safer claim: "Designed as a research and training tool with a clear regulatory roadmap following IDEAL framework."

3. **"Replaces surgical technologists/scrub nurses."** – Creates political opposition from clinical staff and regulators. Safer claim: "Supports technologists by automating tedious tasks, allowing them to focus on patient care and mentorship."

4. **"Achieves da Vinci-level precision with low cost."** – da Vinci costs $1.5M+ and required decades of development. Claiming cost parity or precision without evidence undermines credibility. Safer claim: "Demonstrates low-cost gesture recognition and basic manipulation for training applications."

5. **"This is ready for clinical use."** – A hackathon prototype with plastic props cannot make clinical claims. Judges will challenge sterility, safety certification, and regulatory status. Safer claim: "This is a proof-of-concept for training and research, not clinical deployment."

---

## Summary (150 words)

Retained surgical items cost hospitals $2.4 billion annually; sponges account for 34% of cases. Manual counting fails due to communication breakdowns and limited visibility. RFID and barcode sponges provide existing solutions but require procedural integration. Surgical technologist shortages are acute: 28% plan to leave by 2025, with position-filling taking 120 days. Scrub nurse shift handoffs (not instrument passes) took 7.7% of OR time in one study. Prior robotic systems (Gestonurse at Purdue achieved 95% gesture recognition; Penelope at Columbia uses voice commands; AESOP, FreeHand, and AutoLap focused on laparoscopic camera control) addressed single tasks without integrated training benefits. GEARS and OSATS assess robotic and manual surgical skill; JIGSAWS provides labeled video datasets (G1–G15 gestures); deep learning achieves 95–100% accuracy on video skill assessment. Hackathon winners emphasize safety, clinical validity, and sterility barriers. Five risky claims to avoid: claiming prevention of retained items, oversimplifying FDA clearance, replacing technologists, matching da Vinci precision, and claiming clinical readiness.

Sources:
- [Retained Surgical Items in Healthcare Finance](https://www.healthcarefinancenews.com/news/damages-left-behind-surgical-tools-top-billions-systems-seek-end-gruesome-errors)
- [OR Manager Surgical Tech Shortage](https://www.ormanager.com/tag/surgical-technologists/)
