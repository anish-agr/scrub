# Deslop pass (small job, run later, after the full pass is done)

Say to any agent: "Pull, then follow team/DESLOP-PROMPT.md (or docs/ if it hasn't moved). Use subagents, one per folder."

Rewrite the comments, docstrings, README text, help strings, UI copy and voice lines so nothing reads as AI-written. Don't change behavior: no logic edits, no renamed identifiers, no changed field names or strings that tests or the contracts check. Run every test after each folder and commit per folder.

Fix these:
- Em dashes. Use a period, comma or parentheses.
- "It's not X, it's Y" in any form.
- Rhetorical questions, colon reveals, one-line paragraphs for effect, neat closing lessons.
- Sentences ending in ", ensuring ...", ", highlighting ...", ", showcasing ...".
- Filler: honestly, genuinely, truly, really, actually, simply, just, exactly, very, quite.
- Decorative AI words: delve, tapestry, landscape, realm, leverage, harness, foster, robust (as praise), seamless, pivotal, crucial, vital, testament, unlock, empower, journey. Keep a word when it's the accurate technical word.
- Comments that restate the code below them. Delete those. Keep comments that say why.
- Emojis in code, logs or UI.

Rule of thumb: say the thing plainly, then stop. A comment explains a reason, a limit or a measured number.
