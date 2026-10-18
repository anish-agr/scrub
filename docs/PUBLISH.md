# Making the repo public

The `team` folder (the team's working notes) is already removed from the tree. Run these steps right before switching the repo to public, after the last agent session has finished. Don't run step 2 earlier: agents still read `AGENTS.md` and `CLAUDE.md`.

## 1. Keys

The history was scanned for keys during the comb on Oct 17 (no hits). Removed files stay in git history: anyone can read them with `git log --all -- team` or by browsing an older commit on GitHub. If something there must not be readable at all, removing it from history needs a rewrite (`git filter-repo`) and a force push, which this team does not do without everyone agreeing. Check that `.env` is not tracked:

```bash
git ls-files .env      # should print nothing
```

## 2. Move the agent instructions out

`AGENTS.md` and `CLAUDE.md` are instructions for coding agents, not for judges. To keep them for local work, copy them out first (for example to `~/scrub-agents/`) and copy them back into a local checkout later without committing them.

From the repo root, on `main`, with a clean tree:

```bash
git pull --rebase
mkdir -p ~/scrub-agents && cp AGENTS.md CLAUDE.md ~/scrub-agents/
git rm -q AGENTS.md CLAUDE.md
git commit -m "Remove agent instructions before the repo goes public"
git push
```

## 3. Visibility

GitHub, the repo, Settings, General, Danger Zone, Change visibility, Public.

## 4. Dead links

```bash
ls team AGENTS.md CLAUDE.md     # "No such file or directory" for all three
git grep -n -e "team[/]" -e "AGENTS.md" -e "CLAUDE.md" -- '*.md' '*.html'
```

Each line the grep prints is a link that is dead on the public repo. Edit it in the file it comes from (point to the kept equivalent or drop the sentence), commit and push again. This file mentions those names on purpose; ignore its own lines.
