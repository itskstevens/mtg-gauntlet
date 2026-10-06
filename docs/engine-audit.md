# Gauntlet engine audit

2026-10-05 · Kevin · Source doc: [Gauntlet engine audit](https://claude.ai/code/artifact/14f5eb66-40f3-4332-b3af-0e20d78c44c0)

The gauntlet is a good tag-based approximation of creature and combat decks, but it isn't yet a rules engine. About 36% of opponents' nonland cards do nothing in the sim, spells and combo decks are badly under-modelled, and win rates run from 0.1% to 58%, a spread real Commander pods don't produce. Turning it into a product means rebuilding around a real rules core and validating against real game data.

> **For agents (Claude, opencode):** work the roadmap from the [Working checklist](#working-checklist) at the end. Tick items in this file as they land, in the same commit as the change. Before and after any engine change run `python3 -m pytest -q tests`, `python3 gauntlet.py smoke <deck>`, and compare a 100-series run against the last saved `results/<deck>/*/summary.json`; a category shift over about 3 points must be intended (see README, "Extending").

## At a glance

The engine handles commander rules, combat and the mainstream card roles well. The gaps are in how it represents the game: no stack, no generic activated abilities, Treasures and lands as plain numbers, and a hand-written list of cards it knows.

| Measure | Today | Why it matters |
| --- | --- | --- |
| Opponent nonland card slots doing nothing in the sim | 36% (19,868 of 55,234) | Opponents play weaker than their real lists |
| Distinct cards with no modelled abilities | 3,867 of 6,715 | Long tail, one card at a time |
| Median opponent deck that is blank | 36%; worst decks 64–67% | Some archetypes barely play Magic |
| Your tuned decks that are blank | Aziza 5%, Lae'zel 3%; Doran 51%, Sanar 24% | The sim rewards decks it was built around |
| Spread of your all-tables series win rates | 0.1% (Sanar) to 58.3% (Toxrill) | Very wide around a 16% fair share; not yet checked against real games |
| Card names hard-coded in game logic | 131 in the engine, 72 in the tagger | Every new card needs code |
| Rules tests | 16 | Too few to catch regressions |
| Speed | 1,800 tables in about 1 minute on 16 cores | Fast enough to keep |

The biggest single correctness bug: Isochron Scepter + Dramatic Reversal is listed as a combo but can never fire, because the check needs both on the battlefield and Dramatic Reversal is an instant.

## How the engine works today

Each stage of the pipeline has one main gap:

| Stage | What it does | Main gap |
| --- | --- | --- |
| 1. Decklists | Your list and pilot file, plus 848 EDHREC average decks (424 commanders, B3 and B4) in 18 archetypes | Average lists, not real decks; scraped, so a licensing question for a product |
| 2. Card loader (`engine/cards.py`) | Reads cached Forge scripts (7,400+ cards) for cost, types, power/toughness, keywords and oracle text | GPL-3.0 data; only the text is used, not Forge's own rules scripting |
| 3. Tagger (`engine/cards.py: tag()`) | Regex rules and curated tables turn text into roles: ramp, removal, counters, tokens, drains, combos | 36% of opponent slots get no role; 131 cards special-cased by name |
| 4. Game engine and AI (`engine/engine.py`, `engine/counters.py`) | Turns, combat and tag effects for four players; your deck follows its pilot, opponents share one AI | No stack, no generic activated abilities; Treasures are a number |
| 5. Runner and report (`engine/runner.py`, `gauntlet.py`) | Random LGS tables, best of 3, on 16 cores; writes summaries, insights and the HTML report | No real-game check yet; your decks' win rates span 0.1% to 58% |

The engine never runs card rules directly. It turns each card's text into a handful of role tags, and the game loop acts on those tags, so anything a tag can't express is invisible to the game.

## Card coverage

A card counts as blank when the tagger gives it no role and no engine code mentions it by name. A creature whose only text is evasion keywords counts as covered, since it still fights. Measured over all 848 opponent lists (424 commanders, B3 and B4) on 2026-10-05.

| Card type | Blank slots | Share blank |
| --- | --- | --- |
| Creature (abilities ignored, body still fights) | 11,476 of 22,187 | 52% |
| Enchantment | 2,623 of 6,794 | 39% |
| Sorcery | 2,143 of 7,204 | 30% |
| Artifact | 2,179 of 8,835 | 25% |
| Instant | 1,449 of 9,556 | 15% |
| Planeswalker | 99 of 648 | 15% |

The most-played blank cards are mostly ordinary staples, so a few dozen targeted fixes buy a lot:

| Card | Opponent decks running it | What it should do in the sim |
| --- | --- | --- |
| Nature's Lore | 271 | Ramp: fetch a Forest untapped |
| Three Visits | 205 | Same as Nature's Lore |
| Deflecting Swat | 196 | Free redirect of removal |
| Victimize | 103 | Reanimate two creatures |
| Frantic Search | 96 | Draw/discard, untap three lands |
| Wild Growth | 64 | Land aura ramp |
| Rhythm of the Wild | 57 | Haste and uncounterable creatures |
| Panharmonicon | 57 | Double ETB triggers |
| Seedborn Muse | 55 | Untap on each turn |
| Sun Titan | 53 | Recur small permanents |
| Hardened Scales | 49 | +1/+1 counter replacement |
| Phyrexian Metamorph | 49 | Clone |

Equipment is the largest blank family: equip appears in 2,561 opponent slots and the engine has no equip model, so Swords, Shadowspear, Mithril Coat and similar cards do nothing. That makes Voltron opponents easier than they should be.

Your own decks show the same bias in reverse. The decks the engine was built around are almost fully modelled; the rest are not.

| Your deck | Nonland cards blank |
| --- | --- |
| Lae'zel (B3) | 2 of 66 (3%) |
| Aziza | 3 of 65 (5%) |
| Codie | 5 of 64 (8%) |
| Serpent Society | 6 of 63 (10%) |
| Bria | 13 of 65 (20%) |
| Sanar | 17 of 71 (24%) |
| Toxrill | 22 of 64 (34%) |
| Rankle | 26 of 65 (40%) |
| Doran | 33 of 65 (51%) |

## Rules audit

Checked against the Comprehensive Rules effective 2026-09-25, via the mtg-rules server. Commander basics (903), combat damage and keyword combat rules were already audited on 2026-10-04 and hold up. The gaps are structural: the engine has no stack, no generic abilities and no object model for mana or lands.

| Area | Rules | Engine today | Impact |
| --- | --- | --- | --- |
| Stack and priority | 117, 405, 608 | No stack. Counterspells fire as the spell is cast; instant removal is used only to break a combo; everything else happens at sorcery speed | High: no responses, no flash play, no end-of-turn tricks, no protection in response |
| Activated abilities | 602, 605 | Not modelled in general; about 130 cards special-cased by name | High: Sanar, Marvin, Ioreth, Krenko-style engines, equip, mana sinks |
| Triggered abilities | 603 | Tagged buckets (ETB, dies, cast, landfall, attack, upkeep); no APNAP ordering, no "intervening if" | Medium |
| Continuous effects and layers | 613 | Power/toughness from pumps, anthems and counters only; no type, control or ability-changing layers | Medium: control magic, Blood Moon, Humility-style effects |
| Replacement effects | 614, 616 | Only token doubling and a few names (e.g. enters-tapped lands) | High for Xorn, Hardened Scales, Panharmonicon-style cards |
| Copying | 707 | Spell copies for Aziza, Twinning Staff and magecraft only; no clone permanents | Medium: Spark Double, Metamorph, Isochron Scepter |
| Tokens | 111.10a | Treasures are an integer, not artifact permanents | High: no artifact ETB triggers (Reckless Fireweaver, Weftstalker), no artifact count |
| Lands | 305 | A land count plus colour list; only a few named lands exist as permanents | Medium: land destruction, land auras, Crucible, landfall recursion |
| Mana | 106, 605 | One number per turn; colours checked by matching, but already-tapped sources aren't tracked | Medium |
| Storm | 702.40a | Grapeshot deals the spell count to the lowest-life opponent; Brain Freeze is blank; only your own spells count | Medium |
| Attacking | 802, 903.2 | Commander's default is attacking multiple players; the engine sends all attackers at one player (plus walkers) | Medium: changes who dies first and how threats spread |
| Mulligans | 103.5, 103.5c | Keeps 2–5 landers, at most 3 tries; free first mulligan correct | Low |
| Extra turns, control change, phasing | 500.7, 613.1b, 702.26 | Not modelled | Low to medium by deck |
| Politics, deals, goad | 701.15 | Threat scoring only; goad not modelled | Medium for casual-table realism |

## Keyword coverage

Every keyword ability (702) and keyword action (701) in the current rules was checked against the engine's code, weighted by how many opponent slots use it. The common combat keywords (flying, trample, deathtouch, first strike, menace, lifelink, ward, hexproof, indestructible) are handled. These are the most-used ones the engine never mentions:

| Keyword | Rule | Opponent slots | What it needs |
| --- | --- | --- | --- |
| Equip | 702.6 | 2,561 | Attach model plus an activated ability |
| Scry | 701.22 | 791 | Library-top decision (cheap to approximate) |
| Cycling | 702.29 | 575 | Activated ability from hand |
| Overload | 702.96 | 481 | Alternative cost that turns removal into a wipe |
| Proliferate | 701.34 | 464 | Counter engine hook (counters.py exists) |
| Regenerate | 701.19 | 458 | Replacement on destroy |
| Food | 111.10 | 376 | Token permanent with life ability |
| Transform | 701.27 | 348 | Double-faced card state |
| Phasing | 702.26 | 242 | Treat as temporary removal or protection |
| Cascade | 702.85 | 213 | Free cast from library on cast |
| Gain control | 613.1b | 208 | Controller field on permanents |
| Changeling | 702.73 | 207 | All creature types (matters for typal) |
| Cumulative upkeep | 702.24 | 173 | Upkeep cost |
| Extra turns | 500.7 | 162 | Turn queue |
| Affinity, convoke, improvise | 702.41, 702.51, 702.126 | 337 combined | Cost reduction |
| Crew | 702.122 | 152 | Vehicles become creatures |
| The Ring Tempts You | 701.54 | 129 | Ring-bearer emblem |
| Goad | 701.15 | 87 | Forced attack, not at the goader |
| Monarch | 725 | 52 | Draw-and-steal designation |

These counts come from a keyword search on card text, so they are approximate. Keywords the engine mentions may still be only partly modelled.

## Calibration and bias

The sim's numbers are internally consistent (reruns land within about ±1.3 points) but not yet validated against real games. Three things push them away from reality.

**Your decks get a better pilot than opponents.** Your deck plays through a hand-tuned pilot file and its own main-phase logic (`my_main`, `my_score`). Opponents share one generic AI (`ai_main`, `ai_score`). Your best-supported decks are also 95%+ modelled while the median opponent is 64% modelled.

**The spread is too wide.** Latest all-tables runs, 1,800 random tables each:

| Your deck | Series won | Games won |
| --- | --- | --- |
| Toxrill | 58.3% | 56.2% |
| Serpent Society | 50.5% | 50.3% |
| Aziza (final) | 48.1% | 48.1% |
| Lae'zel (B3) | 31.4% | 36.7% |
| Rankle | 23.2% | 30.1% |
| Doran | 13.5% | 21.0% |
| Codie | 9.4% | 18.2% |
| Bria | 5.7% | 12.7% |
| Sanar | 0.1% | 2.4% |

Fair share is about 16% of series and 25% of games. A deck winning half its 4-player games against bracket 3–4 lists would be exceptional at a real table, and a tuned storm deck winning 2% is not credible. Both ends point to modelling, not deck quality.

**Opponents are averages, not players.** EDHREC average decks are a sensible stand-in, but nobody actually sleeves the average list, and the AI never plays politics.

The fix is a ground truth. [Playgroup.gg](https://playgroup.gg/commanders/tier-list/365-days) publishes win rates from 335,102 logged casual games over the last 365 days, across 1,188 commanders with at least 150 games each. Simulating those commanders' lists against each other and comparing the ranking to Playgroup's is a concrete, repeatable accuracy score. Its site shows no API, so data access would need asking.

## What Sanar and storm decks need

Sanar's 1,800-table run won 2.4% of games. In a 60-game trace the deck cast Seething Song 317 times, recast Sanar 2.5 times a game, never cast Freed from the Real or Pemmin's Aura, and assembled a win once. These changes, in order, would make spells decks measurable. The first four are small enough to do inside today's engine.

| # | Change | Rules | Fixes | Size |
| --- | --- | --- | --- | --- |
| 1 | Let combos include spells: a combo is live when its permanents are out and its spell pieces are in hand with mana to cast them | 601, 608 | Isochron + Dramatic Reversal (every deck), Crackle with Power as an infinite-mana outlet | Small |
| 2 | Model imprint as a stored card on the permanent | 406.6, 607 | Isochron Scepter as a real engine | Small |
| 3 | Auras that are combo pieces target the right creature (Freed/Pemmin's on Sanar, not any creature) | 303.4, 702.5 | Sanar's Xorn loops | Small |
| 4 | Tag the missing spells: Brain Freeze (storm mill), Frantic Search (net mana), Hex Magic, Crackle with Power (X burn), Nexus of Fate (extra turn) | 702.40, 500.7 | 17 blank Sanar cards | Small to medium |
| 5 | Make Treasures real artifact tokens | 111.10a | Reckless Fireweaver, Weftstalker, Storm-Kiln Artist's power, Xorn's extra Treasure as a replacement | Medium |
| 6 | A generic activated-ability model with tap costs, mana costs and "activate only if" conditions | 602, 605 | Sanar's Treasure ability, Marvin copying abilities, untappers, equip | Large |
| 7 | A real storm count: all spells cast this turn by anyone, each copy targeting separately | 702.40a | Grapeshot and Brain Freeze math | Small once spells are objects |
| 8 | Turn-planning AI for combo turns: chain rituals and cantrips only when the chain reaches a win or a payoff | n/a (AI) | The Seething Song spam; casting rituals with nothing to follow | Large |
| 9 | Stop opponents treating every commander as the top removal target | n/a (AI) | Sanar removed 4,355 times in about 4,300 games | Small |

Items 1–4 are a day or two of work and would give Sanar, Bria and Codie a first honest number. Items 5–8 are the same work the general rules gaps need, so they belong in the rebuild below rather than as more special cases.

## Making it a paid product

The engine is yours, but almost everything it feeds on is someone else's, and two of those sources (Wizards and Scryfall) explicitly forbid charging for access. This needs settling before any paywall, ideally with a lawyer; this is a summary of the published terms, not legal advice.

| Dependency | What the repo uses it for | Published terms | Risk for a paid product |
| --- | --- | --- | --- |
| Wizards of the Coast IP (card names, text, art) | Everything | Fan Content Policy: fan content must be free to access; no subscriptions or paywalls; ads, sponsorships and donations are allowed; selling Wizards-related content needs permission | High: a paid simulator over Magic cards needs a licence from Wizards, or a free core funded by ads, sponsorship or donations |
| Scryfall | Card images and some card text | No paywalling Scryfall data; must add value; no proxying; 50–100 ms between requests | High for images and data behind a paywall |
| Forge card scripts | `cards/` (oracle text and types for 7,400+ cards) | GPL-3.0 | Medium: using its data in a closed commercial product needs care; shipping it inside a closed service is the risky part |
| EDHREC average decks | Every opponent list | Terms not checked (page unavailable) | Medium: scraping as a product's data source needs permission |
| Playgroup.gg (proposed) | Calibration data | No API found | Needs a data partnership |

Two ways to stay on the right side of this:

- **Free tool, paid service around it.** Keep the simulator free to use, and fund it with ads, sponsorship or donations, which the Fan Content Policy permits. Alternatively, charge only for things that aren't Wizards content, such as compute or hosting. Whether that counts as "access" under the policy is exactly the question to put to Wizards or a lawyer.
- **Licensed product.** Ask Wizards for written permission or a licence. That's slower, but it's the only clean route to a subscription.

On the engineering side, a product also needs: card data loaded from a source you're allowed to use, rather than Forge scripts; automated regression tests in the hundreds, not 16; an accuracy score published with every release; and opponent decks users can supply themselves, so you're not dependent on scraped lists.

## Roadmap

Fix the cheap gaps first, then prove accuracy before rebuilding. Phases are in order, not to scale; each gate must pass before the next phase starts.

| Phase | Focus | Work | Gate to leave the phase |
| --- | --- | --- | --- |
| 0. Quick fixes | Inside today's engine | Spell combo pieces, imprint, aura targets; top 40 blank staples; basic equipment; fairer removal targets | Sanar, Bria, Codie get honest numbers |
| 1. Validate | A real-game yardstick | Playgroup.gg data deal; same AI for all seats; accuracy score with every engine change | Sim ranking tracks real-game ranking |
| 2. Rules core | Build, or adopt XMage | Stack and priority; tokens and lands as real permanents; generic activated, triggered and replacement abilities | Accuracy holds and blank cards are rare |
| 3. Product | Only once allowed | Wizards permission; card data you may use; user-supplied decks; hosted runner and reports | Launch |

Validation comes before the rebuild on purpose. Without a real-game yardstick there's no way to tell whether a new rules core is more accurate, only that it's more complex. The big decision in phase 2 is build versus adopt. [XMage](https://github.com/magefree/mage) is MIT-licensed and already has a rules engine with AI opponents and a server mode. [Forge](https://github.com/Card-Forge/forge) has the same but is GPL-3.0, which is harder to fit inside a closed paid service. Either still leaves the Wizards and Scryfall terms to settle.

## Working checklist

Tick items as they land, and add the commit hash. Convention so far: commit the change, then a second commit `roadmap: tick <id> (<hash>)` that ticks the box with a one-line note of what changed and the smoke numbers. Keep items small enough for one session.

### Phase 0 — quick fixes (inside today's engine)

- [x] **0.1 Spell combo pieces.** `engine/engine.py: check_combo`, `spell_threat`, `my_score`/`ai_score` treat a combo as live when its permanent pieces are on the battlefield and its instant/sorcery pieces are in hand and castable. Unblocks `('Isochron Scepter', 'Dramatic Reversal')` in `engine/cards.py: COMBOS`. Add a test in `tests/test_rules.py`. — **Done** (e62de54): check_combo casts spell pieces from hand when affordable (counterable like any spell); pure combo spells aren't cast as filler; Crackle with Power added as a Sanar outlet. 4 new tests. Smoke: Sanar 2.8% -> 13.2%, Aziza/Codie unchanged within noise.
- [x] **0.2 Imprint.** Store the imprinted card on the Isochron Scepter `Perm` (CR 406.6, 607); the Scepter + Reversal line requires the imprint, not just the card in hand. — **Done** (948cca1): Scepter imprints an instant (MV<=2) as it enters, preferring its combo partner; the Reversal combo fires only with the imprint, 3+ nonland mana and a finisher (storm/X spell in hand, a spell-trigger drain, pingers + Treasure maker, or a draw-per-spell engine with a finisher in library). Scepter is held until Reversal is in hand. 6 new tests. Smoke: Sanar 13.2% -> 5.6%, since 0.1 had let Scepter + Reversal win unconditionally.
- [x] **0.3 Aura combo targets.** `aura_target`/`attach`: an aura that is a combo piece goes on the creature that completes the combo (Freed from the Real / Pemmin's Aura on Sanar). Check why these were never cast in Sanar traces. — **Done** (66a0700): Root cause: the auras were cast but never logged, and the combo check accepted Freed/Pemmin's on any creature. Auras now record what they enchant and are logged; a combo Aura goes on its combo's first piece (Sanar, Bloom Tender) and is held until that creature is out; the combo only counts if it's attached there; Auras whose host leaves go to the graveyard (CR 303.4c, 704.5m). 4 new tests. Smoke: Sanar 4.2%, others unchanged within noise.
- [x] **0.4 Tag Sanar's blank spells.** Brain Freeze (storm mill), Frantic Search (net mana), Hex Magic, Crackle with Power (X burn, infinite-mana outlet), Nexus of Fate (extra turn). — **Done** (8b50d03): generic tags in `engine/cards.py` for look-at-the-top-into-hand (`draw_now`), instant/sorcery Treasure makers (`treasure_now`), restricted tutors (`tutor` + `tutor_filter`) and unconditional cost reducers (`cost_less`); `cost()` applies the reducers (CR 601.2f), `tutor(P, src)` honours the type/mana-value limit (CR 701.23), and `special_effect`/`special_score` cover Sanar's five spells plus Nexus-style shuffle-back (CR 614.1a) and extra turns (CR 500.7). 6 new tests, 36 pass. Verified at 100 series per category against eb79181, ~4,000 games per deck, game win: **Sanar 3.9% -> 10.6%**, Aziza 44.9% -> 45.7%, Bria 13.6% -> 13.3%, Codie 19.1% -> 18.4%. The handoff's "Codie and Aziza dropped 6–7 points" was smoke noise: run-to-run spread on an unchanged engine is about 1.1 points at this sample size, and isolating each half on Codie accounts for at most 0.8 of it (whole `tutor()` rewrite 17.6% with the pre-0.4 version, type/mana-value filter alone 18.3% = no effect, cost reducers off 18.8%, specials off 18.4%). Only Sanar moves outside noise.
    - **Known over-credit, left alone on purpose:** Hex Magic is modelled as "draw a hand the size of the current one and keep the original cards in hand", so the player holds 2N cards with no expiry instead of N in hand plus N playable until the end of the following turn. Worth about 0.9 points of Sanar's game win (9.4% with the card disabled). Modelling the expiry properly needs `cast()` at `engine/engine.py:958` to survive a card leaving the hand mid-turn — it does `P.hand.remove(c)` on a plan built earlier in `my_main`, which raises `ValueError` as soon as anything unexpected moves a card. Fix that staleness first; every future "card leaves hand unexpectedly" feature will hit it.
    - **Also worth knowing for 0.5:** the per-special contributions to Sanar are Brain Freeze 0.5, Crackle with Power 0.8, Hex Magic 0.9, Frantic Search ~0, so the rest of the 6.7-point gain is the generic tags, not the specials.
- [ ] **0.5 Top blank staples.** Work down the "most-played blank cards" list: Nature's Lore, Three Visits (forest fetch ramp), Deflecting Swat, Victimize, Wild Growth, Rhythm of the Wild, Panharmonicon, Seedborn Muse, Sun Titan, Hardened Scales, Phyrexian Metamorph, then the next 30 from a fresh coverage run.
    - **Batch 1 (ramp, counters, ETB doubling), done:** three causes, not eleven. Nature's Lore and Three Visits read as blank because the ramp regex insisted on the word "land" while both name their basic type ("a Forest card"); widened it to accept any named basic type and keep a `ramp_col` so a fetched Forest only provides green. That fix generalises past these two cards: 9 cards gain ramp and 7 already-ramped ones become correctly colour-locked (Aerial Surveyor, Binding the Old Gods, Claim Jumper, Hunting Wilds, Keeper of the Accord, Knight of the White Orchid, Loyal Warhound), verified card-by-card against the old tagger with zero losses. Deflecting Swat is a redirect rather than a counter, so the counter regex misses it; tagged as a free counterspell (every deck that can cast it controls a commander, so the free clause always applies). Panharmonicon doubles ETB triggers of artifacts and creatures entering, per CR 706.2a, and is valued by how many ETB permanents you control so the pilot actually casts it. 7 new tests, 43 pass. 100 series per category: Codie 18.4 -> 17.0, Aziza 45.7 -> 45.1, Bria 13.3 -> 13.4, Sanar 10.6 -> 9.5 (game win). All inside the ~1.1-point run-to-run spread except Codie, which sits at about the edge of it; the direction is right (opponents got ramp and a free counterspell) and no category moved past 3 points.
    - **Left for batch 2:** Victimize and Sun Titan (graveyard recursion needs an engine model for returning cards from the graveyard, which nothing has yet), Wild Growth and Rhythm of the Wild (both are stat/keyword permanents the value function can't see), Seedborn Muse (untap in other players' untap steps — the engine untaps everything at the start of a turn, so it is already nearly a no-op), Hardened Scales (needs +1/+1 counter replacement effects, CR 122.1c, which no card implements), Phyrexian Metamorph (copy an artifact or creature).
- [ ] **0.6 Basic equipment.** Equip as "attach to best creature for its cost, grant the static bonus/keywords"; Swords' hit triggers as an attack trigger.
- [ ] **0.7 Fairer removal targets.** Opponent AI stops treating every commander as the top target (Sanar was removed 4,355 times in about 4,300 games).
- [ ] **0.8 Coverage script.** Turn the audit's coverage measurement into `tools/coverage.py` (blank share overall, by type, per deck, top blank cards) so every change reports its effect.
- [ ] **Gate:** rerun Sanar, Bria, Codie at 100 series; numbers are plausible and every remaining blank in those lists is listed.

### Phase 1 — validate

- [ ] **1.1** Ask Playgroup.gg for access to commander win-rate data (no API found).
- [ ] **1.2** Calibration harness: simulate a fixed set of real commanders against each other; report rank correlation with real-game win rates.
- [ ] **1.3** One AI for all seats: your deck plays with the same AI as opponents (pilot files become hints both sides can use), or opponents get generated pilots.
- [ ] **1.4** Accuracy score printed with every engine change and stored in `results/`.
- [ ] **Gate:** the sim's commander ranking tracks the real-game ranking.

### Phase 2 — rules core

- [ ] **2.1** Decide build versus adopt (XMage, MIT; Forge, GPL-3.0). Spike: run 100 headless XMage Commander games and time them.
- [ ] **2.2** Stack and priority (CR 117, 405, 608).
- [ ] **2.3** Tokens (incl. Treasure, Food, Clue) and lands as real permanents (CR 111.10).
- [ ] **2.4** Generic activated, triggered and replacement abilities (CR 602, 603, 614).
- [ ] **2.5** Rules test suite in the hundreds.
- [ ] **Gate:** accuracy holds or improves, and blank cards are rare.

### Phase 3 — product

- [ ] **3.1** Written permission or a licence from Wizards, or commit to a free, ad/sponsor-funded model.
- [ ] **3.2** Card data from a source you may use commercially.
- [ ] **3.3** User-supplied opponent decks.
- [ ] **3.4** Hosted runner and reports.

## Sources

- Comprehensive Rules effective 2026-09-25, through the mtg-rules server (rules cited inline)
- itskstevens/mtg-gauntlet at commit 4f5e0b3: `engine/`, `opponents/`, `results/`, measured 2026-10-05
- [Wizards of the Coast Fan Content Policy](https://company.wizards.com/en/legal/fancontentpolicy)
- [Scryfall API documentation and usage guidelines](https://scryfall.com/docs/api)
- [Forge repository (GPL-3.0)](https://github.com/Card-Forge/forge)
- [XMage repository (MIT)](https://github.com/magefree/mage)
- [Playgroup.gg commander tier list, last 365 days](https://playgroup.gg/commanders/tier-list/365-days)
