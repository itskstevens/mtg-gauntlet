# mtg-gauntlet

Simulates a Commander deck in 4-player pods against EDHREC average decklists grouped by archetype, plays
best-of-3 series, and produces a results page with per-category metrics, opponent decks, replays and card-swap tests.

## Quick start

```bash
pip install pyyaml
python3 gauntlet.py check      serpent-society      # 100 cards? card data cached? pilot names valid?
python3 gauntlet.py stale                           # opponent lists older than refresh_days
python3 gauntlet.py smoke      serpent-society      # a few logged games + health checks
python3 gauntlet.py run        serpent-society      # 300 best-of-3 series per category (~2 min on 2 cores)
python3 gauntlet.py variants   serpent-society --swap "Withering Curse->Golgari Charm"
python3 gauntlet.py report     serpent-society      # results/<deck>/<latest>/report.html
```

## Layout

| Path | What it holds |
|---|---|
| `gauntlet.py` | Command-line entry point |
| `engine/cards.py` | Parses card scripts and tags each card by role (mana, removal, wipes, counters, stax, tokens, drains, combos) |
| `engine/engine.py` | The 4-player game engine and AI. Card-level knowledge lives here |
| `engine/runner.py` | Series runner, analysis, summaries |
| `cards/` | Cached Forge card scripts (one `.txt` per card). `dfc_map.json` maps double-faced fronts to back faces |
| `opponents/<key>/` | `b3.txt` (EDHREC Upgraded), `b4.txt` (EDHREC Optimized), `meta.yaml` (commander, source URLs, fetch date) |
| `gauntlets.yaml` | Categories and the decks in each, plus run defaults |
| `decks/<deck>/list.txt` | Your list, commander on the first line. `variants/` holds swap-test lists |
| `pilots/<deck>.yaml` | How the simulator plays your deck: engine pieces, cards kept home, fodder rules, tutor targets, cast priorities |
| `results/<deck>/<date>[-tag]/` | `results.json.gz` (every game), `summary.json`, `summary.md`, `insights.json`, `report.html` |
| `report/template.html` | The results page template |

## How it works

- Opponents play their real decklists. Each card is tagged from its rules text, and the AI casts, attacks, blocks,
  counters, removes and combos based on those tags. Known infinite combos and alternate wins are listed in `engine/cards.py`.
- `gauntlets.yaml` has 18 archetype categories, each a pool of up to 25 EDHREC top commanders for that archetype.
- **LGS mode (default, `mode: lgs`)**: every series is a random table, like sitting down at a local game store. It
  picks 3 *different* categories at random and one random deck from each, rolls each deck's bracket (3 or 4) and
  keeps the table for all three games. `--series N` plays N x 18 tables, so each category sits down at about N x 3 of
  them. The report's first tab covers every table; each category tab covers the tables where a deck from that
  category sat down (a table counts toward all three of its categories, so category rows overlap).
- **Category mode (`--mode category`, or any run with `--categories`)**: the original setup, 3 decks drawn from a single
  category's pool per series. Useful for stress-testing one matchup. Seats are random each game. The original four fixed-deck categories live in `gauntlets-classic.yaml`
  (run with `GAUNTLET_CFG=gauntlets-classic.yaml`).
- Prepare (Secrets of Strixhaven) is modeled: creatures with a prepare spell cast it from exile when prepared, Codie,
  Ravenous Codex copies prepare spells and re-prepares the board, and Displacer Kitten / Chakram Retriever / Jeskai
  Ascendancy loops are detected in `loop_combo`. Cards Forge has no script for yet are synthetic files built from
  Scryfall text (marked `# synthetic`).
  A game that reaches `max_rounds` is a draw and counts as a loss for the series.
- Fair share in a 4-player pod is 25% of games and about 16% of best-of-3 series.

## Reading results

- Noise: at 300 series per category, game win rates move about ±1.6 points between runs; at the default 50 about ±4. Treat differences under
  3 points as noise. 50 series is too few to compare lists.
- "Win when cast" tables are correlation. Long games see more cards, so late cards look better than they are.
  Use `variants` (paired runs on identical shuffles) before cutting or adding anything.
- The AI is rule-based. No politics, deals or bluffs. Treat the matchup shape as the finding.

## Extending

- New opponent: add `opponents/<key>/` with both lists and `meta.yaml`, then list it in `gauntlets.yaml`.
- New card behavior: most cards tag themselves from rules text. For cards that don't, add them to the curated
  tables in `engine/cards.py` (`COMBOS`, `STAX`, `DRAW_ENGINES`, `MANA_ENGINES`, `TUTORS`, `ALT_WINS`).
- Engine changes: rerun `smoke`, then `run` and compare against the last saved summary for a deck. A shift of more
  than about 3 points in a category means behavior changed, and that change should be intended.

## Pauper gauntlet (1v1)

```bash
python3 tools/pauper_gauntlet.py meta                       # opponent decks, shares, fetch dates
python3 tools/pauper_gauntlet.py smoke izzet                # one logged match vs each meta deck
python3 tools/pauper_gauntlet.py run --matches 200 --house  # all decks in pauper/lists, ~5 min on 2 cores
```

- Kevin's decks: `pauper/decks.json` (full report data) and `pauper/lists/<key>.txt` (main + `SIDEBOARD:`).
- Opponents: `opponents-pauper/<key>/list.txt` + `meta.yaml`, listed in `gauntlets-pauper.yaml` with metagame share and a
  `trust` rating (how well the engine models the deck). Refresh from MTGTop8 event pages (`/event?e=…`) and
  `/mtgo?d=<deck id>` exports.
- The engine runs in `fmt='constructed'`: 20 life, no commander, the player on the play skips the first draw, no sideboarding.
- Results: `results-pauper/<date>[-tag]/results.json` and `summary.md`; report template `report/pauper-template.html`.

## Collection

```bash
python3 tools/collection.py import EXPORT.csv     # ManaBox .csv or .txt export -> collection/manabox.txt, cards.tsv, history.md
python3 tools/collection.py diff                  # what changed since the previous version
python3 tools/collection.py fits                  # buy-list hits, deck cards now owned, colour-legal homes for new cards
python3 tools/pauper_legal.py                     # refresh collection/pauper_legal.txt (Forge rarity data)
```
Each import is one commit, so `git log -- collection/cards.tsv` is the version history.
