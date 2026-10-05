# Working in mtg-gauntlet

Instructions for coding agents (opencode, Claude Code). Read `README.md` for how the simulator works.

## Current work: the engine roadmap

`docs/engine-audit.md` is the plan. Work its **Working checklist** top to bottom, one item per change:

1. Pick the first unticked item in the current phase. Don't start a later phase until the current phase's gate is ticked.
2. Make the change, with a test in `tests/` when it touches rules behavior.
3. Check it:
   - `python3 -m pytest -q tests`
   - `python3 gauntlet.py smoke <deck>` for an affected deck (e.g. `sanar`, `bria`, `codie`)
   - for engine changes, a 100-series run (`python3 gauntlet.py run <deck> --series 100 --tag <short-name>`) compared with the last saved `results/<deck>/*/summary.json`. A category moving more than about 3 points must be intended; say why in the commit.
4. Tick the item in `docs/engine-audit.md` in the same commit, with a one-line note of what changed.

## Conventions

- Card knowledge belongs in `engine/cards.py` (tags and curated tables) before `engine/engine.py`. Avoid new `card.name == '...'` branches in the engine when a tag can express it.
- Cite Comprehensive Rules numbers in comments and tests for rules behavior.
- Don't commit `results/` from local experiments unless asked; the homelab job commits real runs.
- The homelab clone (`/home/kevin/mtg-gauntlet`) pulls from GitHub. Push your branch or `main`, then sync there before running homelab jobs.
