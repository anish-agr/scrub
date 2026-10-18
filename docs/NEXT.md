# DubHacks NEXT Business Case: Scrub

Team Scrub, DubHacks 2026.

Scrub is a training and research prototype. We make no clinical claims. The numbers below are planning estimates, not results.

## Executive Summary

Scrub is an autonomous scrub assistant for the operating room. It picks instruments from a tray on voice command, delivers them handle first to an open hand, returns them to their slots, and maintains an exact count. Scalpels go to a fixed safe spot instead of hand to hand.

Operating rooms face a staffing crisis. We would sell Scrub as a monthly software and hardware subscription per operating room. The plan is to price it below the cost of covering one unfilled scrub tech shift per month.

## 1. The Beachhead Market: Surgery Centers and Operating Rooms

We start with surgery centers and operating rooms, and with surgical training and simulation labs before any live case.

### Why Surgical First

1. **The job is well defined.** A scrub tech passes instruments, takes them back and keeps the count. The tray, the instruments and the sharps rules are standard, so the task is small enough to automate and to measure.
2. **Documented staffing shortage.** Surgical technologist positions take an average of 120 days to fill. First-year staff turnover is 42.9%.
3. **Immediate ROI for the buyer.** When a room has no scrub tech, the surgeon must stop, look away from the patient, and pick their own tools. An unfilled shift costs in delayed cases, slower throughput and temporary staffing agencies ($35 to $50 per hour).
4. **A safe path to market.** Hospital operating rooms need Class II medical device clearance (De Novo or 510(k)). That pathway costs between $2,000,000 and $6,000,000 and takes 3 to 5 years. We would start where no clearance is needed: training labs and research use, with the arm never near a patient. Clinical use comes later and only with clearance.

## 2. Product and Workflow

Scrub does not replace scrub techs. It assists them.

Scrub automates instrument handling:
- **Voice-directed handoff:** The surgeon says "hemostat" or "Mayo scissors." Scrub picks the tool and brings it to the surgeon's open hand within seconds.
- **Sharps safe spot:** A scalpel is placed in a fixed safe spot. It is never passed hand to hand.
- **Pull release:** Scrub senses when the clinician takes the tool and opens its gripper automatically.
- **Hands-free returns:** When a tool is placed in the designated return spot, Scrub returns it to its tray slot.
- **Continuous instrument count:** Scrub tracks every tool. Clinicians say "count" to confirm no tool is missing before the case ends.

This frees a scrub tech to focus on the sterile field, the count and the next step of the case.

## 3. Business Model and Pricing

### Pricing Structure

- **Subscription:** $600 to $900 per operating room per month.
- **Hardware setup:** $1,500 initial setup fee per room, including the arm cell, overhead camera, and mounting bracket.
- **Software platform:** Includes continuous model updates, tray configuration tools, procedural analytics, and hardware replacement support.

### Unit Economics and Buyer ROI

These are planning estimates, not measured results.

| Metric | Cost Without Scrub | Cost With Scrub |
| --- | --- | --- |
| Unfilled tech shift (1 per month) | $200 to $400 / month | $0 (room stays productive) |
| Temp agency coverage (2 days) | $560 to $800 / month | $0 |
| Monthly Scrub subscription | $0 | $750 / room / month |
| Net monthly financial impact | -$560 to -$800 | +$10 to +$50 net gain, plus extra case capacity |

A center that avoids just two unfilled shifts in a month pays for the entire monthly cost of Scrub.

### Target Customer Segments

1. **Surgery centers:** Ambulatory surgery centers run many operating rooms with standard trays and repeat procedures. Standard tray cards allow rapid roll-outs.
2. **Hospital operating room groups:** Systems that struggle with scrub tech retention and want a count that is logged.
3. **Surgical training and simulation centers:** Schools and training labs use standard trays and value objective instrument tracking. This is the first stop, before any live case.

## 4. What We Changed and Proved This Weekend

We used the DubHacks weekend to de-risk key technical and operational assumptions.

1. **A second setting without new code:** One perception and control pipeline runs the operating room tray (scalpel, hemostat, Mayo scissors) and a robotics assembly bench tray (needle-nose pliers, wire cutters, hex key). Adding the bench setting needed zero new control code, only demonstrations and slot definitions. A dental tray file exists in the repo but is not demoed.
2. **Dual-check grasp reliability:** Simple gripper position checks fail when a tool is misaligned. We built a dual-check verification system: gripper position sensing combined with overhead slot verification through computer vision. Grasp check accuracy is [measured].
3. **Operating glare and lighting robustness:** Stainless steel tools reflect harsh clinical lighting. We locked camera exposure and white balance, and evaluated perception under three lighting conditions: normal room light (~450 lux), bright lamp glare (~1200 lux), and dim light (~80 lux).
4. **Human-safe hand tracking:** We built real-time overhead palm tracking at 10 Hz. The robot dynamically updates its trajectory to stop 8 cm short of the clinician's hand. If the clinician withdraws their hand or another person's arm blocks the path, the controller freezes the arm in place. Freeze time is [measured] ms.
5. **Hands-free sharps safety protocol:** Scalpels are never passed hand to hand. They are delivered exclusively to a dedicated safe spot.

## 5. Roadmap

- **Month 1 to 3 (Customer Discovery and Pilot):** Conduct 20 customer discovery interviews with surgery center managers and operating room leads in the Seattle area. Place two prototype arms in non-clinical surgical training labs.
- **Month 4 to 6 (Training Lab Beta):** Deploy Scrub in 5 training and simulation rooms. Validate request-to-hand latency under 3 seconds.
- **Month 7 to 12 (Next Step):** Standardize arm mounting kits for common operating room tables. Begin the regulatory path before any use near a patient.
