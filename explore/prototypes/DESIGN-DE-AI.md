# De-AI design guide (read before restyling any prototype)

Sources: Caiden's frontend-design research (`~/Documents/frontend_design/transcripts`: the AJ "AI website tells" reel and the
Talha "design styles" reel), the Lavish design rules (`npx -y lavish-axi design`), and the apartment-finder review UI.

## 1. Lavish rule: match the subject's real design system first
Priority: (1) what the user asked for, (2) the real product's own design system, (3) a generic fallback only if both are empty.
Scrub has no design system yet, so the "real product" is **the operating room itself**. Borrow from real artifacts that
exist there instead of from web templates:
- **Medical device HMIs** (anesthesia machines, patient monitors, infusion pumps): flat panels, black or very dark grey
  ground, alarm colors that follow IEC 60601-1-8 (red = high priority, yellow/amber = medium, cyan = low/info),
  fixed-position numeric readouts, units always printed, no decoration, no rounded "app" cards.
- **Paper forms**: the surgical count sheet, the WHO Surgical Safety Checklist, instrument tray tags, preference cards.
  Ruled lines, boxed fields, pre-printed labels in small caps, handwritten-feel entries, initials columns, form numbers
  in a corner ("Form OR-114 rev. 3").
- **Sterile processing labels**: autoclave indicator tape stripes, peel-pouch labels, lot numbers, barcodes.
- **Surgical instrument catalogs** (Aesculap, Sklar): line drawings of instruments on white, item codes like
  "BH110R", dimensions in mm, dense specification tables.
- **OR whiteboards / wall displays**: big case clock, room number, surgeon initials, hand-lettered status.
Pick ONE of these worlds per prototype and commit to it.

## 2. Banned: the AI tells (from the AJ reel, all of them)
Never use any of these:
- harsh gradients; purple and black; neon colors; basic pastel palettes; rainbow coloring
- pure white background used lazily (white is OK only when copying a real white artifact like a paper form or catalog)
- drop shadow on everything; soft large corner radius everywhere; liquid glass / glassmorphism; radial orbs; dot grids
- loose decorative side icons; sparkle icons; animated arrows; emojis
- the colored accent stripe on the left of cards; three feature cards in a row; bento grids; three pricing tiers
- checkmark bullet lists; fake testimonials; terminal-window decoration
- Inter, Geist, or Space Grotesk fonts
- "it's not X, it's Y" copy; em dashes
- hover animations on everything
- no real product demo (always show the actual thing working); no skeleton loaders where data loads
- missing TOS / privacy links on anything user-facing (add a plain footer line with "Terms" and "Privacy" placeholders)

## 3. Name a real style and commit (from the Talha reel)
Choose one named style per page and write it in the top comment: e.g. **Swiss Design** (grid, Helvetica-like grotesk,
flush-left, red/black), **Editorial Design** (serif headlines, columns, captions, rules), **Medical device HMI**,
**Neobrutalism** (hard 2px black borders, flat fills, offset solid shadows, no blur), **Wabi Sabi** (paper, imperfect,
muted earth), **Minimalism**, **Luxury Typography**, **Scrapbook**. Avoid Glassmorphism, Neumorphism, Synthwave,
Cybercore, Y2K for this project: they read as AI or as gimmicks next to a medical subject.

## 4. Concrete craft rules
- Fonts that are not the defaults. Good picks for this subject: IBM Plex Sans / Plex Mono (instrument panels),
  Public Sans or Atkinson Hyperlegible (healthcare legibility), Source Serif 4 or Newsreader (forms, editorial),
  Archivo / Archivo Narrow (labels), JetBrains Mono only for code. Use tabular numerals for every number.
- Square or near-square corners (0 to 4px). Separate with 1px rules and whitespace, not shadows.
- Color comes from meaning: alarm states, instrument status, sterile vs not. One accent at most besides semantic color.
- Copy in the voice of the room: "Kelly, curved, 5.5 in", "Count 1 of 3: initial", "RN: J. Ortiz", "OR 4", "T+00:42:10".
  Real units (mm, s, kg), real item codes, real roles (circulating RN, scrub tech, attending).
- Imperfection on purpose where the source artifact has it: slightly uneven handwriting font for initials, a stamp,
  a hole-punch margin on a form, a barcode, a fold line. Keep it subtle.
- Motion only where state changes (a count updating, an alarm). No idle floating, no hover lifts.
- Show the product working: the live state, the camera view, the actual numbers. No marketing hero sections.
- Skeleton loaders (plain grey bars) when something is "loading", e.g. perception results.
- Keep every existing feature, interaction, STOP control, keyboard shortcut, mock data and the header comments.
  This is a restyle, not a rewrite of behavior.
