# Medical Go-To-Market: How the SO-101 Surgical Assistant Becomes a Company

Date: 2026-10-17. Not legal or regulatory advice. Tags: [V] = verified in a source I opened or got in search results; [U] = unverified, from general knowledge, check before relying on it.

## 0. Bottom line (the honest version)

- The founder's worry is half right. The thing we demoed (a $250 hobby arm handing instruments in the OR) is not clearable or sellable into an OR for years. 5 mm repeatability, 0.3 kg payload, no sterile barrier, and a plastic-prop demo is the wrong hardware for a patient-adjacent device.
- The company is not "the robot." The company is the perception, verification and skill-scoring layer (instrument identification, counting, handoff verification, gesture/skill labeling), sold first to buyers where FDA does not apply or applies lightly. The arm is the demo and a training-lab accessory, not the regulated product.
- Best beachhead ranking by speed to revenue with low regulation: (1) sterile processing tray verification (but Censis already ships a competitor), (2) surgical skills/sim labs, (3) device-company and veterinary/dental training. OR-facing products (counting, handoff) are a 3 to 5 year, multi-million dollar program.
- Funding is real but slow: SBIR just came back from a 195-day lapse. Plan to fund the first 12 months with hackathon prizes, university gap money, and small pilots, not SBIR.

## 1. Regulatory reality

### 1.1 Framework basics
- Devices are Class I (mostly exempt), II (usually 510(k)), III (PMA). If no predicate exists and risk is low or moderate, De Novo creates a new Class II type.
- 2026 FDA fees: 510(k) $26,067 standard / $6,517 small business; De Novo $173,782 / $43,446; annual establishment registration $11,423 with no small-business discount [V] [FDA FY2026 user fees (RAPS)](https://www.raps.org/resource/fda-unveils-fy-2026-user-fee-rates.html), [MDUFA fees (FDA)](https://www.fda.gov/medical-device-user-fee-amendments-mdufa). Small-business status needs a qualification filing with FDA first [U on exact procedure].
- Quality system: FDA's QMSR, which folds ISO 13485:2016 into 21 CFR 820, became effective Feb 2, 2026 [V] [Covington on QMSR](https://www.cov.com/news-and-insights/insights/2024/02/fda-finalizes-rule-incorporating-iso-13485-into-new-quality-management-system-regulation-qmsr), [Emergo on QMSR](https://emergobyul.com/news/us-fda-incorporates-iso-13485-within-its-qmsr-final-rule). So design controls, risk management (ISO 14971), and a QMS are needed before you sell a regulated device. ISO 13485 certification itself is not legally required by FDA, but the equivalent system is.
- 510(k) timing and cost: median about 151 days receipt to clearance in recent data, about 1 in 4 cleared within 90 days, clock stops during FDA hold [V] [510(k) review time](https://www.510kdatabase.net/510k-review-time/). All-in cost commonly cited $50k to $250k+ (fees, testing $20k to $150k+, consultants $15k to $50k); about 10% of 510(k)s need human clinical data costing $250k to $2.5M [V, consultant-blog quality] [How much does a 510(k) cost](https://meddeviceguide.com/blog/how-much-does-510k-cost-guide). IEC 60601-1 lab testing quoted at roughly $18k to $39k for a simple device [V, blog quality]; a robot with motors will cost more [U].
- Software: IEC 62304 lifecycle (safety classes A/B/C), cybersecurity documentation, and for learned models a Predetermined Change Control Plan if you want to update models post-clearance [U on current final guidance status; check FDA AI-enabled device software functions pages].
- Jan 6, 2026 FDA relaxed clinical decision support (CDS) and general wellness guidance, broadening what software can ship without premarket review when a clinician can independently review the basis for a recommendation [V] [Orrick summary](https://orrick.com/en/Insights/2026/01/FDA-Eases-Oversight-for-AI-Enabled-Clinical-Decision-Support-Software-and-Wearables), [Polsinelli](https://www.polsinelli.com/publications/new-year-digital-health-fda-updates-guidance-documents). Helpful for scoring/analytics software, but it does not reach software that acquires or analyzes images from a device in the sterile field [U, my reading; confirm with counsel].

### 1.2 Our three product shapes

(a) Instrument-handoff robot in the OR
- Likely Class II, 510(k) if a predicate exists, otherwise De Novo. I found no cleared "robotic scrub nurse" in search [V that none surfaced]; Gestonurse and Penelope remained research prototypes ([Gestonurse](https://www.iceira.ntu.edu.tw/en/research-direction/309-gestonurse), [Penelope](https://reliasmedia.com/articles/3871-will-robot-penelope-replace-a-scrub-nurse)). No predicate means De Novo is the realistic path: about $43k fee at small-business rate plus the real cost, a human-factors validation, bench and probably animal/cadaver or simulated-use data. Plan $2M to $6M and 3 to 5 years [U, my estimate].
- Hard parts: sterile field (drape over a robot arm, or autoclavable end effector), electrical safety (IEC 60601-1, EMC 60601-1-2), collision/force limits and stop behavior, human-factors per IEC 62366, and a clinical argument that handing a sharp is safe at 5 mm repeatability. The SO-101 as built cannot pass this. A medical version means different actuators and a different arm.
- Precedent for the pattern of "robot touches sterile instruments": Restore Robotics got 510(k) for remanufactured da Vinci instruments, product code QSM for some items [V] [Restore Robotics](https://www.medicaldevice-developments.com/news/restore-robotics-receives-fda-clearance-for-surgical-instrument-remanufacturing/). That is a different thing (instruments, not a scrub robot) so treat it as context only.

(b) Sponge/instrument counting vision system
- This is the best-precedented class. Product code LWH, "Counter, Sponge, Surgical," Class I per the FDA record I saw, cleared by 510(k):
  - ORLocate system, K100551, decision 08/12/2010, LWH, RFID counting of sponges and manual instruments plus detection of retained items [V] [FDA K100551](https://www.accessdata.fda.gov/cdrh_docs/pdf10/K100551.pdf), [SecureIDNews](https://www.secureidnews.com/news-item/no-sponge-gets-left-behind-orlocate-earns-fda-approval/).
  - SurgiCount Safety-Sponge System, K060076, cleared 2006, LWH [V] [K060076](https://fda.innolitics.com/device/K060076). ClearCount K071355 (2007, LWH) is a second one [V] [K071355](https://fda.innolitics.com/device/K071355).
  - Gauss Surgical Triton (camera/AI blood-loss measurement on sponges and canisters), K160338, Aug 2016, product code reported as PBZ [V per search result, I could not open the FDA page, verify the code]. It is the closest precedent for "tablet camera plus ML on surgical sponges," and it went through 510(k) with a clinical component [U on specifics].
- Note: all of these are RFID or barcode on tagged items, or blood-volume estimation. A pure vision sponge-count that claims to reduce retained items is a new intended use, so expect either a 510(k) citing LWH with performance testing, or a Class II De Novo if FDA says the AI claim differs [U]. Do not claim "prevents retained items" before you have outcomes data; claim "adjunct count verification" [V that this is the framing in our research file, risky claim #1].
- Scope trick: a counting aid used on the back table (non-patient-contact, advisory only, human still does the official count) may carry less review burden than a retained-item detector in the wound. FDA decides by intended use, so get a Pre-Submission (Q-Sub) before building [U].
- Realistic: 510(k) at 12 to 24 months and $300k to $1.5M if no clinical study is required; much more if one is.

(c) Training-only device
- A simulator or skills-scoring tool used on phantoms and props, never on patients, is generally not regulated as a medical device for the sim itself, and most surgical simulators (LapSim, Lap Mentor) are sold without 510(k) [U; I did not find a primary FDA statement. Verify with a regulatory consultant]. Claims matter: "validated measure of competence for credentialing" starts to look like assessment of clinicians, which FDA does not regulate as a device, but accreditors and program directors will want validity evidence (OSATS/GEARS correlation) [U].
- Do not put patient-facing claims in the marketing (diagnosing, treating, preventing). Keep "for education and research use" labeling, which is exactly what our UI already says per SURGEON_BRIEF.md.
- Still do: basic electrical safety (UL/IEC 61010 or 62368 style), CE/UL not required to sell in the US but universities' procurement often wants it [U].

### 1.3 Sterility and draping
- Anything entering the sterile field must be sterile or draped. Draping a robot arm is solved (da Vinci drapes) but costs engineering: drape-compatible joints, sensor visibility through a drape, and sterile adapters. Autoclaving ABS/PLA parts and servos is not possible; STS3215-class servos on the SO-101 are not rated for it [U]. This is why training and SPD beachheads come first.
- Tray-side devices in SPD sit in a clean (assembly) area, are cleaned with disinfectant wipes, and are not sterile; SPD standard is ANSI/AAMI ST79 for steam sterilization and documentation [V] [AAMI ST79 listing](https://webstore.ansi.org/standards/aami/ansiaamist792017).

## 2. Beachhead markets, ranked by speed to revenue

Ranking is mine. Cycle times and budgets are [U] unless cited.

| Rank | Market | Buyer | Pain | Budget | Sales cycle | FDA burden | Maps to our demo |
|---|---|---|---|---|---|---|---|
| 1 | Surgical skills / sim labs (med schools, residencies, ACS-accredited institutes) | Sim center director, program director, department chair | Subjective, slow skill grading (OSATS/GEARS); faculty time; need objective metrics for milestones | $10k to $150k per system; often grant/donor funded | 3 to 9 months; faster for a pilot under $10k | None for training-only labeling | Direct: box trainer, foam pad, video skill scoring, gesture labels |
| 2 | Sterile processing departments (SPD) | SPD manager, perioperative director, VP of supply chain | Missing/incorrect instruments in trays cause OR delays; heavy turnover, 120-day fills for surgical-technologist roles | Labor and OR-delay budgets; hundreds of trays per day; license per workstation | 6 to 18 months (IT, infection prevention, value analysis committee) | Probably none to low if it only verifies trays and does not make sterility claims; Censis ships Final Check with no FDA status mentioned [V] | Instrument detection against a reference photo, count sheet OCR, tray-tag OCR |
| 3 | Device-company training centers | Sales training / clinical education head at ortho, robotics, laparoscopic OEMs | Reps and surgeons need hands-on practice; need engagement metrics | Existing training budgets, six figures | 6 to 12 months, long procurement | None | Skill scoring, instrument recognition, handoff drill |
| 4 | Veterinary (schools, clinics, spay/neuter high-volume) | Vet school sim lab, large clinic group | Instrument counts, no scrub tech, retained sponges happen in vet too | Smaller budgets; AVMA/USDA not FDA CVM for non-drug devices (vet devices are regulated lightly) [U] | 3 to 9 months | Low [U] | Counting and handoff, same CV |
| 5 | Dental schools / DSOs | Dental school sim director, dental service orgs | Dental simulator market about $381M in 2023, 8.6% CAGR [V] [GMI dental simulator](https://gminsights.com/industry-analysis/dental-simulator-market/market-size); manikin-based dominates; schools about $170M | Equipment budgets | 6 to 12 months | None for training | Skill scoring; arm is less relevant |
| 6 | Research labs | PIs, robotics labs | Need low-cost surgical-task data, benchmark environments | Grant-funded, $2k to $20k | 1 to 3 months | None | SO-101 as a data collection rig and dataset |
| 7 | Ambulatory surgery centers (ASCs) | ASC administrators, DON | Small staff, shortages, retained-item risk | Tight, ROI-driven | 6 to 12+ months | Counting = regulated; scoring or SPD-like use = not | Counting would be the product, so it needs FDA |

How each one maps and where it breaks:
- Sim labs: fastest. Sells scoring and analytics, not the arm. Competitors: Surgical Science (LapSim, subscription "LapSim essence" [V] [Surgical Science brochure](https://surgicalscience.com/lap-brochure-2023-6-en-web)), Simbionix LAP Mentor (3D Systems), Intuitive's own simulators. Our differentiator is physical box trainers plus low-cost vision instead of $50k+ VR [pricing U]. ACS maintains the accredited education institute network, about 76 centres in an older count (67 comprehensive, 9 focused, 13 outside the US) [V, dated] [Augusta ACS-AEI list](https://web1.augusta.edu/mcg/surgery/vesl/links.php). This is a small, reachable list of buyers.
- SPD: biggest pain and clearest ROI, but a funded competitor exists. Censis Final Check uses computer vision to verify tray contents, with unnamed early adopters and no stated FDA status [V] [MarketScale on Censis](https://www.marketscale.com/industries/healthcare/ai-in-sterile-processing-whats-next-censis-assembly-copilot-final-check). Others in the space (Tiliter, PRF licensed inspection tech [V that these exist]) [Tiliter](https://tiliter.com/use-case/surgical-verification-for-hospitals-and-medical-device-logistics), [PRF](https://licensing.prf.org/product/automated-ai-inspection-for-surgical-instruments-in-sterile-processing). Difficulty: real instruments are shiny, dense, and visually near-identical (many forceps). Our hackathon detection on plastic props proves almost nothing about this. You need real-tray data from a partner SPD. Also, SPD vendors sell to the same hospital that uses their instrument-management system (Censis, Steris, Getinge); integration with those systems is the real moat or the real wall.
- Device-company training: smart wedge because they already pay to train. Hard because they want their own instruments and their own branding.
- Vet and dental: easy entry, small checks. Useful for first revenue and testimonials, not a venture-size market alone.
- ASC: avoid until you have a cleared counting product.

## 3. Business models and pricing anchors

- Hardware plus SaaS. Sell a vision station (camera rig, compute, tray) at about $3k to $10k [U] with a per-workstation annual subscription ($3k to $12k per year [U]). Matches how sim labs and SPD software are bought.
- Robots-as-a-service. Realistic only once the hardware is stable and cleared. In sim labs, a monthly lease of $300 to $1,000 per station [U] removes capital approval.
- Per-procedure or per-tray. Per-tray pricing in SPD ($0.10 to $0.50 per tray verified [U, my guess]) can be justified against labor. SPD technician median pay was $44,940 a year, $21.61/hour (BLS, May 2023) [V] [search summary of BLS](https://recruiting.paylocity.com/Recruiting/Jobs/Details/4230461); job postings $18 to $32.50/hour [V]. Fully loaded cost is higher. I could not find a reliable per-tray assembly time or cost; do not quote one until you time it in a partner SPD [V that not found].
- Data/analytics licensing. Skill scores, motion, gesture labels. Valuable but needs consented, de-identified data and IRB or educational-use agreements. Gesture datasets like JIGSAWS exist for da Vinci, and annotated surgical video is described as scarce [V, from SURGEON_RESEARCH.md]. Gap = box trainer and open-surgery tasks; own data is a real asset.
- Training subscription. Per-resident or per-seat ($100 to $500 per learner per year [U]) with curriculum, scoring, and dashboards for program directors, who must document milestones to the ACGME [U on ACGME link].
- Pricing anchors on the demand side: a retained surgical item costs roughly $525k to $600k per incident to a facility, with a national estimate of $2.4B per year, and 1 in 5,500 to 18,760 surgeries [V, from SURGEON_RESEARCH.md; [Becker's](https://www.beckershospitalreview.com/quality/the-high-cost-of-inaction-retained-surgical-sponges-are-draining-hospital-finances-and-harming-reputations/)]. Treat these as marketing anchors, not as an ROI you can promise; hospitals have heard it for 20 years and many already bought RFID.
- Pricing anchors on the supply side: LapSim and Lap Mentor are high five to low six figures [U; I could not find public list prices, searches returned none]. Get quotes by emailing sim centers as part of customer discovery.

## 4. Non-dilutive funding

- NIH SBIR/STTR. Both lapsed Sep 30, 2025 and were reauthorized Apr 13, 2026 through Sep 30, 2031 (a 195-day gap) [V, one aggregator] [OpenGrants on 2026 changes](https://opengrants.io/sbir-grants-2026-what-changed-whats-next/). Standard ceilings reported: Phase I $323,090, Phase II $2,153,927, with waiver topics up to $700k/$3M and a new Strategic Breakthrough Phase II up to $30M with matching [V, same source; confirm on grants.nih.gov]. Fit institutes: NIBIB, NHLBI, NIGMS; the call needs a research question, not a product pitch. You need a company registered (SAM.gov, SBIR.gov) and majority US-owned [U]. Timeline from submission to money: 6 to 9 months [U].
- NSF SBIR/STTR restarted May 31, 2026 with a $250M FY26 allocation, Project Pitch reopened Jun 2, first full proposal deadline Jul 27, 2026; Phase I up to $305k, Phase II $1.25M; next windows Nov 4 and Mar 4, 2027 [V, aggregator] [GrantedAI on NSF restart](https://grantedai.com/news/nsf-sbir-sttr-250m-2026-05-31), [OpenGrants NSF guide](https://opengrants.io/nsf-sbir-grants/). NSF wants technical risk and a commercial thesis; a perception-in-the-loop manipulation story fits better than "medical device." Project Pitch is the cheap first step (about a page).
- ARPA-H. The AIR (Autonomous Interventions and Robotics) program funds autonomous surgical robotics up to $175.3M over 5 years in total; e.g. a Vanderbilt-led team up to $12M [V] [Fierce Biotech on AIR](https://www.fiercebiotech.com/medtech/arpa-h-launches-program-fund-autonomous-stroke-treating-robots), [Vanderbilt](https://engineering.vanderbilt.edu/2024/09/24/quest-to-develop-fully-autonomous-surgical-robot-attracts-award-up-to-12-million-from-arpa-h/). Teams are university plus clinical heavy hitters. Realistic role for us: subcontractor or data/test-bed partner, not prime.
- DoD. CDMRP has funded semi-autonomous robotic surgery and telesurgery for combat casualty care [V] [citedrive on tele-robotic surgery for combat casualty care](https://www.citedrive.com/en/discovery/tele-robotic-surgery-for-combat-casualty-care/). Specific programs: DoD SBIR/STTR (Army, DHA) and CDMRP's Military Operational Medicine and Joint Warfighter programs [U on current topics]. The pitch angle is low-resource, austere, few-staff surgery; cheap hardware is a feature there. Each program has long cycles (6 to 12 months) and wants a PI with military ties.
- Washington State and Seattle.
  - UW CoMotion Innovation Gap Fund: historically about $50k per team up to $75k, over $1M a year pool, $18.9M across 399 awards [V] [CoMotion gap fund](https://comotion.uw.edu/funding-and-competitions/programs/comotion-innovation-gap-fund). Requires UW IP or affiliation. If anyone on the team is a UW student or researcher this is the first money to chase.
  - Life Science Washington Institute: runs SBIR/STTR assistance and received state Commerce funding ($100k grants for small-business support; a prior 20 startups got $25k each) [V] [WA Commerce announcement](https://www.commerce.wa.gov/commerce-awards-1-million-to-support-small-businesses-in-life-sciences-and-health-it/), [Science in Seattle](https://scienceinseattle.com/2023/10/12/washington-startups-receive-25k-grants-aimed-at-boosting-states-life-sciences-sector/).
  - "W Fund": I could not find it; unverified, do not cite until you confirm it exists. The Washington Research Foundation (funds CoMotion) is real [V].
- Medtech accelerators.
  - MedTech Innovator: no fees, no equity, competes for up to $500k in prizes; the 2026 cycle closed Dec 2025 and the site now shows a 2027 waitlist [V, aggregator] [How to apply (Causo)](https://hub.causo.ai/guides/how-to-apply-to-medtech-innovator-2026). Usually favors companies with more than a demo, so apply once you have a pilot.
  - TMCx (Texas Medical Center), Cedars-Sinai Accelerator, Mayo Clinic Platform_Accelerate, Y Combinator: I did not research current terms; [U]. YC takes equity (standard deal) and has funded health-AI and robotics companies; the others vary and several are equity-based.
- Realistic expectations: SBIR Phase I is the first serious non-dilutive money and typically needs 6 to 12 months of lead time, a team with a credible PI, and preliminary data. Do not budget it before month 9.

## 5. Staged path

### Hackathon (now to demo day)
- Run the demo on props, with "training/research prototype, not for clinical use" visible on every screen (already in SURGEON_BRIEF.md).
- Avoid the five risky claims in SURGEON_RESEARCH.md, especially "eliminates retained items" and "FDA path is straightforward."
- Capture: a 60-second video, performance numbers on your own props (detection accuracy per instrument, handoff success rate over N trials, with the 5 mm caveat), and the arm's honest limits.
- Pitch as the perception and verification layer plus training platform, with a stated regulatory roadmap: training first (unregulated), counting aid later (510(k) via LWH-type precedent), robotic handoff last.

### 3 months
- 20 customer-discovery calls: 8 sim lab directors (ACS AEIs, UW/Harborview/Seattle Children's-type centers), 6 SPD managers, 3 device-training heads, 3 vets/dental. Ask for budgets and for a letter of intent (LOI) or paid pilot.
- Form an LLC or C-corp (Delaware C-corp if you want venture or SBIR/YC). Register on SAM.gov (takes weeks) and SBIR.gov if aiming at SBIR.
- Build the skill-scoring MVP on a box trainer and collect data under a signed data-use agreement at one lab (a resident volunteer study under educational use; check with the institution whether IRB review or exemption is needed [U]).
- Apply: CoMotion Innovation Gap Fund (if UW-affiliated), NSF Project Pitch, Life Science Washington events. Book a free SBA/SBDC or LSW regulatory consult.
- Milestone for an investor: 2 to 3 pilot commitments, ideally one paid, at least one clinical (surgeon or SPD) advisor named.

### 12 months
- 3 to 5 paying sim/training customers ($20k to $100k ARR total [U target]), 1 SPD pilot with real trays with measured error and time, and a dataset from real tray or box-trainer sessions.
- IRB-approved or exempt validation study at a partner institution comparing automated scores with OSATS/GEARS ratings from expert raters; aim for a submitted abstract (SAGES, ASE, Surgical Education conferences) [U on venue timing].
- Start an ISO 13485-style QMS lite and IEC 62304 documentation habit in the repo (requirements, risk file, traceability) even before it is required; costs nearly nothing now and saves a year later.
- FDA Pre-Submission (Q-Sub) for the counting-aid concept; cost is staff time and a consultant, no user fee for a Q-Sub [U]. Get written feedback on intended use, predicate (LWH, K100551), and whether clinical data is needed.
- Funding: pre-seed $500k to $1.5M [U range] plus one of SBIR/NSF Phase I (NSF windows Nov 2026 and Mar 2027 [V]); MedTech Innovator 2027 application.
- Milestone: Series-seed credible story = revenue plus a clinical validation plus a regulatory plan with FDA feedback in hand.

### 36 months
- Branch A (counting aid): 510(k) submission about months 18 to 30, clearance by about month 36 if no clinical trial; hospital pilots in the OR back-table role, a GPO or EHR/IMS integration partnership (Epic/Censis/Steris).
- Branch B (SPD tray verification, if unregulated): 20+ hospital sites, integrated with an instrument-management system, strong ARR; this is likely the actual revenue engine.
- Branch C (robot): only with a purpose-built medical-grade arm design, a sterile-drape concept, an engineering partner or acquirer, and Series A capital ($8M to $20M+ [U]). A De Novo for a handoff robot, plus a clinical simulated-use study, is plausible by year 5 to 6 [U].
- Investor milestones through this stage: clinical advisory board, LOIs from 3+ health systems, IRB-backed study, FDA Q-Sub feedback, ISO 13485 certified QMS, IP (provisional patents on the handoff verification and counting methods; prior art exists from Gestonurse and Penelope so claim narrowly) [U].

## 6. What is genuinely hard (read this before pitching)

1. The arm. The SO-101 can't be the clinical product. Hobby servos and 3D-printed links will not survive a safety case. Say so before an investor finds out.
2. Incumbents. RFID sponge counting (ORLocate, SurgiCount, ClearCount) has been cleared for 15+ years and hospitals who care already own it; Gauss/Triton and Censis have funding and customers. We need an angle (cheaper, no tags, instruments not just sponges, SPD focus), not "AI for surgery."
3. Vision on real instruments. Metal glare, 100+ look-alike instruments, wet gauze, blood. Plastic-prop accuracy won't transfer; plan a data-collection effort in a real SPD or sim lab.
4. Sales cycles. Hospital value-analysis committees, IT security reviews, and infection-prevention approvals are slow even for unregulated products. Sim labs and vets are faster but smaller.
5. Liability. Even "advisory" counting tools may attract product-liability risk if a count error is blamed. Insurance and clear labeling matter. Talk to a med-device attorney before the first hospital pilot.
6. Funding gaps. SBIR is back but only since April 2026 and requires patience; accelerators prefer traction. Expect the first year on prize money, gap funds, small pilots, and maybe a pre-seed.
7. Claims. The first FDA problem for a young company is marketing language, not engineering. Keep "training and research use" language until a clearance exists.

## 7. Sources not already linked above
- [Gauss Surgical Triton, K160338 (index)](https://beudamed.com/fda510ks/K160338) (page returned 403 to me; code PBZ is from a search summary, verify)
- [Becker's: surgical technologist shortage](https://www.beckershospitalreview.com/academic-medical-center/academic-medical-centers-workforce/the-surgical-technologist-shortage-explained/)
- [FDA 510(k) classification database, LWH](https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm?ID=K100551)

## 8. Open items to verify (priority order)
1. FDA product code and class for Triton (PBZ?) and exact classification regulation for LWH (the record I saw said Class 1; confirm in the FDA Product Classification database).
2. Whether any robotic instrument-handling device has been cleared; run a search in the FDA 510(k) and De Novo databases for "scrub," "instrument," and "robotic" with a regulatory consultant.
3. Whether a vision-only counting aid is in or out of LWH; request a Q-Sub.
4. Current list prices for LapSim/Lap Mentor (ask sim centers) and SPD per-tray labor time (time it in a partner SPD).
5. W Fund, TMCx, Cedars-Sinai, Mayo, and YC current program terms.
6. NIH SBIR current ceilings and open topics on grants.nih.gov, DoD SBIR topic lists, CDMRP FY26 program announcements.
7. Training-device exemption: confirm with counsel that a skills-scoring product with "education use only" labeling needs no FDA submission.
