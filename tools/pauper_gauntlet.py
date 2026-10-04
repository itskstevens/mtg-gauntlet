#!/usr/bin/env python3
"""Pauper gauntlet: Kevin's 60-card decks vs the current Pauper metagame (1v1, best-of-3, no sideboarding).

  python3 tools/pauper_gauntlet.py run [DECK ...] [--matches 200] [--jobs 2] [--house] [--tag TAG]
      DECK = a key in pauper/decks.json (izzet, golgari, ...) or a path to a list. No DECK = all of them.
      --house also plays every deck against Kevin's other Pauper decks (kitchen-table matchups).
  python3 tools/pauper_gauntlet.py smoke DECK          # one logged match vs each meta deck, prints the first game
  python3 tools/pauper_gauntlet.py meta                # list the opponent decks, shares and fetch dates

Results: results-pauper/<date>[-tag]/results.json (+ summary.md). Opponents: opponents-pauper/, gauntlets-pauper.yaml.
Card scripts are fetched from Forge on first use (python3 gauntlet.py check-style), cached in cards/.
"""
import argparse, datetime, glob, json, os, sys, random

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine import pauper as PP
import yaml

def deck_path(k):
    if os.path.exists(k): return k
    return os.path.join(ROOT, 'pauper', 'lists', k + '.txt')

def all_keys(): return [os.path.basename(f)[:-4] for f in sorted(glob.glob(os.path.join(ROOT, 'pauper', 'lists', '*.txt')))]

def ensure_cards(paths):
    import gauntlet
    names = set()
    for f in paths: names |= set(PP.load_main(f))
    miss = [n for n, s in gauntlet.fetch_cards(names).items() if s == 'missing']
    if miss: sys.exit('No Forge script for: ' + ', '.join(miss) + ' (add a synthetic script in cards/ or swap the card)')

def house(keys, n, jobs):
    """Every pair of Kevin's decks, n best-of-3 matches each (row deck's match win rate)."""
    tasks = [(a, b, 9000 + i * 977 + j * 31 + k) for i, a in enumerate(keys) for j, b in enumerate(keys) if a != b for k in range(n)]
    def job(t):
        a, b, seed = t
        return a, b, PP.play_match(PP.load_main(deck_path(a)), PP.load_main(deck_path(b)), b, seed)['won']
    if jobs > 1:
        import multiprocessing as mp
        with mp.Pool(jobs) as pool: res = pool.map(_house_job, tasks, chunksize=16)
    else: res = [_house_job(t) for t in tasks]
    m = {}
    for a, b, w in res: m.setdefault(a, {}).setdefault(b, []).append(w)
    return {a: {b: round(sum(v) / len(v), 3) for b, v in row.items()} for a, row in m.items()}

def _house_job(t):
    a, b, seed = t
    return a, b, PP.play_match(PP.load_main(deck_path(a)), PP.load_main(deck_path(b)), b, seed)['won']

def cmd_run(a):
    keys = a.decks or all_keys()
    paths = [deck_path(k) for k in keys]
    c = PP.cfg()
    ensure_cards(paths + [os.path.join(ROOT, 'opponents-pauper', o['key'], 'list.txt') for o in c['opponents']])
    names = json.load(open(os.path.join(ROOT, 'pauper', 'decks.json'))) if os.path.exists(os.path.join(ROOT, 'pauper', 'decks.json')) else {}
    out = {'date': datetime.date.today().isoformat(), 'matches': a.matches, 'decks': {}, 'opponents': c['opponents']}
    for k, pth in zip(keys, paths):
        r = PP.run(pth, n_matches=a.matches, jobs=a.jobs)
        r['name'] = names.get(k, {}).get('name', k)
        out['decks'][k] = r
        print(f"{r['name']:<24} meta-weighted match win {r['weighted_match_win']:.0%}  ({r['secs']}s)")
    if a.house and len(keys) > 1:
        out['house'] = house(keys, max(20, a.matches // 4), a.jobs)
    d = os.path.join(ROOT, 'results-pauper', out['date'] + (f'-{a.tag}' if a.tag else ''))
    os.makedirs(d, exist_ok=True)
    json.dump(out, open(os.path.join(d, 'results.json'), 'w'), indent=1)
    md = [f"# Pauper gauntlet {out['date']}", '', f"{a.matches} best-of-3 matches per opponent, no sideboarding. Meta shares from MTGTop8.", '',
          '| Deck | Meta-weighted match win | ' + ' | '.join(o['name'] for o in c['opponents']) + ' |',
          '|---|---|' + '---|' * len(c['opponents'])]
    for k, r in out['decks'].items():
        md.append(f"| {r['name']} | {r['weighted_match_win']:.0%} | " + ' | '.join(f"{o['match_win']:.0%}" for o in r['opponents']) + ' |')
    open(os.path.join(d, 'summary.md'), 'w').write('\n'.join(md) + '\n')
    print('Saved', os.path.relpath(d, ROOT))

def cmd_smoke(a):
    my = PP.load_main(deck_path(a.deck))
    for i, o in enumerate(PP.cfg()['opponents']):
        m = PP.play_match(my, PP.opp_list(o['key']), o['name'], 1000 + i, log=(i == 0))
        print(f"{o['name']:<26} {'won' if m['won'] else 'lost'}  games " + ' '.join(('W' if g['win'] else 'L') + str(g['turns']) for g in m['games']))
        if i == 0: print('\n'.join(m['games'][0]['log'][:80]))

def cmd_meta(a):
    for o in PP.cfg()['opponents']:
        m = yaml.safe_load(open(os.path.join(ROOT, 'opponents-pauper', o['key'], 'meta.yaml')))
        print(f"{o['share']:>3}%  {o['name']:<26} fetched {m['fetched']}  {m['source']}")

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(required=True)
    x = sp.add_parser('run'); x.add_argument('decks', nargs='*'); x.add_argument('--matches', type=int, default=200)
    x.add_argument('--jobs', type=int, default=2); x.add_argument('--house', action='store_true'); x.add_argument('--tag'); x.set_defaults(fn=cmd_run)
    x = sp.add_parser('smoke'); x.add_argument('deck'); x.set_defaults(fn=cmd_smoke)
    x = sp.add_parser('meta'); x.set_defaults(fn=cmd_meta)
    a = ap.parse_args(); a.fn(a)

if __name__ == '__main__': main()
