"""Run gauntlets (best-of-3 pod series per category), analyze results, build the report data."""
import os, random, json, gzip, collections, statistics as st, time, datetime, re
import yaml
from . import engine as E

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def p(*a): return os.path.join(ROOT, *a)

def load_list(path):
    out = []
    for l in open(path):
        l = l.strip()
        if not l or l.startswith('#'): continue
        q, n = l.split(' ', 1)
        out += [n] * int(q)
    return out

def load_cfg(): return yaml.safe_load(open(p(os.environ.get('GAUNTLET_CFG', 'gauntlets.yaml'))))

def load_pilot(slug):
    f = p('pilots', slug + '.yaml')
    return yaml.safe_load(open(f)) if os.path.exists(f) else {}

def opp_meta(key): return yaml.safe_load(open(p('opponents', key, 'meta.yaml')))

def category_decks(cfg, category):
    """Every deck a category can field, as [{key, archetype}]. Pooled categories use the deck key as its archetype
    label so per-opponent results stay separate."""
    c = cfg['categories'][category]
    if isinstance(c, dict): return [dict(key=k, archetype=k) for k in c['pool']]
    return c

def pick_opps(cfg, category, rng):
    """The opponents for one series: a fixed category returns its decks; a pooled one samples `pod` of them."""
    c = cfg['categories'][category]
    if isinstance(c, dict):
        return [dict(key=k, archetype=k) for k in rng.sample(c['pool'], min(c.get('pod', 3), len(c['pool'])))]
    return c

def specs_for(cfg, category, my_deck, pilot, rng, brackets, opps=None):
    sp = [('You', my_deck, True, 'me', 0, pilot)]
    for d, b in zip(opps or cfg['categories'][category], brackets):
        m = opp_meta(d['key'])
        sp.append((f"{m['commander'].split(',')[0].split(' // ')[0]} ({d['archetype']}, B{b})", load_list(p('opponents', d['key'], f'b{b}.txt')),
                   False, d['archetype'], b, None))
    return sp

# ------------------------------------------------------------------ play
def run_category(args):
    category, deck_path, pilot, n_series, seed, max_rounds, logged = args
    cfg = load_cfg(); my_deck = load_list(deck_path)
    rng = random.Random(seed)
    games, series_res, samples = [], [], []
    br_choices = cfg['defaults'].get('brackets', [3, 4])
    for sid in range(n_series):
        opps = pick_opps(cfg, category, rng)
        br = [rng.choice(br_choices) for _ in opps]
        w = l = 0; gno = 0
        while w < 2 and l < 2:
            gno += 1
            sp = specs_for(cfg, category, my_deck, pilot, rng, br, opps)
            log = sid < logged
            g = E.Game(sp, rng, log=log, max_rounds=max_rounds)
            winner = g.play()
            me = next(x for x in g.players if x.is_me)
            won = winner is me
            w += won; l += (not won)
            order = [P for P, *_ in g.elim]
            place = 1 if won else (4 - order.index(me) if me in order else 2)
            rec = dict(series=sid, game=gno, brackets=br, won=won, draw=winner is None, rounds=g.round, place=place, seat=me.seat,
                       winner=(winner.group if winner else 'draw'),
                       my_death=(me.died[1], next((x.group for x in g.players if x.label == me.died[2]), None), me.died[0]) if me.died else None,
                       my_stats={k: v for k, v in me.stats.items() if not k.startswith('jin_')},
                       my_cast=sorted(set(n for r, n in me.cast_log)), opp=[])
            for P in g.players:
                if P.is_me: continue
                rec['opp'].append(dict(arch=P.group, bracket=P.bracket, won=winner is P, died=P.died,
                                       killed_by_me=bool(P.died and P.died[2] == me.label),
                                       cast=sorted(set(n for r, n in P.cast_log)), combo_win=P.stats['combo_win']))
            rec['my_kills'] = [P.died[1] for P in g.players if not P.is_me and P.died and P.died[2] == me.label]
            # simulator health signals
            rec['health'] = dict(attacks_at_me=sum(1 for e in g.events if ' attacks You ' in e),
                                 attacks_total=sum(1 for e in g.events if ' attacks ' in e)) if log else None
            games.append(rec)
            if log and len(samples) < 3:
                samples.append(dict(won=won, rounds=g.round, players=[x.label for x in g.players], events=g.events[:500]))
        series_res.append(dict(series=sid, brackets=br, opps=[d['key'] for d in opps], won=w >= 2, score=f'{w}-{l}'))
    return category, dict(games=games, series=series_res, samples=samples)

def run(deck_path, pilot, n_series=None, categories=None, jobs=2, seed_base=100, logged=3):
    cfg = load_cfg()
    n_series = n_series or cfg['defaults']['series']
    cats = categories or list(cfg['categories'])
    mr = cfg['defaults'].get('max_rounds', 25)
    tasks = [(c, deck_path, pilot, n_series, seed_base + i, mr, logged) for i, c in enumerate(cfg['categories']) if c in cats]
    out = {}
    if jobs > 1:
        import multiprocessing as mp
        with mp.Pool(jobs) as pool:
            for c, r in pool.imap_unordered(run_category, tasks):
                out[c] = r; print(f'  {c}: {quick(r)}', flush=True)
    else:
        for t in tasks:
            c, r = run_category(t); out[c] = r; print(f'  {c}: {quick(r)}', flush=True)
    return {c: out[c] for c in cats if c in out}

def quick(r):
    G, S = r['games'], r['series']
    return f"{len(S)} series, {len(G)} games, game win {sum(g['won'] for g in G)/len(G):.1%}, series win {sum(s['won'] for s in S)/len(S):.1%}"

def save_results(res, path):
    with gzip.open(path, 'wt') as f: json.dump(res, f)
def load_results(path):
    op = gzip.open if path.endswith('.gz') else open
    with op(path, 'rt') as f: return json.load(f)

# ------------------------------------------------------------------ analyze
CAUSE = {'death': 'Death-trigger drains', 'wurm': 'Death-trigger drains', 'spell': 'Spell-cast pings', 'storm': 'Burn spells', 'etb': 'Creature-entry drains', 'burn': 'Burn spells', 'bombardment': 'Goblin Bombardment', 'arabella': 'Attack triggers',
         'ping': 'Burn spells', 'sheoldred': 'Burn spells', 'lifegain': 'Lifegain drains', 'commander damage': 'Commander damage',
         'Test of Endurance': 'Alternate win', 'Felidar Sovereign': 'Alternate win', 'Approach of the Second Sun': 'Alternate win',
         'empty-library win': 'Alternate win', 'combo': 'Infinite combo', 'combat': 'Combat damage', 'decked': 'Decked',
         'poison': 'Poison', 'torment': 'Torment of Hailfire', 'blightfang': 'Death-trigger drains', 'drain': 'Drain spells',
         'lathril': 'Lathril activation', 'attack': 'Attack triggers', 'upkeep': 'Upkeep triggers', 'landfall': 'Landfall triggers'}
def cause(c): return CAUSE.get(c.split(':')[0], c.split(':')[0])

def analyze(res, cfg, pilot):
    groups = []
    watch = list(dict.fromkeys(list(pilot.get('priorities', {})) + pilot.get('key_cards', []) + pilot.get('engine', [])))
    for cat, d in res.items():
        G, S = d['games'], d['series']; n = len(G)
        lost = [g for g in G if not g['won']]
        deaths = collections.Counter((cause(g['my_death'][0]), g['my_death'][1]) for g in G if g['my_death'])
        kills = collections.Counter(cause(k) for g in G for k in g['my_kills'])
        avg = lambda k: round(sum(g['my_stats'].get(k, 0) for g in G) / n, 2)
        def top(prefix):
            c = collections.Counter()
            for g in G:
                for k, v in g['my_stats'].items():
                    if k.startswith(prefix): c[k[len(prefix):]] += v
            return c.most_common(4)
        opps = []
        for dk in category_decks(cfg, cat):
            arch = dk['archetype']; m = opp_meta(dk['key'])
            rows = [(g, o) for g in G for o in g['opp'] if o['arch'] == arch]
            if not rows: continue
            hk = collections.Counter((g['my_death'][0].replace('combo: ', '') if g['my_death'][0].startswith('combo') else cause(g['my_death'][0]))
                                     for g, o in rows if g['my_death'] and g['my_death'][1] == arch)
            lw = [o for g, o in rows if not g['won']]; ww = [o for g, o in rows if g['won']]
            cl = collections.Counter(c for o in lw for c in o['cast']); cw = collections.Counter(c for o in ww for c in o['cast'])
            lift = sorted(((cl[c] / max(1, len(lw)) - cw[c] / max(1, len(ww)), c) for c in cl if cl[c] >= 6), reverse=True)
            mv = lambda b: round(100 * st.mean([g['won'] for g, o in rows if o['bracket'] == b] or [0]), 1)
            opps.append(dict(cmd=m['commander'], arch=m.get('tag', arch) if arch == dk['key'] else arch, key=dk['key'], games=len(rows), link=m['source']['b3'].rsplit('/', 1)[0],
                             fetched=m.get('fetched'),
                             win_share=round(100 * st.mean(o['won'] for g, o in rows), 1),
                             killed_me=round(100 * sum(1 for g, o in rows if g['my_death'] and g['my_death'][1] == arch) / len(rows), 1),
                             i_killed=round(100 * st.mean(o['killed_by_me'] for g, o in rows), 1),
                             my_vs_b3=mv(3), my_vs_b4=mv(4), how=hk.most_common(4),
                             threats=[c for v, c in lift if v >= 0.04][:5]))
        impact = []
        for c in watch:
            w = [g['won'] for g in G if c in g['my_cast']]; nw = [g['won'] for g in G if c not in g['my_cast']]
            if len(w) >= 20: impact.append([c, len(w), round(100 * st.mean(w)), round(100 * st.mean(nw)) if nw else 0])
        impact.sort(key=lambda r: -(r[2] - r[3]))
        health = [g['health'] for g in G if g.get('health')]
        att = sum(h['attacks_at_me'] for h in health); tot = sum(h['attacks_total'] for h in health)
        seat = collections.defaultdict(list)
        for g in G: seat[g['seat']].append(g['won'])
        opps.sort(key=lambda o: -o['killed_me'])
        groups.append(dict(name=cat, slug=re.sub(r'[^a-z]+', '-', cat.lower()).strip('-'), games=n, series=len(S),
            series_win=round(100 * st.mean(s['won'] for s in S), 1), game_win=round(100 * st.mean(g['won'] for g in G), 1),
            avg_place=round(st.mean(g['place'] for g in G), 2), avg_rounds=round(st.mean(g['rounds'] for g in G), 1),
            place={str(k): v for k, v in collections.Counter(g['place'] for g in G).items()}, draws=sum(g['draw'] for g in G),
            first_out=round(100 * sum(1 for g in G if g['place'] == 4) / n, 1),
            deaths=[[c, a, k] for (c, a), k in deaths.most_common(7)], losses=len(lost), kills=kills.most_common(5),
            stats=dict(cmd=avg('cmd_triggers'), edict=avg('edict_commander'), pact=avg('edict_pact'), poison=avg('poison_dealt'),
                       countered=avg('countered'), wipes=avg('wipes_suffered'), removal=avg('removal_taken'), dmg=avg('dmg_dealt')),
            countered=top('countered_card_'), removed=top('removed_'), wiped=top('wiped_by_'),
            impact=impact[:8], opps=opps, by_seat={k: round(100 * st.mean(v), 1) for k, v in sorted(seat.items())},
            attack_share=round(100 * att / tot, 1) if tot else None,
            samples=[dict(won=sm['won'], rounds=sm['rounds'], players=[x.split(' (')[0] for x in sm['players']], lines=key_lines(sm['events'], pilot))
                     for sm in d['samples']]))
    return groups

def key_lines(ev, pilot):
    keys = set(pilot.get('key_cards', [])) | {pilot.get('commander', '')}
    out = []
    for e in ev:
        if '   [' in e: continue
        mine = e.startswith(e.split(' ')[0] + ' You ')
        if any(k in e for k in ('WIPE', 'OVERRUN', 'INFECT ALPHA', 'counters', 'breaks', 'eliminated', 'wins via', 'Golgari Charm', 'Bojuka', 'protects', 'Lathril drains', 'Jin-Gitaxias')) \
           or (mine and ' casts ' in e and any(k and k in e for k in keys)):
            e = re.sub(r' \(([^()]+), B\d\)', '', e).replace("You's", 'your')
            out.append(e)
    return out[:28]

def summary_md(deck_name, groups, meta):
    L = [f'# {deck_name} gauntlet ({meta["date"]})', '', f'{meta["series_total"]} best-of-3 series, {meta["games_total"]} games, {meta["series_per_cat"]} series per category.', '',
         '| Category | Games won | Series won | Avg place | Rounds | First out |', '|---|---|---|---|---|---|']
    for g in groups:
        L.append(f"| {g['name']} | {g['game_win']}% | {g['series_win']}% | {g['avg_place']} | {g['avg_rounds']} | {g['first_out']}% |")
    L += ['', 'Fair share in a 4-player pod: 25% of games, about 16% of best-of-3 series.', '']
    for g in groups:
        L += [f"## {g['name']}", '', 'How you lost: ' + '; '.join(f'{c} by {a} ({k})' for c, a, k in g['deaths'][:5]),
              'How you won kills: ' + '; '.join(f'{c} ({k})' for c, k in g['kills']),
              'Opponents: ' + '; '.join(f"{o['cmd']} won {o['win_share']}%, knocked you out {o['killed_me']}%" for o in g['opps']),
              f"Attacks aimed at you: {g['attack_share']}% (fair ~33%). Knocked out first: {g['first_out']}% (fair 25%).", '']
    return '\n'.join(L)
