You are starting fresh with no history. This file is all the context you need, plus the files it tells you to read. The project is Scrub, an SO-101 robot arm that passes surgical instruments by voice, built by Anish, Caiden, Brandon and Evan at DubHacks '26 (UW, Oct 17 to 18, 2026). It's Sunday morning: the video goes up on YouTube (unlisted) by 9:00 AM, the final Devpost by 9:30 (it locks at 10:00), everyone in the HUB Ballroom by 10:20, judging from 10:30.

Do all of it yourself, start to finish. Use a lot of subagents: split every small task (each doc, each claim check, each sim fix, each video slot, each test run) into its own agent and run them in parallel. You coordinate and verify. Commit small, `git pull --rebase` before every push, never print or commit a key. When something needs a person (filming, a key, the arm), write it in your final report.

## Read first, in this order

1. `git pull --rebase`.
2. `AGENTS.md`, `README.md`, `docs/OVERVIEW.md`, `docs/CONTRACTS.md`.
3. `team/CONTEXT.md` Part 1 (every sourced stat), `team/STATE.md`, `team/LEFT.md` (the top item is the Gemini and judge-page step from this morning).
4. `docs/INTEGRATION.md`, `team/DEVPOST.md`, `docs/README-PUBLIC.md`, `team/PITCH.md`, `team/SLIDES.md`, `team/DEMO.md`, `team/HIDE.md`.
5. `voice/README.md` (the Photon and ElevenLabs call path and its status notes), `deploy/README.md` (the Vultr page).
6. `video/simcine.py`, `video/simdemo.py`, `video/roughcut.py`.
7. The DubHacks rules: `GUIDE-SUMMARY.md` and `HACKER-GUIDE-FULL.txt` are in Anish's workspace folder; the live guide is https://dubhacks.notion.site/The-DubHacks-26-Hacker-Guide-15dff32c1d7e83748aac8154036aa658 . The parts that matter are quoted under "Rules and judging" below.

## What changed this morning (already on main)

- `821fe46` voice: optional `GEMINI_THINKING_LEVEL` and `GEMINI_MAX_OUTPUT_TOKENS`. Tested on the fake arm: `gemini-3.8-flash` at thinking low parses a request with no tool name in 2.8 s and asks back when it's unclear ("Which screwdriver: flathead or Phillips?"). Known names skip Gemini (1 ms).
- `8e605c1` judge page text now matches what ran; Series and Memory links removed (Tiger Data and Backboard are not used). The live Vultr server still shows the old page and needs a redeploy.
- `d557181` `team/LEFT.md` top item: the Gemini `.env` lines and the redeploy command.
- `3a92b17` `video/simdemo.py`: a scripted sim demo (IK keyframes, eased moves, the jaw closes on the item, the held item rides the gripper). `python -m video.simdemo sheet --out x.png` for a contact sheet, `render --draft --fps 15` for a quick look, `render --out ...` for 1080p 30 fps.

## What Scrub does in the demo (build everything to this)

- Three instruments only: scalpel, hemostat, Mayo scissors.
- The demo video is a hard-coded, recorded routine. Each clip is labeled with what really ran it (model or taught skill). No claim we can't show.
- No safe spot. The scalpel safe-spot step is not possible on the arm; remove it from the routine, the sim, the script, the docs, the pitch, the Devpost and the judge page.
- No hand detection. The camera frame rate is too low to track the hand. What is true: the arm slows down as it nears the handoff point. Remove every "tracks the surgeon's hand / holds when the hand moves away" claim and reword to that.
- After each handoff the arm goes straight home on its own. The sim and the docs must show that.
- The return in the video is simulation only, modeled as an electromagnet pickup, and labeled that way on screen. The real arm does a manual return (a person puts the tool back, or the arm is jogged), and it is labeled manual.
- No music. Real voices. The person asking for tools wears a lab coat; keep faces out of frame, show the arm and the open gloved hand.

## The shot list (record all of it; more takes are better)

Film every shot 20 to 40 s without stopping (start before the ask, stop a few seconds after the arm is home), 3 takes each, phone in landscape, 1080p 30 fps, exposure locked, a second phone recording audio next to the speaker. Name files `V<slot>-take<n>.mp4`.

1. The ask on the phone ("hemostat"), the pick, the carry, the handle into the lab-coat person's gloved hand, the release on pull, the arm going home. Wide take and close take on the handle.
2. Same for the Mayo scissors.
3. Stop mid-move: "stop", the arm freezes, the red STOPPED banner on screen, then reset and continue to finish the pass.
4. Manual return: a tool put back by hand (or jogged), labeled "manual return" in the edit.
5. Lighting: a lamp turned on, glare on the steel, a handoff that still finishes. Do the bright, normal and dim tries and log each one so the lighting table has real rows.
6. Thermal: a screen recording of the temperature graph during a hold, then the arm folding to rest with torque off.
7. The dashboard count and the count-sheet OCR read (Perceptron OCR, Gemini fallback), screen recorded, with the latency shown.
8. The tray check: one real overhead frame of the three instruments through Perceptron detect, screen recorded with the result and latency.
9. If a trained Perceptron model is deployed: an unedited roll of real model picks for the Perceptron Robotics video, then the success table from the ledger.
10. Sim inserts: render with `video/simdemo.py` after the fixes below.
11. Narration voice memos from Anish, Caiden, Evan and Brandon (one line per file, quiet room).

Ideas worth adding if time allows: a side-by-side of the real handoff and the sim of the same routine, labeled "the same routine in simulation" (the sim does not mirror the real arm live, so never say "connected"); a 4x grid of recorded demonstrations for "how it's trained"; the phone screen showing the call and the case-summary text if Photon works.

## Fix the sim (`video/simdemo.py`), then show Anish stills before rendering

Go through the sim play by play: make a 1 fps contact sheet of the whole run (`python -m video.simdemo sheet --every 1 --out ...`), then stills at every event (each grab, release, home, stop, return) and look at each one. Write down every problem you see (pose, jaw, item position, flicker, camera, caption timing), fix it, and repeat until a full pass is clean. One agent per segment.

Anish's notes on the draft:
- The gripper is rotated 90 degrees the whole time. The wrist roll in the IK keyframes (the `READY` pose has roll 1.59 and `across` is tangential) must match how the real SO-101 holds a tool from above: compare against the photos and the real arm, pick the roll that matches, and keep it consistent.
- Rendering glitches on the scissors and during the return (items flicker or jump). Check `Player.items_at`: the grab/place offsets, the `appear` event, the settle-flat step, and that hidden items don't pop in. Look at 1 fps contact sheets around each event, not just a few stills.
- Remove the scalpel safe-spot segment. New sequence: hemostat into the hand, arm home; Mayo scissors into the hand, arm home; a stop mid-move then continue; the simulated return of the hemostat labeled "SIMULATED RETURN (electromagnet)".
- After each handoff the arm goes home directly.
- Zoomed out (camera distance about 1.45, fixed), only a small SIMULATION tag and a plain caption. Nothing else on screen.
- The draft is 15 fps on purpose. The final is 30 fps 1080p (about 8 minutes to render). Send Anish a contact sheet and wait for his okay before the final render.
- The overlay and cards must not look AI-made: no step strip, no glowing boxes, no decorative labels, plain type.

## The video (you own all of it)

You build the whole video. We will send you the recordings as we film them (files named `V<slot>-take<n>.mp4` and voice memos). Get everything ready now so each file drops in: pick the best take, trim it, put it in `data/video/kit/real/V<slot>.mp4`, rebuild with `python -m video.roughcut`, and keep a current cut we can watch at any time. Before any recordings arrive, make sure the pipeline works end to end with the sim stand-ins and the cards (run it, watch the output, fix anything broken), and update `video/roughcut.py`'s slots and cards to the new script and scope. Captions burned in for every spoken line, plain white text, nothing that looks AI-made. Tell us which slots are still missing each time you rebuild.

- Length: 2 to 3 minutes, under 3:00. The script Anish's team wrote runs to about 2:40 and plays as narration over the clips.
- Fix the script to match the scope: drop the safe spot and "never hand to hand", drop hand tracking (say the arm slows near the handoff), keep "model trained on our demonstrations" only if that clip is a real model pick (otherwise "a skill we taught it"), drop "if a motor goes down, degraded control keeps working" unless it's tested on video, drop "texts a case summary" unless Photon works, keep the lighting line only after real lighting tries are logged.
- Assemble with `python -m video.roughcut` (real takes go in `data/video/kit/real/V<slot>.mp4`), then trim, captions and room tone in CapCut or similar. Export 1080p 30 fps H.264, about -16 LUFS. Upload unlisted by 9:00 and put the link on Devpost.
- The same middle section is what plays at the table if the arm can't run there.

## Rules and judging (from the hacker guide)

- Exactly one title track (ours: Community Kitchen), up to 3 sponsored side tracks, any number of non-sponsored.
- Public GitHub repo linked on Devpost before 10:00. At least 70% of the code written during the event. No video means no judging.
- Judging is in person, expo style, in the HUB Ballroom. One 50-minute round at an assigned table; the whole team stays at the table the whole round. The main-track judge comes, and side-track judges (Perceptron, Photon, NEXT do in-person judging) come at any time. The schedule appears on the hacker profile after submissions close; check it.
- MLH tracks (Gemini, MongoDB, Vultr) are judged mainly from Devpost and may not visit.
- Perceptron Robotics: "a pre-trained checkpoint with an SO-101 robot arm, both of which will be provided. Teams may collect their own demonstration data and fine-tune it." Judged on creativity, task difficulty and technical execution, and teams "should plan to submit a short video of their working demo." Fine-tuning is allowed, not required. We were given the arm, recorded our own demonstrations and tuned on them, and we wrote our own control and safety layer around it. Say exactly what ran: if the model is deployed and picks, show it; if not, say the pick is a taught skill and the training run is shown separately.
- Perceptron Perception: their vision API out of the box (detect, OCR). Fine-tuning not expected. This is our safest Perceptron entry.
- Photon: must be built on Photon 2.0 and live on at least one Photon channel. A real call or text on the new SMS line counts.
- Plan for the table: bring the arm and run the routine live if it works there; the video plays on a laptop as the backup and to show shots we can't do live (lighting, thermal, sim return). Have the dashboard and the Vultr page open.

## Tracks to enter, with the proof each needs (put this list at the top of `team/DEVPOST.md`)

- Community Kitchen (title).
- Perceptron Robotics: the arm on video, plus a real model pick if deployed; otherwise the training job id and its state, said plainly.
- Perceptron Perception: the tray check and the OCR read on video with latency.
- Photon: the call on +1 785 867 1047 (already set up), on video.
- DubHacks NEXT.
- MLH Gemini API, MLH MongoDB Atlas, MLH Vultr (the public page, after the redeploy).
- Not entered: Tiger Data, Backboard, GoDaddy. DEV writing is a blog post that can go up after the event.

## Voice

Photon is already set up on your side. Don't redo it. Confirm one real call on +1 785 867 1047 moved the arm and is logged, and make sure the Gemini lines from `team/LEFT.md` are in your `.env`. The new ElevenLabs `sk_` key has no user_read permission, so change `deploy/check_env.py`'s `GET /v1/user` probe to `GET /v1/models` so it doesn't show a false FAIL.

## Vultr

The live page (http://144.202.95.111/) still shows old claims (bench tray, fine-tuned Isaac doing the picks, the Photon number, Tiger Data, Backboard) and stats from sim and fake runs. The repo already fixes both. Redeploy from a laptop whose SSH key is on the server (Brandon's): `powershell -File deploy/push_public.ps1 -Target root@144.202.95.111`, or add your key. Then update the page text again for the new scope (no safe spot, no hand tracking) and redeploy. Check `curl -s http://144.202.95.111/` and `/api/stats`.

## Everything we say must be true

Go through `docs/INTEGRATION.md`, `team/DEVPOST.md`, `docs/README-PUBLIC.md`, `team/PITCH.md`, `team/SLIDES.md`, `team/DEMO.md`, the judge page, the dashboard text and the video script. Every claim gets checked against what ran today; remove or reword the rest. Every number comes from the ledger or the dataset, or the sentence goes. Remove the safe spot, hand tracking, the bench tray, Tiger Data and Backboard everywhere. Keep the sterility answer: Scrub never touches the patient and is a research prototype; a clinic version would run under a sterile drape on a medical-grade arm, like today's surgical robots, with the trays and tools sterilized as usual. We don't claim it's sterile.

Failsafes we can state (check each in code before keeping it): stop freezes the arm until reset; the thermal guard reads motor temperatures twice a second and rests the arm with torque off between requests; speed and joint limits; a grasp check before carrying; release only on a pull; the arm slows near the handoff point.

Write it all like a person: no em dashes, no filler, no "it's not X, it's Y", no decorative words.

## Finish line (by 9:00)

- The video uploaded unlisted, link on Devpost.
- The Devpost final text with the tracks and proof at the top, every claim checked.
- Tests that passed before still pass; `python -m controller.run_all --real` and the sim backup start; `git status` clean; nothing ahead of origin/main.
- At 9:00 Anish runs `team/HIDE.md` and makes the repo public. Don't run it yourself.

Report at the end: the call result, the training job and deployment state, real tries per item and source, which shots exist, the tracks entered with proof, every claim removed, and what a person still has to do.
