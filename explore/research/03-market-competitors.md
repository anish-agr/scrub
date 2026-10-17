# 03 - Market and Competitors (SO-101 Surgical Assistant)

Research date: 2026-10-17. Prototype scope: training / research tool, not clinical. Items tagged **[UNVERIFIED]** came from my background knowledge, a single weak source, or conflicting results and should be re-checked before going on a slide.

## 1. Competitor and comparable map

### 1a. OR assistant robots

| Company | Stage / funding | Product | Price | Gap vs. us |
|---|---|---|---|---|
| Moon Surgical | $31.3M Series A (Jun 2022); $55.4M round (May 2023); FDA clearance Jun 2024. No later round found [UNVERIFIED that none exists] | Maestro: AI co-manipulation arms that hold laparoscopic instruments/camera, use existing surgeon tools | Not public; sold to hospitals/ASCs as capital equipment, "far cheaper than da Vinci" | Capital sale, one task (holding), no counting, no training |
| Diligent Robotics | ~$50M total by 2022 ($30M Series B, Tiger Global); $25M more Sep 2023. No 2025 round found | Moxi: mobile manipulator fetching supplies on nursing floors, ~100 units, rental/usage model | Subscription, price not public | Floor logistics, not sterile field or OR |
| Andromeda Surgical | $15M Series A (YC, Standard Capital), $30M total (date not confirmed) | Beacon: autonomy for HoLEP (prostate laser) | Not public | One urology procedure |
| Penelope (Columbia, M. Treat) / "Robotic Surgical Systems" | Academic prototype tested at NY-Presbyterian; commercial company, funding and status not found [UNVERIFIED] | Cart + arm that unpacks instrument sets, voice-requested retrieval | n/a | Closest concept to ours; never commercialized, so the opening is real |
| Gestonurse (Purdue) | Academic | Gesture/voice robotic scrub nurse, 95% gesture accuracy | n/a | Research only |
| Asensus Surgical | Acquired by Karl Storz, ~$95M ($0.35/share), closed 2024 | Senhance (laparoscopic robot with eye-tracking camera) | Capital sale | Cautionary exit: stock fell 98% from 2019 |
| Virtual Incision | $46M Series C (Nov 2021) + $30M extension (Sep 2023) | MIRA: miniaturized in-body robot, FDA De Novo | Not public | Surgeon-side robot, not support role |
| Medical Microinstruments (MMI) | $110M Series C (Feb/Mar 2024, led by Fidelity) | Symani microsurgery robot | Not public | Microsurgery niche |
| Intuitive (da Vinci) | Public. 2025 revenue about $10.06B; installed base 11,106; 1,721 placements in 2025 | da Vinci 5 | $1.5M+ per system [from SURGEON_RESEARCH.md] | The thing "robotic surgery" means to buyers |

### 1b. OR analytics and video AI

| Company | Funding | Product | Notes |
|---|---|---|---|
| Theator | $15.5M Series A (Feb 2021, Insight); $24.5M listed Apr 2022 by CB Insights (round type unclear). No newer round found | Surgical video intelligence, phase recognition | Requires video capture in OR; enterprise sales |
| Caresyntax | $180M (Aug 2024: $80M Series C extension equity + up to $100M growth debt) | Surgical data/video/analytics platform | Largest in category |
| Activ Surgical | Series B total $60M (extension $15M led by Hikma, 2022); another source says $92M total | ActivSight: light/perfusion imaging for surgeons | No recent news found |
| Apella | $80M Series B, total ~$104M. Sources conflict on date (CB Insights says Jan 2024; a 2026-01-12 article reports the close) [UNVERIFIED which] | Ambient AI + computer vision for OR operations/turnover | Closest to "OR perception analytics" |
| Surgical Safety Technologies (OR Black Box) | $15M Series A (May 2023, USVP, Sante); about $18.2M total, further raise Mar 2026 per CB Insights | OR Black Box: audio/video capture for safety and quality | Capture/analytics only, no actuation |

### 1c. Retained item detection

| Company | Status | Product | Notes |
|---|---|---|---|
| Stryker SurgiCount | Stryker bought Patient Safety Technologies (SurgiCount) for $120M in Dec 2013; 660+ US facilities, 10M procedures used (older stat) | Barcoded Safety-Sponge + scanner | Incumbent; barcode scans add steps |
| Medline / ORLocate (Haldor) | Medline distributes; FDA cleared (2010 510(k) K100551) | HF RFID tagged sponges and instruments, detection wand | Requires tagged consumables |
| Gauss Surgical (Triton) | Acquired by Stryker (terms undisclosed) | Computer-vision blood loss estimation on sponges | Blood loss, not item count |
| ClearCount (Medline-linked) | Older RFID player | RFID sponge counting | Historic |

Market-research sizing for sponge counting/detection varies by a factor of 7: $53M (2025) vs. $0.4B RFID sponge tracking (2025). Treat both as soft.

### 1d. Sterile processing (SPD) automation

| Company | Status | Notes |
|---|---|---|
| RIF Robotics | Pre-seed, about $800K debt round; Wellstar Catalyst pilot; prototype identifies/manipulates 4 instruments and assembles a small tray | Directly on our SPD beachhead; very early |
| Steelco Belimed + ZHAW | Research project with humanoid robots assembling trays | Early R&D |
| Censis Technologies | Sold by Riverside to Fortive (Nov 2019, price [UNVERIFIED]); 1,300+ hospitals | Tracking software; no robotics, so a distribution partner or acquirer |
| Case Medical, Ascendco | Searches returned nothing useful [UNVERIFIED] | Case Medical is a reprocessing products company; Ascendco I could not confirm |

### 1e. Surgical simulation

| Company | Facts | Notes |
|---|---|---|
| Simbionix (Surgical Science) | Acquired Aug 2021 for $305M; 2020 sales $41M; 5,000+ simulators installed | Established VR sim, high-priced stations |
| VirtaMed | Searches returned no funding or price [UNVERIFIED]; Swiss VR/haptic simulator maker | Typical sim price points tens of thousands of dollars [UNVERIFIED] |
| SimVentions | No relevant data found [UNVERIFIED] | |
| Market sizing | US surgical simulation $1.16B (2025); global $4.42B (2026). Laparoscopy simulators alone $63M (2025) | Analyst sizing; soft |

### 1f. Physical AI and open hardware

| Company | Facts |
|---|---|
| Physical Intelligence | $70M seed (Mar 2024); $400M Series A (Nov 2024); $600M Series B (Nov 2025, CapitalG, $5.6B); about $1.05B Series C at $11B reported closed May 21, 2026 |
| Hugging Face LeRobot / SO-101 | Open-source stack; SO-101 launched Apr 2025, $100 base, about $130 BOM, $100-500 depending on supplier/tariffs. Acquired Pollen Robotics; Reachy Mini $300, HopeJR $3,000 |
| Perceptron | Founded Nov 2024 by ex-Meta FAIR scientists; $21M round led by Bessemer (Aug 2026); Isaac 0.5 open-weight vision-language model for physical AI, claims to edge out GR00T and Pi 0.5 on LIBERO |
| Physical AI sector | One source claims $47.4B raised in H1 2026 (aggregator, [UNVERIFIED]) |

## 2. Market math (bottom-up, assumptions explicit)

**Facts used:** 38,677 US hospital ORs (Definitive Healthcare); about 5,500 ASCs averaging 3 ORs each (Becker's, 2016 data, so likely stale) giving about 16,500 ASC ORs; 50,550 sterile processing / instrument technicians at a $44,940 median wage (BLS, May 2023); 117,460 surgical technologists (BLS); about 430 surgical technology programs; 280+ general surgery residencies; about 100 ACS-accredited education institutes (2021).

**Our assumed pricing (decision, not fact):** training station = $2,500 hardware (arm + camera + props) + $1,200/yr software. SPD tray-verification = $20K/yr per hospital. OR count-verification = $3K/yr per OR.

### Beachhead A: Surgical training labs (best first target)
- Buyers: about 430 ST programs + 280 GS residencies + about 100 ACS AEIs + about 150 medical schools [UNVERIFIED count] with overlap, estimate about 800 distinct institutions.
- Stations per institution: 3-4 (assumption). 800 x 3.5 = 2,800 stations.
- TAM (US): 2,800 x ($2,500 one-time + $1,200/yr) is about $7M hardware plus $3.4M/yr recurring. Add community colleges, nursing, EMS, and international: roughly 5x, so about $50M/yr. This is small, which is honest: sim incumbents sell $41M/yr (Simbionix) and the whole laparoscopy simulator niche is about $63M.
- SAM: programs without budget for VR sims (ST programs, community colleges, rural residencies), about 500 institutions = about $2M/yr recurring + hardware.
- SOM (3 yrs): 5% = 40 institutions, about 140 stations, around $0.5M ARR. Value is the beachhead and data, not the revenue.

### Beachhead B: Sterile processing (largest dollar pool, hardest tech)
- Labor pool: 50,550 techs x $44,940 = $2.27B wages; with about 25% burden = $2.8B [burden is an assumption].
- Tray assembly/inspection share of tech time: 30-40% (assumption, not sourced) = $0.85-1.1B of labor that vision-assisted assembly could touch.
- Software-first wedge (camera check of tray contents against count sheet, no arm): about 6,000 hospitals + about 5,500 ASCs. SAM = hospitals with real volume, about 3,000 x $20K = $60M/yr. TAM across all = about $230M/yr.
- SOM (3 yrs): 1% of 3,000 = 30 sites = $0.6M ARR.
- Throughput check: one cited SPD runs 300+ trays/day with 47 techs and 2,000 sets; the average hospital is far smaller. Automating even 10% of assembly steps on 300 trays/day is cost-justified only if the system is under about $50-100K per SPD.
- Pain is real: 120-day time-to-fill, 42.9% first-year turnover (from SURGEON_RESEARCH.md; those are surgical tech figures).

### Beachhead C: OR instrument handling and counts
- ORs: 38,677 + about 16,500 = about 55,000.
- Count-verification vision at $3K/OR/yr: TAM = $165M/yr. Cross-check against analyst sponge-counting market of $53M-$0.4B.
- Retained items cost $13K (excess cost per incident) to $525-600K (all-in) each, at 1 in 5,500-18,760 surgeries. At 1 in 10,000 and 50M US procedures [procedure count UNVERIFIED], about 5,000 events/yr; even at the low $13K that is $65M/yr, and at $200K that is $1B/yr. Real ROI argument but needs FDA path.
- Physical handoff robot: payload 0.3 kg, ~5 mm repeatability, non-sterile. Not viable in a live OR for this version. SAM for the arm itself in the OR is about zero today; the value is the perception layer.
- SOM: pilot only, not a revenue line for 3 years.

**Ranking:** (1) training labs, no regulatory path, low price fits our arm, sells in months; (2) SPD tray verification, large labor pool, perception works with fixed camera; (3) OR counting, biggest safety story, longest regulatory road.

## 3. White space

1. **Nobody sells a sub-$5K surgical-support arm.** Everything above is a capital sale (da Vinci $1.5M+, Maestro and Hugo-class systems six to seven figures) or a software subscription with no actuation. Open-hardware SO-101 is about $130-500.
2. **Penelope and Gestonurse proved the concept in 2010s labs and then stalled** for cost, interface complexity, and training-value gaps (as noted in SURGEON_RESEARCH.md section 3). Cheap hardware plus modern perception removes the reasons.
3. **Perception and analytics vendors (Theator, Caresyntax, Apella, SST) only watch.** Retained-item incumbents need tagged consumables. A camera that recognizes untagged instruments from one exemplar photo each is a different cost structure.
4. **Why now (2025-2026):** (a) SO-101 and LeRobot made a $100-500 arm with an open training stack; (b) open-weight vision-language models (Perceptron Isaac 0.5) support few-shot detection without labeled datasets; (c) robot foundation models (Physical Intelligence, $11B valuation) mean policies transfer to cheap arms; (d) chronic tech shortage (120-day fills) and ASC growth create buyers who cannot afford a $1M robot; (e) investors are funding physical AI at record pace.
5. **Risks to state honestly:** low repeatability, no sterility, FDA path for anything near a patient, and incumbents (Stryker, Medline, Intuitive) can bundle.

## 4. Exits and funding, 2023-2026 (investor appetite)

| Date | Event | Size |
|---|---|---|
| May 2023 | Moon Surgical financing | $55.4M |
| Sep 2023 | Virtual Incision Series C extension | $30M |
| Sep 2023 | Diligent Robotics round | $25M |
| Jan/Feb 2024 | MMI Series C (Fidelity) | $110M |
| Jan 2024 or 2026 [date conflict] | Apella Series B | $80M |
| 2024 | Karl Storz acquires Asensus | about $95M |
| Aug 2024 | Caresyntax Series C ext + debt | $180M |
| Nov 2024 | Physical Intelligence Series A | $400M |
| Apr 2025 | CMR Surgical (SoftBank-linked reports) | $200M+ |
| 2025 | Zimmer Biomet acquires Monogram Technologies | about $177M upfront |
| Oct 2025 | Petal Surgical emerges from stealth | $10M Series A |
| Nov 2025 | Physical Intelligence Series B ($5.6B) | $600M |
| Late 2025 | Distalmotion Series G; IPO announced Mar 2026 (outcome [UNVERIFIED]) | $150M |
| Dec 2025 | Medtronic Hugo FDA-cleared (urology) | n/a |
| 2026 | Enovis to acquire eCential Robotics (close expected by YE 2026) | about $180M + up to $41M |
| Jan 2026 | Intuitive FY2025 revenue | $10.06B, +21% |
| Mar 2026 | Surgical Safety Technologies raise | about $18M total, round size [UNVERIFIED] |
| May 2026 | Physical Intelligence Series C ($11B) | about $1.05B |
| Aug 2026 | Perceptron round | $21M |

Takeaways: pure-play surgical robotics raised about $1.17B over 17 disclosed rounds between Aug 2024 and Jul 2026 (one analyst blog, [UNVERIFIED]), skewed to late stage. Exits for sub-scale hardware players are modest ($95M Asensus, $177-180M orthopedic robotics buys). Capital abundance is in physical-AI foundation models, not OR hardware, so the pitch should lead with the perception/AI layer and training data, with cheap hardware as the delivery vehicle. Older reference exits: Simbionix $305M (2021), Stryker/SurgiCount $120M (2013).

## Sources

- [Moon Surgical raises $31.3M](https://www.therobotreport.com/moon-surgical-raises-31-3m-for-robotic-surgery-system/)
- [Moon Surgical $55.4M and FDA clearance coverage](https://www.massdevice.com/moon-surgical-raises-31m-robotic-surgery-system/)
- [Diligent brings in $30M](https://www.therobotreport.com/diligent-brings-in-30m-to-put-moxi-in-hospitals/)
- [Diligent Robotics raises $25M](https://iotworldtoday.com/robotics/diligent-robotics-raises-25m-for-hospital-robot-expansion)
- [Moxi at Rochester Regional (subscription model)](https://www.rochesterregional.org/hub/moxi-robot-rgh-unity-hospital)
- [Andromeda Surgical raises $15M](https://dealroom.co/news/142797-andromeda-surgical-raises-15m-to-bring-autonomy-to-the-operating-room/)
- [Karl Storz acquires Asensus](https://www.fiercebiotech.com/medtech/asensus-surgical-seals-acquisition-deal-karl-storz)
- [Virtual Incision Series C extension](https://www.businesswire.com/news/home/20230919457089/en/Virtual-Incision-Extends-Series-C-Round-with-Additional-30M-Funding)
- [MMI raises $110M](https://www.biospace.com/mmi-raises-110-million-in-series-c-financing)
- [Caresyntax $180M](https://www.massdevice.com/caresyntax-raises-180m-ai-surgical-software/)
- [Caresyntax financials, CB Insights](https://www.cbinsights.com/company/caresyntax/financials)
- [Surgical Safety Technologies financials, CB Insights](https://www.cbinsights.com/company/surgical-safety-technologies/financials)
- [Theator financials, CB Insights](https://www.cbinsights.com/company/theator/financials)
- [Theator $15.5M Series A](https://www.bioworld.com/articles/503418-theator-scoops-up-155m-to-improve-surgical-performance)
- [Apella $80M Series B (Pulse 2.0)](https://pulse2.com/apella-80-million-series-b/amp/)
- [Apella Series B (The AI Insider, Jan 2026)](https://theaiinsider.tech/2026/01/12/apella-closes-80m-in-series-b-to-transform-the-hospital-with-ambient-ai-and-computer-vision/)
- [Surgical Safety Technologies $15M Series A](https://surgicalsafety.com/company/news/surgical-safety-technologies-secures-15-million-series-a-funding)
- [Activ Surgical Hikma-led round](https://www.fiercebiotech.com/medtech/activ-surgical-scores-hikma-led-funding-round-bring-series-b-total-60m)
- [Stryker acquires Patient Safety Technologies $120M](https://www.mddionline.com/software/stryker-acquires-patient-safety-technologies-for-120m-on-the-last-day-of-2013)
- [Stryker acquires Gauss Surgical](https://www.biospace.com/stryker-announces-the-acquisition-of-gauss-surgical)
- [Medline distributes ORLocate](https://www.fiercehealthcare.com/healthcare/medline-to-distribute-only-fda-cleared-system-to-both-count-and-locate-surgical-sponges)
- [SurgiCount facility counts](https://www.beckersasc.com/?p=40122)
- [Sponge counting market (Dimension Market Research)](https://www.globenewswire.com/de/news-release/2024/12/16/2997516/0/en/Sponge-Counting-System-Market-is-expected-to-reach-a-revenue-of-USD-358-1-Mn-by-2033-at-6-8-CAGR-Dimension-Market-Research.html)
- [RFID surgical sponge tracking market](https://marketintelo.com/report/rfid-surgical-sponge-tracking-market)
- [RIF Robotics (TechCrunch)](https://techcrunch.com/2022/10/19/rif-robotics-powers-robots-that-inspect-and-organize-surgical-equipment)
- [RIF Robotics Wellstar pilot](https://catalyst.wellstar.org/rif-robotics-pilot-aims-to-improve-patient-and-team-member-safety-in-sterile-processing/)
- [ZHAW / Steelco Belimed humanoid project](https://www.zhaw.ch/en/research/project/80161)
- [Censis acquired by Fortive](https://softwareequity.com/transactions/censis-technologies-acquired-by-fortive-corporation)
- [Surgical Science acquires Simbionix $305M](https://surgicalscience.com/news/surgical-science-has-entered-into-an-agreement-to-acquire-simbionix/)
- [US surgical simulation market](https://www.towardshealthcare.com/outlook/us-surgical-simulation-market)
- [Laparoscopy simulator market](https://www.reportprime.com/laparoscopy-simulator-r8174)
- [Hugging Face SO-101 (TechCrunch)](https://techcrunch.com/2025/04/28/hugging-face-releases-a-3d-printed-robotic-arm-starting-at-100)
- [Hugging Face Reachy Mini / HopeJR](https://www.eweek.com/news/hugging-face-robots-reachy-mini-hopejr/)
- [Physical Intelligence funding history](https://komo.ai/directory/physical-intelligence-funding)
- [Physical Intelligence Series C talks](https://dealroom.co/news/127095-robot-ai-startup-physical-intelligence-seeks-1b-at-11b-valuation/)
- [Physical AI startups raised $47.4B in H1](https://aiweekly.co/node/10331)
- [Perceptron raises $21M (TechCrunch)](https://techcrunch.com/2026/08/26/ex-meta-scientists-want-to-bring-visual-ai-to-the-factory-floor/)
- [Perceptron Isaac 0.5 vs GR00T and Pi 0.5](https://ai2.work/blog/perceptron-isaac-0-5-edges-out-nvidia-gr00t-and-pi-0-5-on-libero)
- [US operating room count (Definitive Healthcare)](https://www.definitivehc.com/resources/healthcare-insights/number-of-us-operating-rooms)
- [ASC and HOPD statistics (Becker's)](https://beckersasc.com/benchmarking/26-statistics-to-know-on-ascs-hopds-procedures-growth-potential-more.html)
- [Central sterile department statistics (Becker's)](https://www.beckershospitalreview.com/human-capital-and-risk/15-facts-and-statistics-on-central-sterile-departments-and-technicians.html)
- [SPD staffing crisis report (OR Manager)](https://ormanager.com/briefs/report-warns-sterile-processing-staffing-crisis-threatens-surgical-safety)
- [ACS accredited education institutes](https://www.facs.org/for-medical-professionals/news-publications/news-and-articles/newsletters/aei-quarterly/august2021/accredits/)
- [Intuitive FY2025 results](https://www.nasdaq.com/press-release/intuitive-announces-preliminary-fourth-quarter-and-full-year-2025-results-2026-01-14)
- [Medtronic Hugo FDA clearance](https://news.medtronic.com/2025-12-03-Medtronic-announces-FDA-clearance-of-Hugo-TM-robotic-assisted-surgery-system-for-urologic-surgical-procedures?asPDF=1)
- [Surgical robotics funding: late-stage capital, thin deal flow](https://ai2.work/blog/surgical-robotics-funding-late-stage-capital-thin-deal-flow)
- [Surgical robotics M&A and funding guide](https://meddeviceguide.com/blog/surgical-robotics-mna-funding-race-beyond-da-vinci-guide)
- [Zimmer to acquire Monogram](https://finance.yahoo.com/news/zimmer-acquire-monogram-technologies-177-133415508.html)
- [Enovis to acquire eCential Robotics](https://www.beckersspine.com/orthopedic/enovis-to-acquire-surgical-robotics-company-for-180m/)
- [CMR Surgical $200M](https://www.massdevice.com/cmr-surgical-raises-200m-funding-round/)
- [Distalmotion $150M](https://www.massdevice.com/distalmotion-raises-150m-dexter-surgical-robot/)
- Existing team research: /Users/caide_1/Documents/dubhacks/prototypes/SURGEON_RESEARCH.md
