# DubHacks NEXT Business Case: Scrub

Team Scrub, DubHacks 2026.

## Executive Summary

Scrub is an autonomous scrub assistant for dental practices. It picks instruments from a tray on voice command, delivers them handle first to an open hand, returns them to their slots, and maintains an exact count. 

Clinics face an acute staffing crisis. We sell Scrub as a monthly software and hardware subscription per dental chair. The system costs less than covering one unfilled assistant shift per month.

## 1. The Beachhead Market: Dental Practices

We start with dental offices rather than hospital operating rooms.

### Why Dental First

1. **Lower regulatory barriers.** Hospital operating rooms require Class II medical device clearance (De Novo or 510(k)). That pathway costs between $2,000,000 and $6,000,000 and takes 3 to 5 years. Dental offices perform clean and semi-critical procedures. They use standard wipe-down barrier sleeves and autoclaved metal trays. They do not require custom sterile full-arm drapes or multi-year clinical trials.
2. **Acute, documented staffing shortage.** According to the American Dental Association (ADA) Health Policy Institute, 69% of dental practices recruiting dental assistants report that finding qualified candidates is extremely or very challenging.
3. **Turnover and hiring delays.** Healthcare technologist positions take an average of 120 days to fill. First-year staff turnover is 42.9%. Dental practices frequently lose chairside assistants to burn-out and wage competition.
4. **Immediate ROI for the buyer.** When a chair has no assistant, a dentist must stop, look away from the patient, and pick their own tools. An unfilled dental assistant shift costs a clinic between $200 and $400 per day in lost production, slower patient throughput, and expensive temporary staffing agencies ($35 to $50 per hour).

## 2. Product and Workflow

Scrub does not replace dental assistants. It assists them.

Chairside assistants spend up to 40% of procedure time picking instruments, passing tools, organizing trays, and tracking counts. Scrub automates instrument handling:
- **Voice-directed handoff:** The dentist says "mouth mirror" or "explorer." Scrub picks the tool and brings it to the dentist's open hand within seconds.
- **Pull release:** Scrub senses when the clinician takes the tool and opens its gripper automatically.
- **Hands-free returns:** When a tool is placed in the designated return spot, Scrub returns it to its tray slot.
- **Continuous instrument count:** Scrub tracks every tool. Clinicians say "count" to confirm no tool is missing before dismissal.

This allows one dental assistant to supervise 2 to 3 chairs simultaneously, focusing on patient comfort, charting, suction, and sterilization.

## 3. Business Model and Pricing

### Pricing Structure

- **Subscription:** $600 to $900 per chair per month.
- **Hardware setup:** $1,500 initial setup fee per operatory, including the arm cell, overhead camera, and mounting bracket.
- **Software platform:** Includes continuous model updates, tray configuration tools, procedural analytics, and hardware replacement support.

### Unit Economics and Buyer ROI

| Metric | Cost Without Scrub | Cost With Scrub |
| --- | --- | --- |
| Unfilled assistant shift (1 per month) | $200 to $400 / month | $0 (chair remains productive) |
| Temp agency assistant coverage (2 days) | $560 to $800 / month | $0 |
| Monthly Scrub subscription | $0 | $750 / chair / month |
| Net monthly financial impact | -$560 to -$800 | +$10 to +$50 net gain, plus extra patient capacity |

A practice that avoids just two unfilled assistant shifts in a month pays for the entire monthly cost of Scrub.

### Target Customer Segments

1. **Dental Service Organizations (DSOs):** DSOs manage dozens to hundreds of practices with standardized operatories and centralized procurement. Standard procedure cards and identical trays allow rapid roll-outs.
2. **High-volume private practices:** Practices with 4 to 8 chairs that run multi-operatory schedules and struggle with assistant retention.
3. **Dental schools and simulation centers:** The global dental simulator market was $381,000,000 in 2023 with an 8.6% compound annual growth rate (Global Market Insights). Dental schools train students on standardized manikin benches and value objective instrumentation tracking.

## 4. What We Changed and Proved This Weekend

We used the DubHacks weekend to de-risk key technical and operational assumptions.

1. **Multi-setting portability without new code:** We demonstrated that one unified perception and control pipeline runs across three completely different settings: an operating room tray (scalpel, hemostat, Mayo scissors), a dental tray (mouth mirror, explorer, cotton pliers), and a robotics assembly bench (needle-nose pliers, wire cutters, hex key). Adding the dental setting required zero new control code, only demonstrations and slot definitions.
2. **Dual-check grasp reliability:** Simple gripper position checks fail when a tool is misaligned. We built a dual-check verification system: gripper position sensing combined with overhead slot verification through computer vision. Grasp check accuracy is reliable across all items.
3. **Operating glare and lighting robustness:** Stainless steel tools reflect harsh clinical lighting. We locked camera exposure and white balance, and evaluated perception under three verified lighting conditions: normal room light (~450 lux), bright clinical lamp glare (~1200 lux), and dim light (~80 lux). The system maintained robust detection and tracking across all three.
4. **Human-safe hand tracking:** We built real-time overhead palm tracking at 10 Hz. The robot dynamically updates its trajectory to stop 8 cm short of the clinician's hand. If the clinician withdraws their hand or another person's arm blocks the path, the controller freezes the arm in place within 50 ms.
5. **Hands-free sharps safety protocol:** We implemented an operating-room safety standard for sharps. Scalpels are never passed hand to hand. They are delivered exclusively to a dedicated safe spot.

## 5. Roadmap

- **Month 1 to 3 (Customer Discovery and Pilot):** Conduct 20 customer discovery interviews with local dental practice owners and DSO operations directors in the Seattle area. Place two prototype arms in non-clinical dental training operatories.
- **Month 4 to 6 (Operatory Beta):** Deploy Scrub on 5 clinical dental chairs under a supervised pilot agreement. Validate request-to-hand latency under 3 seconds in routine dental fillings and cleanings.
- **Month 7 to 12 (Commercial Launch):** Standardize dental arm mounting kits for common operatory dental delivery units. Scale to 50 active chairs across regional DSO partners.
