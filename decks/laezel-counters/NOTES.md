# Lae'zel counters army (bracket 4, no budget) — built 2026-10-04

Commanders: Lae'zel, Vlaakith's Champion + Guild Artisan (Background).
Plan: go wide with creatures and tokens; Lae'zel adds +1 to every counter placement, so Cathars' Crusade,
Felidar Retreat, Luminarch Aspirant, Ajani Steadfast and Basri Ket snowball. Win by a wide pumped alpha strike, or
Heliod, Sun-Crowned + Walking Ballista (infinite damage).

Gauntlet 2026-10-04 on the rules-audited engine (1,800 LGS tables): 35.5% games, 29.1% series (first run before the audit: 40.3%). Report: results/laezel-counters/report-2026-10-04.html

Engine support added 2026-10-04 (engine/counters.py) for what this list needed:
- Background as a second commander (Guild Artisan) — not supported yet
- Lae'zel's +1 counter replacement — not modelled
- planeswalker loyalty abilities — not modelled (Ajanis, Basri, Elspeths, Gideon, Wandering Emperor)
- untagged cards the sim plays as blanks: Cathars' Crusade, The Ozolith, Heliod (and the Ballista combo),
  Luminarch Aspirant, Mikaeus, Steel Overseer, Constable, Ainok Bond-Kin, Inspiring Paladin, Abzan Falconer,
  Exemplar of Light, Laelia, Stonecoil, Grateful Apparition, Mentor of the Meek, Welcoming Vampire, protection spells
- a pilot file (none yet)

## Flex to bracket 3 (decks/laezel-counters-b3)
Same 96 cards; swap 4 slots. Bracket 3 keeps 3 Game Changers: Smothering Tithe, Teferi's Protection, The One Ring.

| Bracket 4 (in)          | Bracket 3 (swap to)  | Why |
|-------------------------|----------------------|-----|
| Enlightened Tutor (GC)  | Idyllic Tutor        | still finds Cathars' Crusade / Felidar Retreat / Anointed Procession |
| Jeska's Will (GC)       | Inspiring Overseer   | card draw on a 2-power body (Welcoming Vampire, Mentor) |
| Ancient Tomb (GC)       | Plains               | |
| Heliod, Sun-Crowned     | Ajani's Pridemate    | removes the Heliod + Walking Ballista two-card infinite |

Game Changers in the bracket 4 list (6): Smothering Tithe, Enlightened Tutor, Teferi's Protection, Jeska's Will,
Ancient Tomb, The One Ring. (Esper Sentinel, Trouble in Pairs and Urza's Saga came off the list in Oct 2025.)
