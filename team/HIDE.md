# Hiding team/ before the repo goes public

`team/` holds how we worked (plans, status, pitch, prompts, prototypes, research notes). A judge doesn't need it to understand, run or trust Scrub. Run these on Sunday at 8:30 AM, after the last edit to anything in `team/`. Don't run them earlier.

From the repo root, on `main`, with a clean tree:

```bash
git pull --rebase
git mv -f docs/README-PUBLIC.md README.md    # the judge-facing README replaces the team one
git mv AGENTS.md CLAUDE.md team/              # agent rules go with the team's notes
git rm -r -q team/
git commit -m "Remove the team's working notes before the repo goes public"
git push
```

Then make the repo public: GitHub, the repo, Settings, General, Danger Zone, Change visibility, Public.

Check after the push:

```bash
ls team AGENTS.md CLAUDE.md          # should say "No such file or directory" for all three
grep -rn "team/" --include='*.md' --exclude-dir=node_modules --exclude-dir=.venv . | head
```

Any `team/` link that the grep prints is a dead link on the public repo. Remove it in the file it points from and push again.

The files stay in git history. Anyone can read them with `git log --all -- team/` or by browsing an older commit on GitHub. The history was scanned for keys during the comb on Oct 17 (no hits). If something in `team/` must not be readable at all, removing it from history needs a rewrite (`git filter-repo`) and a force push, which this team does not do without everyone agreeing.

To keep agent rules for local work after the push, copy `AGENTS.md` and `CLAUDE.md` out of the repo before running the commands (for example to `~/scrub-team/`), and copy them back into a local checkout without committing them.
