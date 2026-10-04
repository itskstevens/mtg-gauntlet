#!/usr/bin/env python3
"""Track Kevin's ManaBox collection in git and work out what new cards are good for.

  python3 tools/collection.py import EXPORT [--date YYYY-MM-DD]   # normalise + save, prints the change summary
  python3 tools/collection.py diff [--from REV] [--to REV]        # cards added/removed between two versions
  python3 tools/collection.py fits [--from REV] [--json OUT]      # where the added cards could go

Files:
  collection/manabox.txt   the latest export, normalised to `qty Name (SET) num [*F*]`, sorted. Git history = versions.
  collection/cards.tsv     name<TAB>qty, summed across printings (what diffs and deck checks use).
  collection/rarity.tsv    name<TAB>lowest rarity seen in the export (only filled from CSV exports).
  collection/history.md    one line per import: date, unique cards, total cards, +added / -removed.
"""
import argparse, csv, collections, datetime, io, json, os, re, subprocess, sys, glob, unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
COL = os.path.join(ROOT, 'collection')
BASICS = {'plains', 'island', 'swamp', 'mountain', 'forest', 'wastes'}
RAR = {'common': 'C', 'uncommon': 'U', 'rare': 'R', 'mythic': 'M', 'special': 'S', 'bonus': 'S'}

def norm(n):
    n = unicodedata.normalize('NFKD', n).encode('ascii', 'ignore').decode().split(' // ')[0].strip().lower()
    return re.sub(r'\s+', ' ', n)

# ------------------------------------------------------------------ parsing
LINE = re.compile(r'^(\d+)x?\s+(.+?)(?:\s+\(([A-Za-z0-9]+)\)\s*(\S+)?)?(\s+\*F\*)?$')

def parse_export(path):
    """Return a list of (qty, name, set, num, foil, rarity) from a ManaBox .txt or .csv export."""
    raw = open(path, encoding='utf-8-sig').read()
    rows = []
    first = raw.splitlines()[0] if raw.strip() else ''
    if ',' in first and 'name' in first.lower():
        for r in csv.DictReader(io.StringIO(raw)):
            k = {x.lower().strip(): (v or '').strip() for x, v in r.items() if x}
            name = k.get('name'); q = int(k.get('quantity') or k.get('count') or 1)
            if not name: continue
            rows.append((q, name, k.get('set code', '').upper(), k.get('collector number', ''),
                         k.get('foil', '').lower() in ('foil', 'etched', 'true', 'yes'), RAR.get(k.get('rarity', '').lower(), '')))
    else:
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.lower().startswith(('sideboard', '//')): continue
            m = LINE.match(line)
            if not m: print('  skipped unreadable line:', line); continue
            rows.append((int(m.group(1)), m.group(2), (m.group(3) or '').upper(), m.group(4) or '', bool(m.group(5)), ''))
    return rows

def totals(rows):
    t = collections.Counter(); disp = {}
    for q, n, *_ in rows:
        t[norm(n)] += q; disp.setdefault(norm(n), n.split(' // ')[0])
    return t, disp

def read_tsv(text):
    t = collections.Counter(); disp = {}
    for line in text.splitlines():
        if '\t' not in line: continue
        n, q = line.rsplit('\t', 1); t[norm(n)] += int(q); disp[norm(n)] = n
    return t, disp

def git(*a): return subprocess.run(['git', '-C', ROOT, *a], capture_output=True, text=True).stdout

def version(rev):
    """cards.tsv at a git revision ('WORK' = working tree). Falls back to the old dated export for early history."""
    if rev == 'WORK':
        p = os.path.join(COL, 'cards.tsv')
        return read_tsv(open(p).read()) if os.path.exists(p) else (collections.Counter(), {})
    txt = git('show', f'{rev}:collection/cards.tsv')
    if txt: return read_tsv(txt)
    old = git('show', f'{rev}:collection/manabox-2026-10-04.txt')
    if old:
        tmp = os.path.join('/tmp', 'old_export.txt'); open(tmp, 'w').write(old)
        return totals(parse_export(tmp))
    return collections.Counter(), {}

def prev_rev(back=1):
    """Commit that holds the version before the current one (the last commit that touched cards.tsv, minus `back`)."""
    revs = [r for r in git('log', '--format=%H', '--', 'collection/cards.tsv', 'collection/manabox-2026-10-04.txt').split() if r]
    return revs[back] if len(revs) > back else None

# ------------------------------------------------------------------ commands
def cmd_import(a):
    rows = parse_export(a.export)
    if not rows: sys.exit('No cards found in that export.')
    before, bdisp = version('WORK')
    if not before:   # first import after the dated-file era
        r = prev_rev(0); before, bdisp = version(r) if r else (collections.Counter(), {})
    t, disp = totals(rows)
    os.makedirs(COL, exist_ok=True)
    lines = sorted((f"{q} {n}" + (f" ({s}) {num}".rstrip() if s else '') + (' *F*' if f else '')) for q, n, s, num, f, _ in rows)
    open(os.path.join(COL, 'manabox.txt'), 'w').write('\n'.join(lines) + '\n')
    open(os.path.join(COL, 'cards.tsv'), 'w').write(''.join(f'{disp[k]}\t{t[k]}\n' for k in sorted(t)))
    rar = {}
    order = 'CUSRM'
    for q, n, *_x, r in rows:
        if r: k = norm(n); rar[k] = min(rar.get(k, r), r, key=order.index)
    if rar: open(os.path.join(COL, 'rarity.tsv'), 'w').write(''.join(f'{disp[k]}\t{rar[k]}\n' for k in sorted(rar)))
    add = {k: t[k] - before.get(k, 0) for k in t if t[k] > before.get(k, 0)}
    rem = {k: before[k] - t.get(k, 0) for k in before if before[k] > t.get(k, 0)}
    date = a.date or datetime.date.today().isoformat()
    hist = os.path.join(COL, 'history.md')
    if not os.path.exists(hist): open(hist, 'w').write('# Collection history\n\n| Date | Unique | Total | Added | Removed |\n|---|---|---|---|---|\n')
    open(hist, 'a').write(f'| {date} | {len(t)} | {sum(t.values())} | +{sum(add.values())} ({len(add)} unique) | -{sum(rem.values())} ({len(rem)} unique) |\n')
    print(f'Saved {len(t)} unique / {sum(t.values())} total cards.')
    print(f'Added {sum(add.values())} cards ({len(add)} unique), removed {sum(rem.values())} ({len(rem)} unique) since the last version.')
    print(f'Commit message suggestion: collection: ManaBox export {date} (+{sum(add.values())} / -{sum(rem.values())})')

def changes(frm, to):
    a, ad = version(frm); b, bd = version(to)
    disp = {**ad, **bd}
    add = {disp[k]: b[k] - a.get(k, 0) for k in b if b[k] > a.get(k, 0)}
    rem = {disp[k]: a[k] - b.get(k, 0) for k in a if a[k] > b.get(k, 0)}
    return add, rem, a, b

def cmd_diff(a):
    frm = a.frm or prev_rev(1 if a.to == 'WORK' and not os.path.exists(os.path.join(COL, 'cards.tsv')) else 1) or prev_rev(0)
    add, rem, *_ = changes(frm, a.to)
    print(f'From {frm[:8] if frm else "nothing"} to {a.to}:')
    print(f'  +{sum(add.values())} cards ({len(add)} unique)'); [print(f'    +{q} {n}') for n, q in sorted(add.items())]
    print(f'  -{sum(rem.values())} cards ({len(rem)} unique)'); [print(f'    -{q} {n}') for n, q in sorted(rem.items())]

# ------------------------------------------------------------------ fits
def deck_lists():
    """Every deck Kevin has: Commander decks (decks/*/list.txt, commander first) and Pauper decks (pauper/decks.json)."""
    out = {}
    for f in sorted(glob.glob(os.path.join(ROOT, 'decks', '*', 'list.txt'))):
        names = [l.strip().split(' ', 1) for l in open(f) if l.strip() and not l.startswith('#')]
        out['cmd:' + f.split(os.sep)[-2]] = {'format': 'commander', 'commander': names[0][1],
                                             'main': collections.Counter({n: int(q) for q, n in names}), 'side': collections.Counter(), 'buy': []}
    pj = os.path.join(ROOT, 'pauper', 'decks.json')
    if os.path.exists(pj):
        for k, d in json.load(open(pj)).items():
            main = collections.Counter(); side = collections.Counter()
            for g in d['groups']:
                for c in g[1]: main[c[1]] += c[0]
            for c in d['side']: side[c[1]] += c[0]
            out['pauper:' + k] = {'format': 'pauper', 'name': d['name'], 'colors': d['colors'], 'main': main, 'side': side,
                                  'buy': [(c[0], c[1], c[2]) for c in d.get('upgrades', [])]}
    return out

def identity(card_text):
    return set(re.findall(r'\{([WUBRG])(?:/[WUBRGP])?\}', card_text)) | set(c for c in 'WUBRG' if re.search(r'^ManaCost:.*\b' + c, card_text, re.M))

def card_script(name):
    from engine import cards as CD
    p = os.path.join(CD.FORGE_DIR, CD.slug(name) + '.txt')
    if not os.path.exists(p):
        try:
            from gauntlet import fetch_cards
            fetch_cards([name])
        except Exception: pass
    return open(p).read() if os.path.exists(p) else ''

def cmd_fits(a):
    frm = a.frm or prev_rev(1) or prev_rev(0)
    add, rem, before, after = changes(frm, 'WORK')
    decks = deck_lists()
    rar = read_tsv(open(os.path.join(COL, 'rarity.tsv')).read())[0] if os.path.exists(os.path.join(COL, 'rarity.tsv')) else {}
    try:
        sys.path.insert(0, os.path.join(ROOT, 'tools')); import pauper_legal
        pauper_ok = pauper_legal.pauper_pool()
    except Exception as e:
        print('  (Pauper check unavailable:', e, ')'); pauper_ok = set()
    report = {'from': frm, 'added': [], 'now_complete': [], 'buy_list_hits': []}
    # 1. deck cards that were missing before and are owned now
    for key, d in decks.items():
        need = d['main'] + d['side']
        was = {n: q for n, q in need.items() if norm(n) not in BASICS and before.get(norm(n), 0) < q}
        now = {n: q for n, q in need.items() if norm(n) not in BASICS and after.get(norm(n), 0) < q}
        filled = sorted(set(was) - set(now))
        if filled: report['now_complete'].append({'deck': key, 'cards': filled, 'still_missing': sorted(now)})
        for q, n, why in d['buy']:
            if norm(n) in {norm(x) for x in add}: report['buy_list_hits'].append({'deck': key, 'card': n, 'want': q, 'owned': after.get(norm(n), 0), 'plan': why})
    # 2. each added card: legality hints, colours, which decks it could slot into
    for n, q in sorted(add.items()):
        if norm(n) in BASICS: continue
        txt = card_script(n)
        ci = identity(txt) if txt else set()
        types = (re.search(r'^Types:(.*)$', txt, re.M) or [None, ''])[1].strip()
        oracle = (re.search(r'^Oracle:(.*)$', txt, re.M) or [None, ''])[1].replace('\\n', ' ').strip()
        cand = []
        for key, d in decks.items():
            if d['format'] == 'commander':
                cmd_txt = card_script(d['commander']); cmd_ci = identity(cmd_txt) if cmd_txt else set()
                if ci <= cmd_ci: cand.append(key)
            else:
                legal = norm(n) in pauper_ok or rar.get(norm(n)) == 'C'
                if legal and ci <= set(d['colors']): cand.append(key)
        report['added'].append({'card': n, 'qty': q, 'colors': ''.join(sorted(ci)), 'types': types, 'oracle': oracle[:300],
                                'rarity_in_export': rar.get(norm(n), ''), 'pauper_listed': norm(n) in pauper_ok,
                                'colour_fits': cand})
    if a.json: json.dump(report, open(a.json, 'w'), indent=1)
    print(f"Added since {frm[:8] if frm else 'start'}: {len(report['added'])} unique cards")
    for x in report['buy_list_hits']: print(f"  BUY LIST HIT  {x['card']} for {x['deck']} (wanted {x['want']}, own {x['owned']}): {x['plan']}")
    for x in report['now_complete']: print(f"  NOW OWNED     {x['deck']}: {', '.join(x['cards'])}  ({len(x['still_missing'])} still missing)")
    for x in report['added']:
        groups = collections.OrderedDict()
        for k in x['colour_fits']:
            g = decks[k]['commander'] if k.startswith('cmd:') else decks[k]['name']
            groups.setdefault(g, []).append(k)
        shown = [f"{g} ({len(v)} lists)" if len(v) > 1 else g for g, v in groups.items()]
        print(f"  {x['qty']}x {x['card']} [{x['colors'] or 'C'}] {x['types']}{' · Pauper' if x['pauper_listed'] else ''} -> {', '.join(shown) or 'no current deck by colour'}")

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(required=True)
    x = sp.add_parser('import'); x.add_argument('export'); x.add_argument('--date'); x.set_defaults(fn=cmd_import)
    x = sp.add_parser('diff'); x.add_argument('--from', dest='frm'); x.add_argument('--to', default='WORK'); x.set_defaults(fn=cmd_diff)
    x = sp.add_parser('fits'); x.add_argument('--from', dest='frm'); x.add_argument('--json'); x.set_defaults(fn=cmd_fits)
    a = ap.parse_args(); a.fn(a)

if __name__ == '__main__': main()
