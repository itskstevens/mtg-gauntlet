#!/usr/bin/env python3
"""mtg-gauntlet: test a Commander deck against EDHREC archetype decks in simulated 4-player best-of-3 series.

  python3 gauntlet.py check     <deck>                 validate list, fetch missing card data, check pilot
  python3 gauntlet.py init-pilot <deck>                write a starter pilots/<deck>.yaml from the list
  python3 gauntlet.py stale                            list opponent decklists due for a refresh
  python3 gauntlet.py smoke     <deck>                 a few logged games per category + simulator health checks
  python3 gauntlet.py run       <deck> [--series N] [--categories "A,B"] [--tag NAME]
  python3 gauntlet.py variants  <deck> --swap "Out->In" [--swap ...] [--series N]
  python3 gauntlet.py report    <deck> [--run DIR] [--insights FILE]

<deck> is a folder name under decks/ (decks/<deck>/list.txt, commander on the first line).
"""
import os, sys, json, argparse, datetime, re, glob, urllib.request, concurrent.futures as cf, signal, random, collections
import yaml
from engine import cards as CD, engine as E, runner as R

ROOT = os.path.dirname(os.path.abspath(__file__))
FORGE = 'https://raw.githubusercontent.com/Card-Forge/forge/master/forge-gui/res/cardsfolder/'
TODAY = datetime.date.today().isoformat()

def deck_path(deck): return os.path.join(ROOT, 'decks', deck, 'list.txt')

# ------------------------------------------------------------------ card data
def fetch_cards(names):
    dfc = json.load(open(os.path.join(ROOT, 'cards', 'dfc_map.json')))
    def get(n):
        path = os.path.join(CD.FORGE_DIR, CD.slug(n) + '.txt')
        if os.path.exists(path): return n, 'cached'
        tries = [CD.slug(n)] + ([CD.slug(n) + '_' + CD.slug(dfc[n])] if n in dfc else [])
        for s in tries:
            try:
                data = urllib.request.urlopen(FORGE + s[0] + '/' + s + '.txt', timeout=20).read().decode()
                open(path, 'w').write(data); return n, 'fetched'
            except Exception: pass
        return n, 'missing'
    with cf.ThreadPoolExecutor(16) as ex: res = dict(ex.map(get, sorted(set(names))))
    # prepare creatures copy their spell's face from another card: make sure that card is cached too
    extra = set()
    for n, st in res.items():
        path = os.path.join(CD.FORGE_DIR, CD.slug(n) + '.txt')
        if st != 'missing' and os.path.exists(path):
            m = re.search(r'CopyFaceFrom:(.+)', open(path).read())
            if m and not os.path.exists(os.path.join(CD.FORGE_DIR, CD.slug(m.group(1).strip()) + '.txt')): extra.add(m.group(1).strip())
    if extra:
        with cf.ThreadPoolExecutor(16) as ex: res.update(dict(ex.map(get, sorted(extra))))
    return res

def all_deck_names():
    names = set()
    for f in glob.glob(os.path.join(ROOT, 'decks', '*', 'list.txt')) + glob.glob(os.path.join(ROOT, 'decks', '*', 'variants', '*.txt')) \
             + glob.glob(os.path.join(ROOT, 'opponents', '*', 'b*.txt')):
        names |= set(R.load_list(f))
    return names

def cmd_check(a):
    lst = R.load_list(deck_path(a.deck))
    print(f'{a.deck}: {len(lst)} cards, commander {lst[0]}')
    if len(lst) != 100: print(f'  WARNING: list has {len(lst)} cards, expected 100')
    res = fetch_cards(set(lst) | all_deck_names())
    miss = [n for n, s in res.items() if s == 'missing']
    print(f"  card data: {sum(s == 'cached' for s in res.values())} cached, {sum(s == 'fetched' for s in res.values())} fetched, {len(miss)} missing")
    if miss:
        print('  MISSING (usually double-faced cards; add "front": "back face name" to cards/dfc_map.json and re-run):')
        for n in miss: print('   -', n)
    for n in sorted(set(lst)):
        try: CD.get(n)
        except Exception as e: print('  PARSE ERROR', n, e)
    pil = os.path.join(ROOT, 'pilots', a.deck + '.yaml')
    print('  pilot:', 'found' if os.path.exists(pil) else 'MISSING (run init-pilot, then tune it)')
    if os.path.exists(pil):
        P = yaml.safe_load(open(pil)); listed = set(lst)
        for k in ('engine', 'keep_home', 'tutor_targets', 'key_cards'):
            bad = [n for n in P.get(k, []) if n not in listed]
            if bad: print(f'  pilot {k} names not in list: {bad}')
        bad = [n for n in P.get('priorities', {}) if n not in listed]
        if bad: print(f'  pilot priorities names not in list: {bad}')

def cmd_init_pilot(a):
    lst = R.load_list(deck_path(a.deck)); cmd = lst[0]
    cs = [CD.get(n) for n in dict.fromkeys(lst[1:]) if not CD.get(n).is_land]
    engine = [c.name for c in cs if c.draw_engine >= 1 or c.free_outlet or c.tokens_rec or c.anthem or (c.death_trig and c.death_trig.get('scope') in ('own', 'any'))]
    key = [c.name for c in cs if c.overrun or c.alt_win or c.wipe or (c.death_trig and c.death_trig.get('edict')) or c.draw_engine >= 1 or c.cmc >= 6][:12]
    pr = {c.name: 80 for c in cs if c.name in engine and not c.is_creature}
    pr.update({c.name: 85 for c in cs if c.death_trig and c.death_trig.get('edict')})
    pil = dict(commander=cmd, summary='TODO: one line on how this deck wins.', engine=engine,
               keep_home=[c.name for c in cs if c.is_creature and c.name in engine], keep_commander_home=True,
               fodder='any', fodder_max_cmc=3, instant_sac_tokens=[], bonus_keywords=[],
               tutor_targets=key[:6], priorities=pr, value_bonus={n: 4 for n in key[:6]}, key_cards=[cmd] + key,
               hold_removal_vs_combo=True, sac_nontoken=False)
    path = os.path.join(ROOT, 'pilots', a.deck + '.yaml')
    if os.path.exists(path) and not a.force: print('pilot exists; use --force to overwrite'); return
    yaml.safe_dump(pil, open(path, 'w'), sort_keys=False, allow_unicode=True, width=120)
    print('wrote', path, '- review engine / keep_home / priorities / tutor_targets before running')

def cmd_stale(a):
    cfg = R.load_cfg(); days = cfg['defaults'].get('refresh_days', 60)
    for k in sorted(os.listdir(os.path.join(ROOT, 'opponents'))):
        m = R.opp_meta(k); age = (datetime.date.today() - datetime.date.fromisoformat(str(m['fetched']))).days
        flag = 'STALE' if age > days else 'ok'
        print(f"{flag:5} {k:10} {age:4}d  {m['source']['b3']}  {m['source']['b4']}")

# ------------------------------------------------------------------ simulation
def cmd_smoke(a):
    cfg = R.load_cfg(); pilot = R.load_pilot(a.deck); lst = R.load_list(deck_path(a.deck))
    def handler(sig, frm): raise TimeoutError()
    signal.signal(signal.SIGALRM, handler)
    ok = True
    for i, cat in enumerate(cfg['categories']):
        rng = random.Random(1 + i); att = tot = first = wins = 0; stuck = collections.Counter(); n = a.games
        for gno in range(n):
            opps = R.pick_opps(cfg, cat, rng)
            br = [rng.choice(cfg['defaults']['brackets']) for _ in opps]
            g = E.Game(R.specs_for(cfg, cat, lst, pilot, rng, br, opps), rng, log=True)
            signal.alarm(5)
            try: g.play(); signal.alarm(0)
            except TimeoutError:
                ok = False; print(f'  HANG in {cat} game {gno} round {g.round}; last events:'); print('\n'.join(g.events[-10:])); break
            except Exception as e:
                signal.alarm(0); ok = False; print(f'  ERROR in {cat}: {e!r}'); raise
            me = next(x for x in g.players if x.is_me)
            wins += g.winner is me; first += bool(g.elim and g.elim[0][0] is me)
            att += sum(1 for e in g.events if ' attacks You ' in e); tot += sum(1 for e in g.events if ' attacks ' in e)
            stuck.update(c.name for c in me.hand if not c.is_land)
        print(f'  {cat}: won {wins}/{n}, attacks aimed at you {att / max(1, tot):.0%} (fair ~33%), out first {first / n:.0%} (fair 25%)')
        print(f'     cards most often stuck in hand at game end: {stuck.most_common(5)}')
    print('smoke test', 'passed' if ok else 'FAILED')

def run_dir(deck, tag=None, run_id=None):
    # run_id keeps concurrent jobs from overwriting each other: two jobs for the same
    # deck on the same day used to share results/<deck>/<TODAY>.
    name = TODAY + (f'-{tag}' if tag else '') + (f'-{run_id}' if run_id else '')
    d = os.path.join(ROOT, 'results', deck, name)
    os.makedirs(d, exist_ok=True); return d

def cmd_run(a):
    cats = [c.strip() for c in a.categories.split(',')] if a.categories else None
    pilot = R.load_pilot(a.deck)
    mode = 'category' if cats else (a.mode or R.load_cfg()['defaults'].get('mode', 'category'))
    unit = 'x 18 random LGS tables' if mode == 'lgs' else 'series per category'
    print(f'Running {a.deck} ({a.series or "default"} {unit})')
    res = R.run(deck_path(a.deck), pilot, a.series, cats, jobs=a.jobs, mode=mode)
    d = run_dir(a.deck, a.tag, getattr(a, 'run_id', None))
    R.save_results(res, os.path.join(d, 'results.json.gz'))
    cfg = R.load_cfg(); groups = R.analyze(res, cfg, pilot)
    meta = dict(date=TODAY, deck=a.deck, mode=mode, series_per_cat=a.series or cfg['defaults']['series'],
                series_total=sum(len(r['series']) for r in res.values()), games_total=sum(len(r['games']) for r in res.values()),
                list_snapshot=R.load_list(deck_path(a.deck)))
    json.dump(dict(meta=meta, groups=groups), open(os.path.join(d, 'summary.json'), 'w'), indent=1)
    open(os.path.join(d, 'summary.md'), 'w').write(R.summary_md(pilot.get('commander', a.deck), groups, meta))
    print('saved to', os.path.relpath(d, ROOT))

def cmd_variants(a):
    base = R.load_list(deck_path(a.deck)); pilot = R.load_pilot(a.deck)
    vdir = os.path.join(ROOT, 'decks', a.deck, 'variants'); os.makedirs(vdir, exist_ok=True)
    lists = {'base': deck_path(a.deck)}; names = {'base': 'Your current list'}
    for sw in a.swap:
        out, inn = [x.strip() for x in sw.split('->')]
        lst = list(base)
        if out not in lst: sys.exit(f'{out!r} is not in the list')
        lst.remove(out); lst.append(inn)
        key = re.sub(r'[^a-z0-9]+', '-', f'{out}-to-{inn}'.lower()).strip('-')
        path = os.path.join(vdir, key + '.txt')
        with open(path, 'w') as f:
            for n, q in collections.Counter(lst).items(): f.write(f'{q} {n}\n')
        lists[key] = path; names[key] = f'{out} → {inn}'
    fetch_cards(set(n for p in lists.values() for n in R.load_list(p)))
    out = {}
    for k, path in lists.items():
        print(f'== {names[k]}')
        res = R.run(path, pilot, a.series, None, jobs=a.jobs, mode=a.mode)
        views, _ = R.lgs_views(res, R.load_cfg())
        out[k] = {c: round(100 * sum(g['won'] for g in r['games']) / len(r['games']), 1) for c, r in views.items() if r['games']}
    d = run_dir(a.deck, 'variants')
    json.dump(dict(variants=out, names=names, series=a.series), open(os.path.join(d, 'variants.json'), 'w'), indent=1)
    print(json.dumps(out, indent=1)); print('saved to', os.path.relpath(d, ROOT))

def cmd_report(a):
    rdir = a.run or sorted(d for d in glob.glob(os.path.join(ROOT, 'results', a.deck, '*')) if os.path.exists(os.path.join(d, 'summary.json')))[-1]
    S = json.load(open(os.path.join(rdir, 'summary.json'))); pilot = R.load_pilot(a.deck)
    data = dict(groups=S['groups'], total_games=S['meta']['games_total'], total_series=S['meta']['series_total'], date=S['meta']['date'], mode=S['meta'].get('mode', 'category'))
    ins = a.insights or os.path.join(rdir, 'insights.json')
    if os.path.exists(ins): data['insights'] = json.load(open(ins))
    vfile = a.variants or next(iter(sorted(glob.glob(os.path.join(ROOT, 'results', a.deck, '*variants*', 'variants.json')))[-1:]), None)
    if vfile and os.path.exists(vfile):
        V = json.load(open(vfile)); data.update(variants=V['variants'], variant_names=V['names'], swap_note=V.get('note', ''))
    lst = S['meta'].get('list_snapshot') or R.load_list(deck_path(a.deck))
    groups = collections.OrderedDict((k, collections.Counter()) for k in ('Commander', 'Creatures', 'Instants', 'Sorceries', 'Artifacts', 'Enchantments', 'Planeswalkers', 'Lands'))
    for i, n in enumerate(lst):
        c = CD.get(n)
        k = 'Commander' if i == 0 else 'Lands' if c.is_land else 'Creatures' if c.is_creature else 'Planeswalkers' if c.is_planeswalker \
            else 'Instants' if c.is_instant else 'Sorceries' if c.is_sorcery else 'Artifacts' if c.is_artifact else 'Enchantments'
        groups[k][n] += 1
    data['decklist'] = [[k, sorted([[q, n] for n, q in v.items()], key=lambda x: x[1])] for k, v in groups.items() if v]
    cmd = pilot.get('commander', a.deck)
    t = open(os.path.join(ROOT, 'report', 'template.html')).read()
    t = t.replace('__TITLE__', f'{cmd.split(",")[0]} Gauntlet').replace('__H1__', f'The {cmd} gauntlet' if not cmd.startswith('The ') else f'{cmd} gauntlet')
    t = t.replace('__EYEBROW__', pilot.get('eyebrow', pilot.get('summary', '')[:80]))
    t = t.replace('__DATA__', json.dumps(data).replace('</', '<\\/'))
    out = os.path.join(rdir, 'report.html'); open(out, 'w').write(t); print('wrote', os.path.relpath(out, ROOT))

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd', required=True)
    for name, fn in (('check', cmd_check), ('init-pilot', cmd_init_pilot), ('smoke', cmd_smoke), ('run', cmd_run),
                     ('variants', cmd_variants), ('report', cmd_report)):
        x = sp.add_parser(name); x.add_argument('deck'); x.set_defaults(fn=fn)
        if name == 'init-pilot': x.add_argument('--force', action='store_true')
        if name == 'smoke': x.add_argument('--games', type=int, default=8)
        if name in ('run', 'variants'):
            x.add_argument('--series', type=int); x.add_argument('--jobs', type=int, default=2)
            x.add_argument('--mode', choices=['lgs', 'category'], help='lgs: random mixed tables (default in gauntlets.yaml); category: 3 decks from one category')
        if name == 'run': x.add_argument('--categories'); x.add_argument('--tag'); x.add_argument('--run-id')
        if name == 'variants': x.add_argument('--swap', action='append', required=True)
        if name == 'report': x.add_argument('--run'); x.add_argument('--insights'); x.add_argument('--variants')
    x = sp.add_parser('stale'); x.set_defaults(fn=cmd_stale)
    a = ap.parse_args(); a.fn(a)

if __name__ == '__main__':
    main()
