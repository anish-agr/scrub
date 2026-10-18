# Building Scrub: An Open-Source Robot Scrub Assistant

By Team Scrub at DubHacks 2026.

## The Problem: The Empty Chair Next to the Doctor

Surgeons and assembly technicians work best when an assistant hands them instruments. Today, operating rooms cannot hire enough of those assistants.

In hospitals, surgical technologist positions stay vacant for an average of 120 days. First-year staff turnover exceeds 42%.

When an assistant is missing, the clinician must repeatedly look away from the patient, drop what they are holding, and search through a metal tray. In delicate procedures, those interruptions cost time and break concentration.

We built Scrub to solve this problem. Scrub is an open-source robotic assistant that listens to voice commands, picks instruments from a tray, brings them handle-first to an open hand, and puts them back when finished.

## System Architecture

Scrub consists of four modular processes that talk to each other over clean HTTP and WebSocket contracts:

1. **Voice Input and Understanding:** The clinician speaks into a phone on speaker. A Photon telephone endpoint receives the call. ElevenLabs converts speech to text. Google Gemini extracts the target instrument name against the active tray catalog. The system also maps common clinical nicknames (for example, "Kelly" maps to hemostat, and "Mayo" maps to scissors).
2. **Overhead Perception:** A webcam mounted above the table looks straight down. MediaPipe tracks the clinician's hand at 10 Hz and checks whether the palm is open. Perceptron's vision API detects instrument positions and monitors whether slots are occupied.
3. **Motion and Manipulation:** An open-source SO-101 6-axis arm runs fine-tuned Isaac 0.5 policies. The robot picks items, carries them at safe heights, and delivers them handle-first.
4. **Safety Controller and Ledger:** A central controller enforces state transitions. It checks grasps, diverts sharp blades to a dedicated safe spot, and logs all events to MongoDB Atlas.

## Data Collection: Teaching the Arm with Demonstrations

Robots in surgical settings cannot rely on hardcoded joint trajectories. Instruments shift in their slots. Hands move to different positions. Tools rest at varying angles.

We trained Scrub by recording demonstrations:
- We recorded teleoperation demonstrations using LeRobot: 20 picks and 10 returns for each operating room instrument, and 15 picks and 10 returns for each bench tool.
- We covered 6 distinct tools across two settings: operating room (scalpel, hemostat, Mayo scissors) and robotics bench (needle-nose pliers, wire cutters, hex key).
- In total, we collected [measured] clean episodes.
- Each demonstration captured dual camera streams (overhead table view and wrist-mounted camera view) along with joint positions at 30 frames per second.

The Isaac 0.5 model fine-tuned on this data learns generalized grasping policies directly from vision and proprioception. Adding the bench setting required zero new control code, just new demonstrations. It took [measured] minutes of demonstration time.

## Conquering Glare: The Lighting Experiments

The biggest surprise during development was lighting.

Operating room lamps are intense. Stainless steel tools reflect direct glare. Under standard camera auto-exposure settings, the camera sensor constantly adjusts its gain. A bright reflection causes the background to turn black, causing detection models to lose track of instruments.

To fix this, we took three steps:

1. **Hardware Control Lock:** At camera startup, our software locks exposure and white balance to fixed values. Even when a 1200-lux lamp turns directly onto the tray, the camera gain remains steady.
2. **Automated Scene Classification:** Our vision service monitors average frame brightness in real time. It automatically classifies the lighting as bright, normal, or dim, and estimates the scene lux. It tags every logged trial automatically.
3. **Rigorous Three-Condition Testing:** We evaluated perception and grasping across three distinct lighting environments:
   - Normal room lighting: approximately 450 lux
   - Direct surgical lamp glare: approximately 1200 lux
   - Dim ambient lighting: approximately 80 lux

Our measured results across lighting conditions:
- Normal light pick success rate: [measured]%
- Bright glare pick success rate: [measured]%
- Dim light pick success rate: [measured]%
- Median request-to-hand duration: [measured] seconds

## Safety Rules and Lessons Learned

Building a robot that interacts with human hands required strict safety rules:

1. **Never pass a sharp hand to hand.** In a real operating room, nurses do not hand scalpels directly into a surgeon's fingers. They place them in a neutral safe spot. Scrub enforces this rule in software. When a user requests a scalpel, Scrub picks the knife, carries it carefully, sets it down at a fixed safe spot, and announces "scalpel down."
2. **Dual-check grasps.** Gripper current sensing alone can give false readings if a tool catches at an odd angle. We built dual verification. First, the gripper position sensor checks whether the jaws closed completely on empty air. Second, the overhead camera verifies that the tray slot is actually empty. If either check fails, the controller retries once before reporting the failure. The grasp verification accuracy is [measured]%.
3. **Safety stop must be instant and latched.** A safety stop cannot wait for an API round trip. When someone says "stop", hits the spacebar, or taps the emergency button on the dashboard, the controller freezes the arm joints in [measured] ms. Once stopped, the arm remains locked until an operator explicitly issues a reset command.
4. **Dynamic hand tracking and standoff.** The overhead camera watches the user's hand at 10 Hz. The robot continuously aims for a standoff point 8 cm short of the palm. If the user pulls their hand back, or if another person reaches into the workspace, the robot halts motion instantly.
5. **Release on pull.** When delivering a tool, the robot waits in place. When the user takes the instrument, the gripper detects the mechanical load change and opens immediately. The user can also say "got it" to release.

## What Is Next

We built Scrub on an arm that costs under $500 to show that useful physical AI is possible on accessible hardware today. 

Our first target is surgery centers and operating rooms, starting with training labs. Surgical trays use standardized instruments and predictable layouts. We plan to offer Scrub as a monthly subscription per operating room, priced below the cost of covering unfilled scrub tech shifts. Scrub is a training and research prototype with no clinical claims.

All code, data collection tooling, and test suites are open source in our repository.
