#!/usr/bin/env python
"""Blank-card coverage for the gauntlet engine (roadmap 0.8).

A nonland, noncreature card is blank when the tagger (engine/cards.summarize)
gives it no role and no engine code mentions it by name; creatures fight even
with no tag and lands have a mana role (engine-audit.md, "Card coverage").
Prints blank share overall, by card type, per deck, and the most-played blank
cards so every engine change can report its effect.

Run: python3 tools/coverage.py [DECK ... | --all]
"""
import argparse, collections, glob, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import cards as CD


def engine_named():
    """Card names hardcoded anywhere in engine code, so they are covered by name."""
    db = os.path.join(ROOT, 'cards')
    pool = ''
    for d, _, fs in os.walk(os.path.join(ROOT, 'engine')):
        for f in fs:
            if f.endswith('.py'):
                pool += open(os.path.join(d, f)).read() + '\n'
    return {lit for lit in re.findall(r"['\"]([A-Za-z][^'\"\n]{2,60})['\"]", pool)
            if os.path.exists(os.path.join(db, CD.slug(lit) + '.txt'))}


def blank(c, named):
    return c.name not in named and not c.is_land and not c.is_creature and not CD.summarize(c)


def main():
    ap = argparse.ArgumentParser(description='blank-card coverage')
    ap.add_argument('decks', nargs='*', help='deck folder names; default: every decks/*/list.txt')
    ap.add_argument('--top', type=int, default=15, help='how many top blank cards to list (default 15)')
    args = ap.parse_args()
    lis = sorted(glob.glob(os.path.join(ROOT, 'decks', '*', 'list.txt')))
    lis = [f for f in lis if not os.path.basename(os.path.dirname(f)).startswith('.')]
    if args.decks:
        keep = {os.path.join(ROOT, 'decks', d, 'list.txt') for d in args.decks}
        lis = [f for f in lis if f in keep]
    named = engine_named()

    type_of = [('artifact', lambda c: c.is_artifact), ('enchantment', lambda c: c.is_enchantment),
               ('instant', lambda c: c.is_instant), ('sorcery', lambda c: c.is_sorcery),
               ('planeswalker', lambda c: c.is_planeswalker)]
    per_type = collections.defaultdict(lambda: [0, 0])   # [blank, total]
    per_deck = []                                        # (name, blank, total)
    top = collections.Counter()                          # blank card -> slots
    tot_b = tot_t = 0
    for f in lis:
        deck = os.path.basename(os.path.dirname(f))
        db = dt = 0
        for line in open(f):
            line = line.strip()
            if not line: continue
            try:
                _, name = line.split(None, 1)
                c = CD.get(name)
            except Exception:
                continue
            if c.is_land or c.is_creature: continue
            dt += 1
            for key, pred in type_of:
                if pred(c):
                    per_type[key][1] += 1
                    if blank(c, named):
                        per_type[key][0] += 1
            if blank(c, named):
                db += 1; top[name] += 1
        per_deck.append((deck, db, dt)); tot_b += db; tot_t += dt

    print(f'engine-named cards: {len(named)}')
    print(f'overall blank share: {tot_b}/{tot_t} slots ({100 * tot_b / max(1, tot_t):.1f}%) over {len(per_deck)} decks')
    print('\nby card type (blank/total):')
    for key, _ in type_of:
        b, t = per_type[key]
        print(f'  {key:<13} {b}/{t}  ({100 * b / max(1, t):.1f}%)')
    print('\nper deck (nonland, noncreature slots):')
    for d, b, t in sorted(per_deck, key=lambda x: -x[1]):
        print(f'  {d:<28} {b}/{t}  ({100 * b / max(1, t):.1f}%)')
    print('\ntop blank cards by slots played:')
    for name, n in top.most_common(args.top):
        print(f'  {name:<32} {n}')

if __name__ == '__main__':
    main()