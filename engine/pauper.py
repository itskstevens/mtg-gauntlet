"""1v1 Pauper gauntlet: best-of-3 matches (no sideboarding) against current metagame decks.

Opponents live in opponents-pauper/<key>/ (list.txt main deck, meta.yaml: name, share, source, fetched).
gauntlets-pauper.yaml lists them with their metagame share, which weights the overall win rate.
"""
import os, random, json, gzip, collections, time, datetime
import yaml
from . import engine as E
from .runner import load_list, p

def load_main(path):
    """Main deck only from a list with an optional 'SIDEBOARD:' section."""
    out = []
    for l in open(path):
        l = l.strip()
        if l.upper().startswith('SIDEBOARD'): break
        if not l or l.startswith('#'): continue
        q, n = l.split(' ', 1); out += [n] * int(q)
    return out

def cfg(): return yaml.safe_load(open(p('gauntlets-pauper.yaml')))

def opp_list(key): return load_main(p('opponents-pauper', key, 'list.txt'))

def play_match(my_deck, opp_deck, opp_label, seed, max_rounds=20, log=False):
    """Best of 3. Returns dict with per-game winners and whether we won the match."""
    rng = random.Random(seed)
    games = []; wins = 0; losses = 0; on_play = rng.choice([0, 1])
    while wins < 2 and losses < 2 and len(games) < 3:
        g = E.Game([('You', my_deck, True, 'me', 0, None), (opp_label, opp_deck, False, opp_label, 0, None)],
                   rng, log=log, max_rounds=max_rounds, fmt='constructed', on_play=on_play)
        w = g.play()
        me = w is not None and w.is_me
        games.append({'win': me, 'on_play': on_play == 0, 'turns': g.round, 'draw': w is None,
                      'log': g.events if log else None,
                      'cast': [c for c in g.players[0].cast_log] if g.players and g.players[0].is_me else []})
        if me: wins += 1
        else: losses += 1
        on_play = 1 if me else 0   # loser chooses to play first
    return {'opp': opp_label, 'games': games, 'won': wins >= 2}

def _job(a):
    my, key, label, seed, mr = a
    return key, play_match(my, opp_list(key), label, seed, mr)

def run(deck_list_path, n_matches=50, jobs=2, seed_base=500):
    c = cfg(); my = load_main(deck_list_path)
    tasks = []
    for i, o in enumerate(c['opponents']):
        for k in range(n_matches):
            tasks.append((my, o['key'], o['name'], seed_base + i * 10007 + k, c.get('max_rounds', 20)))
    t0 = time.time()
    if jobs > 1:
        import multiprocessing as mp
        with mp.Pool(jobs) as pool: res = pool.map(_job, tasks, chunksize=8)
    else: res = [_job(t) for t in tasks]
    by = collections.defaultdict(list)
    for k, m in res: by[k].append(m)
    out = {'deck': deck_list_path, 'date': datetime.date.today().isoformat(), 'secs': round(time.time() - t0), 'opponents': []}
    tot_w = 0; tot_share = 0
    for o in c['opponents']:
        ms = by[o['key']]
        mw = sum(m['won'] for m in ms) / len(ms)
        gs = [g for m in ms for g in m['games']]
        gw = sum(g['win'] for g in gs) / len(gs)
        play = [g for g in gs if g['on_play']]; draw = [g for g in gs if not g['on_play']]
        out['opponents'].append({'key': o['key'], 'name': o['name'], 'share': o['share'], 'matches': len(ms),
                                 'match_win': round(mw, 3), 'game_win': round(gw, 3),
                                 'on_play': round(sum(g['win'] for g in play) / max(1, len(play)), 3),
                                 'on_draw': round(sum(g['win'] for g in draw) / max(1, len(draw)), 3),
                                 'avg_turns': round(sum(g['turns'] for g in gs) / len(gs), 1),
                                 'timeouts': sum(g['draw'] for g in gs)})
        tot_w += mw * o['share']; tot_share += o['share']
    out['weighted_match_win'] = round(tot_w / tot_share, 3)
    out['plain_match_win'] = round(sum(o['match_win'] for o in out['opponents']) / len(out['opponents']), 3)
    return out
