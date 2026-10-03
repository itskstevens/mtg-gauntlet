---
name: mtg-gauntlet
description: Simulate a Commander deck against EDHREC archetype decks in 4-player best-of-3 pods and publish a results page. Use when Kevin asks to playtest, gauntlet, simulate or stress-test a commander deck against opponents or archetypes, test card swaps, or rerun or refresh a gauntlet.
---

# MTG Gauntlet

Runs Kevin's Commander deck through simulated 4-player best-of-3 series against EDHREC average decklists
(bracket 3 and 4) grouped by archetype, then publishes a results page. Everything persistent lives in the private
repo `itskstevens/mtg-gauntlet`: engine code, cached card data, opponent decklists, Kevin's decks, pilot files and
past results. Reuse what is cached; fetch only what is new.

## 1. Set up

1. Attach the repo with `add_repo` (owner `itskstevens`, repo `mtg-gauntlet`, access `push`) and clone it into the
   working directory. Install `pyyaml` if `python3 -c "import yaml"` fails.
2. Read `README.md` and `gauntlets.yaml`. List `decks/` and `pilots/` so you know what already exists.

## 2. Get the deck in

1. Use the decklist from the conversation, or the existing `decks/<deck>/list.txt` if Kevin names a saved deck.
   Folder name: the commander's name in lowercase with hyphens (e.g. `serpent-society`).
2. Write `decks/<deck>/list.txt` as `<qty> <Card Name>` lines with the commander first.
3. Run `python3 gauntlet.py check <deck>`. It must report 100 cards. For any card reported missing (usually
   double-faced), add `"Front Name": "Back Face Name"` to `cards/dfc_map.json` and run check again.

## 3. Pilot file (required for a new commander)

The pilot file tells the simulator how to play Kevin's deck. An untuned starter file plays noticeably worse, so this
step is not optional.

1. If `pilots/<deck>.yaml` is missing, run `python3 gauntlet.py init-pilot <deck>` to get a starter.
2. Read the decklist and edit the file by hand. Use `pilots/serpent-society.yaml` as the worked example:
   - `eyebrow`, `summary`: one line each on what the deck is and how it wins.
   - `engine`: pieces the AI should protect and never sacrifice.
   - `keep_home`: creatures that shouldn't attack (blockers, utility, engines). `keep_commander_home` too.
   - `fodder` (`any`, `deathtouch` or `tokens`) and `fodder_max_cmc`: what may be sacrificed.
   - `instant_sac_tokens`: token names to sacrifice on other players' upkeeps.
   - `tutor_targets`: what tutors fetch, in order.
   - `priorities`: fixed cast priorities for key permanents (80 to 90 for engines). Leave removal, wipes, X spells
     and overruns to the engine.
   - `value_bonus` and `key_cards`: what opponents should want to remove and counter.
3. If the commander has a trigger the tags can't express, it needs code in `engine/engine.py` (see `ME` and the
   Serpent Society trigger in `on_creature_dies`). Tell Kevin when this is needed.
4. Run `check` again; it flags pilot card names that aren't in the list.

## 4. Freshen opponents

1. Run `python3 gauntlet.py stale`. For each STALE deck, WebFetch both URLs printed (EDHREC average decks,
   `/upgraded` and `/optimized`) with a prompt asking for only `<qty> <Card Name>` lines, commander first, lands
   included. Overwrite `b3.txt` / `b4.txt`, confirm each totals 100, and update `fetched` in `meta.yaml`.
   Moxfield blocks automated access; EDHREC works.
2. To add a category or deck Kevin asks for: create `opponents/<key>/` the same way and add it to `gauntlets.yaml`.
3. Run `check <deck>` once more so new opponent cards get cached.

## 5. Smoke test

Run `python3 gauntlet.py smoke <deck>`. It must pass with no hangs or errors. Then check the health lines:
- Attacks aimed at Kevin should be near a third. Far above 40% means the AI is ganging up unfairly.
- Knocked out first should be near 25%. Far above 35% means check the pilot (or the deck is weak; read a game).
- Cards stuck in hand should look plausible. A key card stuck every game means its priority or a tag is wrong.
If anything looks off, read a logged game before running the full gauntlet.

## 6. Run

`python3 gauntlet.py run <deck>` runs 300 best-of-3 series per category (about 2 minutes). Results land in
`results/<deck>/<date>/`.

Before reporting, sanity-check anything surprising. If one opponent wins more than about 55% of pods, or a category
moves far from a previous run, read sample games in `results.json.gz` (`samples` per category) and confirm the
behavior is real. The first build of this tool found an infinite loop and a mis-tagged card this way.

## 7. Insights and report

1. Read `summary.md` and `summary.json`. Write `insights.json` in the run folder: for each category slug, 3 or 4 plain
   bullets with the real numbers (how Kevin loses, which deck is the problem, what wins, what to watch for).
2. Optional: `python3 gauntlet.py variants <deck> --swap "Out->In" [--swap ...]` for swap tests. Each variant gets the
   same shuffles. Differences under 3 points are noise. Never recommend a cut from the "win when cast" table alone.
3. `python3 gauntlet.py report <deck>` writes `report.html`. Publish it with the Artifact tool. If an artifact for this
   deck already exists, update it by URL instead of making a new one.

## 8. Save

Commit and push: the deck, pilot, new card files, refreshed opponents, and the results folder. Use a message like
`serpent-society: gauntlet 2026-10-02 (300 series)`.

## 9. Reply to Kevin

A short table (category, games won, series won), the three or four findings that matter most, any swap-test result,
and one line on the simulator's limits (rule-based AI, no politics). The page card carries the link.

## Reference: fair share and noise

- 4-player pod: 25% of games, about 16% of best-of-3 series.
- 300 series per category: about ±1.6 points per run. 50 series: about ±4.
