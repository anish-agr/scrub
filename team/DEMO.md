# Table demo

Judging is one 50-minute round at our table in the HUB Ballroom, from 10:30 (be there by 10:20). The whole team stays at the table the whole round. The main-track judge comes once; Perceptron, Photon and NEXT judges can come at any time, so be ready to start over at any moment. The words are in `team/PITCH.md`; answers in `team/QNA.md`.

Our own numbers come only from `team/FACTS-0718.md`. If a number isn't there, skip the sentence.

## What's on the table

- The SO-101 arm, clamped, with the tray: scalpel, hemostat, Mayo scissors. Nothing else on the tray.
- Caiden's Mac running the station (`explore/station`, port 8090) and the voice server. The station page is open; Esc on it is KILL.
- A second laptop with the demo video loaded and paused at the start of the middle section. It's the backup, and it shows what we can't do live: the lighting tries, the thermal graph and rest, and the simulated return.
- The dashboard (`http://localhost:8000/`) open in a tab.
- The Vultr page (`http://144.202.95.111/`) open in a tab. Check it shows the redeployed text before 10:20.
- Brandon in the lab coat and gloves.

## The live routine

Run it only if the arm works at the table. Same four steps every time.

Before 10:20, check against `team/FACTS-0718.md` (07:20): the dataset has 6 hemostat episodes and **0 Mayo scissors episodes**, and the only confirmed real handoffs are 2 scalpel passes. The Mayo step can't run until Mayo scissors demos are recorded and a pass works. The hemostat was offered twice with no confirmed handoff. If either still fails at 10:00, use the scalpel (2 confirmed handoffs) for that step and say so, or show it on the video.

1. **Hemostat.** Brandon: "Hemostat." The arm plays the hemostat skill, carries it to the handoff point at a capped speed and holds it out. Brandon pulls it from the jaw. The arm goes home.
2. **Mayo scissors.** Brandon: "Mayo scissors." Same as above.
3. **Stop, then continue.** On a second Mayo scissors (or hemostat) request, Brandon says "Stop" partway through. The arm freezes where it is, still holding. Caiden points it out. Brandon: "Continue." The pass finishes and the arm goes home.
4. **Manual return.** Evan puts each instrument back in its slot by hand and says so: "On the real arm, the return is manual. The video shows the return in simulation."

Between judges: Evan puts every instrument back, Caiden checks the station page says parked or idle with no warnings, and the hottest motor is under 55 C.

## What's on the video, not live

Point to the laptop for these:

- Lighting: only if shot 5 was filmed. No lighting results were logged on the real arm, so show the clip and give no rate.
- Thermal: the temperature graph during a hold, then the arm going home with its motors off.
- The simulated return, labeled "SIMULATED RETURN (electromagnet)".
- The count-sheet OCR and the tray check, if shots 7 and 8 were recorded.

## When something fails

| What fails | What you see | What to do | Who |
| --- | --- | --- | --- |
| Voice doesn't hear the request | Nothing moves | Say it again, closer to the mic. Still nothing: start the run from the station page | Brandon, Caiden |
| The pick misses | The arm offers an empty jaw, or the jaw closes on nothing | Nobody takes it, so after 45 s it goes home and turns its motors off. Or say "return to home". Evan resets the instrument | Evan |
| The arm heads somewhere wrong | Motion toward the wrong place | Esc (KILL) on the station page. Motors off at once; a raised arm drops, so keep hands clear. Press Motors on to resume | Caiden |
| A motor gets hot | Station page warns at 55 C; at 60 C it goes home, motors off | Say so: "It's resting to cool down." Play the video while it cools. It can run again once every motor is at 50 C | Caiden |
| A camera drops | Station page says a camera is down | Press Home, let the station restart it (about 15 s) | Caiden |
| The arm can't run at all | No motion, errors, no power at the table | Anish calls it. Play the middle section of the video on the second laptop and give the pitch over it | Anish decides, Evan plays |

## Starting the stack

From the repo root on Caiden's Mac. The station must be the only thing holding the arm's serial ports and cameras.

```
explore/station/run_station.sh
cd voice && npm run dev
```

The voice server finds the station on `localhost:8090` by itself (`STATION_URL=off` turns that off). With the station found, instrument names are matched on the laptop and a request starts the arm right away.

If the judges want only the sim and there's power for a laptop only:

```
.venv/bin/python -m controller.run_all backup --offline --loop --pause 2
```

That plays a scripted case on the simulated arm, labeled SIMULATION on the dashboard. Say it's a simulation.

## Rules for the table

- Say a number only if it's in `team/FACTS-0718.md` or the PITCH Sources table.
- Say "research prototype". Never claim clinical use or sterility.
- The pick is a skill we taught it from our demonstrations. No model is deployed on the arm.
- No hand tracking, no safe spot, no second tray, no automatic return on the real arm.
- Stay at the table the whole round.
