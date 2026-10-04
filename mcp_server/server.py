#!/usr/bin/env python3
"""MCP server that runs mtg-gauntlet jobs on this machine (Kevin's homelab).

Exposes a few narrow tools, never a general shell:

  list_decks()                      decks and pilots in the repo
  run_gauntlet(deck, ...)           start a gauntlet run or swap test in the background, returns a job id
  job_status(job_id?)               state, elapsed time and log tail of a job (latest if no id)
  list_jobs()                       recent jobs
  cancel_job(job_id)                stop a running job
  sync()                            git pull --rebase, so new decks and pilots pushed from elsewhere are here

Runs take minutes, so run_gauntlet returns at once and the work happens in a detached worker process.
When a job finishes (and push=True) the worker commits results/ and decks/ and pushes, so any Claude session
can read the results from GitHub. Only one job runs at a time: a run already uses every core it is given.

Transport: stdio by default (works over `ssh homelab python mcp_server/server.py`).
`--http PORT` serves streamable HTTP instead, for use behind a tunnel; put authentication in front of it.
"""
import gzip, json, os, re, signal, subprocess, sys, time, uuid
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOBS = os.path.join(ROOT, 'mcp_server', 'jobs')
PY = sys.executable
MAX_SERIES = 1000
NAME_RE = re.compile(r"^[A-Za-z0-9 ,.'’\-:/!&()]+$")   # card names; no shell is ever involved, this just rejects junk


# ---------------------------------------------------------------- helpers
def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def jpath(jid, ext): return os.path.join(JOBS, f'{jid}.{ext}')

def load(jid):
    try: return json.load(open(jpath(jid, 'json')))
    except FileNotFoundError: return None

def save(job):
    tmp = jpath(job['id'], 'json.tmp')
    json.dump(job, open(tmp, 'w'), indent=1); os.replace(tmp, jpath(job['id'], 'json'))

def all_jobs():
    if not os.path.isdir(JOBS): return []
    js = [load(f[:-5]) for f in os.listdir(JOBS) if f.endswith('.json')]
    return sorted((j for j in js if j), key=lambda j: j['created'], reverse=True)

def alive(pid):
    try: os.kill(pid, 0); return True
    except (ProcessLookupError, TypeError): return False
    except PermissionError: return True

def refresh(job):
    """A job marked running whose worker vanished (reboot, crash) is reported as lost."""
    if job['state'] == 'running' and not alive(job.get('pid')):
        job['state'] = 'lost'; job['finished'] = now(); save(job)
    return job

def tail(jid, n=40):
    try:
        with open(jpath(jid, 'log'), errors='replace') as f: return ''.join(f.readlines()[-n:])
    except FileNotFoundError: return ''

def git(*args, check=True):
    return subprocess.run(['git', '-C', ROOT, *args], capture_output=True, text=True, check=check)


def run_files(deck, run=''):
    """Result files for a deck. run='' is the newest run, run='all' is every run."""
    base = os.path.join(ROOT, 'results', deck)
    if not os.path.isdir(base): return []
    names = sorted((d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))), reverse=True)
    if run == 'all': pass
    elif run: names = [n for n in names if n == run]
    else: names = names[:1]
    out = []
    for n in names:
        f = os.path.join(base, n, 'results.json.gz')
        if os.path.exists(f): out.append(f)
    return out


def load_runs(deck, run=''):
    runs = []
    for f in run_files(deck, run):
        try: runs.append((os.path.basename(os.path.dirname(f)), json.load(gzip.open(f, 'rt'))))
        except Exception: pass
    return runs


def _tally(pairs, key=lambda p: p[0]):
    from collections import Counter
    return Counter(key(p) for p in pairs)


def _rank(counter, total, top):
    """[(label, count, share)] sorted by count desc."""
    if not total: return []
    return [(k, c, round(c / total, 3)) for k, c in counter.most_common(max(1, top))]


def _slugify(s):
    import re, unicodedata
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode().lower()
    s = s.replace("'", '').replace('’', '')
    return re.sub(r'[^a-z0-9]+', '_', s).strip('_')


_slug_index = None


def _slug_map():
    """slug -> canonical card name, for both the full "Front // Back" name and the front
    face. Lets a run that stored 'mogis-god-of-slaughter' resolve to the real card
    without depending on how the name was punctuated."""
    global _slug_index
    if _slug_index is None:
        idx = {}
        con = _oracle_conn()
        if con:
            try:
                for (nm,) in con.execute('select distinct name from cards'):
                    if not nm: continue
                    idx.setdefault(_slugify(nm), nm)
                    idx.setdefault(_slugify(nm.split(' // ')[0]), nm)
            finally:
                con.close()
        _slug_index = idx
    return _slug_index


def _killer_rows(counter, total, top):
    """Killer stats as dicts, bridged to the card database where the label is a real card.

    Killer labels are a mix of card names, slug-form card names and opponent deck
    archetypes. Matching is on slug equality, not containment, so an archetype called
    'Spellslinger' is not bridged to 'Crackling Spellslinger'."""
    rows = []
    for label, c, share in _rank(counter, total, top):
        row = {'label': label, 'count': c, 'share': share}
        canonical = _slug_map().get(_slugify(label))
        hit = resolve_card(canonical) if canonical else None
        if hit:
            pairs = card_rules_for(hit)
            row['card'] = {
                'name': hit['name'],
                'image': f"{IMAGE_BASE}/{hit['image_path']}" if hit['image_path'] else None,
                'rules': [{'keyword': k, 'rule': n} for k, n in pairs[:4]],
            }
        rows.append(row)
    return rows


def _pct(wins, total):
    return round(wins / total, 3) if total else None


def _death_parts(d):
    """my_death is [cause, killer, turn]; tolerate short/odd entries."""
    if not isinstance(d, (list, tuple)) or not d: return (None, None, None)
    cause = d[0] if len(d) > 0 else None
    killer = d[1] if len(d) > 1 else None
    turn = d[2] if len(d) > 2 else None
    return (cause, killer, turn if isinstance(turn, int) else None)

def decks():
    d = os.path.join(ROOT, 'decks')
    return sorted(x for x in os.listdir(d) if os.path.isfile(os.path.join(d, x, 'list.txt')))


def category_names():
    """Categories from the gauntlet config. The engine's worker pool is over categories
    (runner.run builds one task per category), so this - not the core count - is the real
    ceiling on how many workers can do useful work."""
    try:
        import yaml
        path = os.environ.get('GAUNTLET_CFG_PATH', os.path.join(ROOT, 'gauntlets.yaml'))
        return list((yaml.safe_load(open(path)) or {}).get('categories') or {})
    except Exception:
        return []


# ---------------------------------------------------------------- worker (runs detached, one per job)
def running_job():
    """The job currently occupying the engine, or None."""
    for j in map(refresh, all_jobs()):
        if j['state'] == 'running' and alive(j.get('pid')):
            return j
    return None


def queued_jobs():
    return sorted((j for j in map(refresh, all_jobs()) if j['state'] == 'queued'),
                  key=lambda j: j.get('created', ''))


def spawn(jid):
    """Double fork via --spawn: the worker is reparented to init, survives this MCP
    session ending (e.g. the SSH connection dropping) and never lingers as a zombie."""
    return subprocess.run([PY, os.path.abspath(__file__), '--spawn', jid],
                          cwd=ROOT, capture_output=True, text=True)


def dispatch_next():
    """Start the oldest queued job if the engine is free. Safe to call repeatedly."""
    if running_job(): return None
    for job in queued_jobs():
        if alive(job.get('pid')): continue
        r = spawn(job['id'])
        if r.returncode == 0 and r.stdout.strip().isdigit():
            job['pid'] = int(r.stdout.strip()); save(job)
            return job['id']
        job['state'] = 'failed'; job['finished'] = now(); save(job)
        log_tail = f'could not start worker: {(r.stdout + r.stderr)[-400:]}'
        with open(jpath(job['id'], 'log'), 'a') as f: f.write(log_tail + '\n')
    return None


PUSH_LOCK = os.path.join(JOBS, 'push.lock')


def push_lock():
    """Exclusive flock around the git add/commit/pull/push sequence, so a job finishing
    and a manual sync can't interleave git operations on the same repo."""
    import fcntl
    os.makedirs(JOBS, exist_ok=True)
    fh = open(PUSH_LOCK, 'w')
    fcntl.flock(fh, fcntl.LOCK_EX)
    return fh


def worker(jid):
    job = load(jid); job['state'] = 'running'; job['pid'] = os.getpid(); job['started'] = now(); save(job)
    log = open(jpath(jid, 'log'), 'a', buffering=1)

    def step(argv):
        log.write(f'\n$ {" ".join(argv)}\n')
        p = subprocess.Popen(argv, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=False)
        job['child'] = p.pid; save(job)
        return p.wait()

    rc = 0
    try:
        rc = step(job['argv'])
        if rc == 0 and job['push']:
            msg = f"{job['deck']}: {job['kind']} {datetime.now().date()} ({job['series']} series, homelab)"
            with push_lock():
                for argv in (['git', 'add', 'results', 'decks'],
                             ['git', 'commit', '-m', msg],
                             ['git', 'pull', '--rebase', '--autostash'],
                             ['git', 'push']):
                    r = step(argv)
                    if r and argv[1] == 'commit':
                        log.write('(nothing to commit)\n'); break
                    if r: rc = r; break
    except Exception as e:
        log.write(f'\nworker error: {e!r}\n'); rc = 1
    job = load(jid)
    if job['state'] != 'cancelled': job['state'] = 'done' if rc == 0 else 'failed'
    job['returncode'] = rc; job['finished'] = now(); save(job)
    log.close()
    if job['state'] != 'cancelled':
        try:
            from notify import notify
            notify(jid, job['deck'], rc == 0,
                   f"{job['series']} series, {job['jobs']} workers" if rc == 0 else f'rc={rc}')
        except Exception:
            pass
    # this job freed the engine, so start the next one waiting
    dispatch_next()


# ---------------------------------------------------------------- MCP tools
from mcp.server.fastmcp import FastMCP
mcp = FastMCP('mtg-gauntlet')

@mcp.tool()
def list_decks() -> dict:
    """List decks in the gauntlet repo (folders under decks/ with a list.txt) and whether each has a pilot file."""
    return {'decks': [{'deck': d, 'pilot': os.path.exists(os.path.join(ROOT, 'pilots', d + '.yaml'))} for d in decks()],
            'cpu_count': os.cpu_count()}

@mcp.tool()
def run_gauntlet(deck: str, series: int = 300, jobs: int = 0, swaps: list[str] | None = None,
                 categories: list[str] | None = None, tag: str = '', push: bool = True) -> dict:
    """Queue a gauntlet job in the background and return its job id. Poll it with job_status.

    Jobs queue rather than collide: if one is already running the new job is held in
    state 'queued' with a position, and starts automatically when the engine frees up.
    Each job writes to its own results/<deck>/<date>-<job id> directory, so two runs of
    the same deck on the same day no longer overwrite each other.

    deck: folder name under decks/ (e.g. "codie").
    series: best-of-3 series per category (use 300 to compare runs).
    jobs: parallel worker processes; 0 means one per core. The engine pools over
          categories, so it is capped at the number of tasks the run actually has -
          asking for more workers than categories just idles them.
    swaps: optional ["Out Card->In Card", ...]. If given, runs a swap test (variants) instead of a plain run;
           categories and tag don't apply to swap tests.
    categories: optional category names to limit a plain run to (as in gauntlets.yaml).
    tag: optional suffix for the results folder of a plain run.
    push: commit results/ and decks/ and push to GitHub when the job succeeds.
    """
    if deck not in decks(): return {'error': f'unknown deck {deck!r}', 'decks': decks()}
    if not 1 <= series <= MAX_SERIES: return {'error': f'series must be 1..{MAX_SERIES}'}
    active = running_job()
    depth = len(queued_jobs())
    cats = category_names()
    jobs = jobs or (os.cpu_count() or 2)
    n_tasks = len(categories) if (categories and not swaps) else (len(cats) or jobs)
    eff_jobs = max(1, min(jobs, n_tasks))
    os.makedirs(JOBS, exist_ok=True)
    jid = datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:4]
    argv = [PY, 'gauntlet.py']
    if swaps:
        bad = [s for s in swaps if s.count('->') != 1 or not all(NAME_RE.match(x.strip()) for x in s.split('->'))]
        if bad: return {'error': 'swaps must look like "Out Card->In Card"', 'bad': bad}
        argv += ['variants', deck, '--series', str(series), '--jobs', str(eff_jobs)]
        for s in swaps: argv += ['--swap', s]
        kind = 'swap test'
    else:
        argv += ['run', deck, '--series', str(series), '--jobs', str(eff_jobs)]
        if categories: argv += ['--categories', ','.join(categories)]
        if tag:
            if not re.fullmatch(r'[a-z0-9-]{1,40}', tag): return {'error': 'tag must be lowercase letters, digits and hyphens'}
            argv += ['--tag', tag]
        argv += ['--run-id', jid]
        kind = 'gauntlet'
    job = dict(id=jid, deck=deck, kind=kind, series=series, jobs=eff_jobs, swaps=swaps or [], push=push,
               argv=argv, state='queued', created=now())
    save(job)
    started = None if active else dispatch_next()
    job = load(jid)
    est = round(15 * (len(swaps) + 1 if swaps else 1) * series / 300 / eff_jobs, 1)
    out = {'job_id': jid, 'state': job['state'], 'command': ' '.join(argv[1:]), 'rough_minutes': est,
           'workers': eff_jobs, 'tasks': n_tasks}
    if active:
        out.update(queued_behind=depth, waiting_for=active['id'],
                   note=f"engine busy with {active['id']}; this job starts when it finishes")
    else:
        out['started'] = started == jid
    return out

@mcp.tool()
def job_status(job_id: str = '', log_lines: int = 40) -> dict:
    """State (queued, running, done, failed, cancelled, lost), timing and the last lines of a job's log.
    With no job_id, reports the most recent job."""
    job = load(job_id) if job_id else (all_jobs() or [None])[0]
    if not job: return {'error': 'no such job' if job_id else 'no jobs yet'}
    job = refresh(job)
    end = job.get('finished') or now()
    el = (datetime.fromisoformat(end) - datetime.fromisoformat(job.get('started') or job['created'])).total_seconds()
    out = {k: job.get(k) for k in ('id', 'deck', 'kind', 'series', 'jobs', 'swaps', 'state', 'returncode', 'created', 'finished')}
    out['elapsed_min'] = round(el / 60, 1); out['log_tail'] = tail(job['id'], max(1, min(log_lines, 200)))
    return out

@mcp.tool()
def analyze_run(deck: str, run: str = '', top: int = 8, min_games: int = 20) -> dict:
    """Aggregate what a finished run already recorded. Does not re-simulate.

    Every game stores why you died, which seat you sat in, where you placed, how
    long it ran and what you cast - so this answers "what actually kills this deck"
    and "are we on the play or the draw" rather than just reporting a win rate.

    deck: folder name under decks/.
    run: run directory name; default is the newest, 'all' covers every stored run.
    top: rows per breakdown.
    min_games: ignore cards cast in fewer games than this, they are noise.
    """
    runs = load_runs(deck, run)
    if not runs:
        have = sorted(d for d in decks() if run_files(d))
        return {'error': f'no stored results for {deck!r}',
                'decks_with_results': have,
                'hint': ('run a gauntlet first, or pass run="all"' if deck in decks()
                         else f'unknown deck; known decks: {decks()}')}

    games, series = [], []
    per_cat = {}
    for name, data in runs:
        for cat, v in (data or {}).items():
            gs = v.get('games') or []
            ss = v.get('series') or []
            games += gs; series += [(cat, s) for s in ss]
            c = per_cat.setdefault(cat, {'games': 0, 'wins': 0, 'series': 0, 'series_wins': 0})
            c['games'] += len(gs); c['wins'] += sum(1 for g in gs if g.get('won'))
            c['series'] += len(ss); c['series_wins'] += sum(1 for s in ss if s.get('won'))

    n = len(games) or 1
    wins = [g for g in games if g.get('won')]
    losses = [g for g in games if not g.get('won') and not g.get('draw')]
    draws = [g for g in games if g.get('draw')]

    def wr(g): return round(sum(1 for x in g if x.get('won')) / len(g), 3) if g else None

    place = _tally([(g.get('place'),) for g in games])
    seat = {}
    for g in games:
        s = g.get('seat')
        if s is None: continue
        seat.setdefault(s, []).append(g)

    buckets = [(0, 5), (5, 8), (8, 11), (11, 14), (14, 99)]
    def len_hist(gs):
        h = {}
        for lo, hi in buckets:
            k = f'{lo}-{hi}' if hi < 99 else f'{lo}+'
            h[k] = sum(1 for g in gs if lo <= (g.get('rounds') or 0) <= hi)
        return h

    deaths = [_death_parts(g.get('my_death')) for g in games]
    death_causes = _tally([(d[0],) for d in deaths if d[0]])
    death_killers = _tally([(d[1],) for d in deaths if d[1]])
    death_turns = [d[2] for d in deaths if d[2] is not None]

    opp_kills, opp_wins = {}, {}
    for g in games:
        for o in (g.get('opp') or []):
            a = o.get('arch')
            if not a: continue
            opp_kills.setdefault(a, []).append(bool(o.get('killed_by_me')))
            if o.get('won'): opp_wins[a] = opp_wins.get(a, 0) + 1

    cast_w, cast_l = {}, {}
    for g in games:
        tgt = cast_w if g.get('won') else cast_l
        for c in set(g.get('my_cast') or []): tgt[c] = tgt.get(c, 0) + 1
    cards = []
    for c in set(cast_w) | set(cast_l):
        tot = cast_w.get(c, 0) + cast_l.get(c, 0)
        if tot < min_games: continue
        cards.append((c, _pct(cast_w.get(c, 0), tot), tot, cast_w.get(c, 0)))
    cards.sort(key=lambda x: (-(x[1] or 0), -x[2]))

    stats = {}
    for g in games:
        for k, v in (g.get('my_stats') or {}).items():
            if not isinstance(v, (int, float)): continue
            stats.setdefault(k, [0, 0, 0])
            stats[k][0] += v
            stats[k][1] += 1
            stats[k][2] += 1 if g.get('won') else 0
    stat_rows = []
    for k, (tot, cnt, wcnt) in stats.items():
        if cnt < min_games: continue
        aw = tot / cnt
        stat_rows.append((k, round(aw, 2), round(wcnt / cnt, 3), cnt))
    stat_rows.sort(key=lambda r: -abs((r[2] or 0) - (wr(games) or 0)))

    return {
        'runs': [n for n, _ in runs],
        'overview': {
            'games': len(games), 'series': len(series), 'draws': len(draws),
            'game_win': wr(games),
            'series_win': _pct(sum(1 for _, s in series if s.get('won')), len(series)),
            'avg_place': round(sum(g.get('place') or 4 for g in games) / n, 2),
            'first_place': place.get(1, 0),
            'avg_rounds_win': round(sum(g.get('rounds') or 0 for g in wins) / len(wins), 1) if wins else None,
            'avg_rounds_loss': round(sum(g.get('rounds') or 0 for g in losses) / len(losses), 1) if losses else None,
        },
        'placement': [[f'place {k}', v, round(v / n, 3)] for k, v in sorted(place.items(), key=lambda x: (x[0] is None, x[0]))],
        'by_seat': {f'seat {k}': {'games': len(v), 'win': wr(v)} for k, v in sorted(seat.items())},
        'game_length': {'wins': len_hist(wins), 'losses': len_hist(losses)},
        'what_kills_you': {
            'cause': _rank(death_causes, len(deaths), top),
            'killer': _killer_rows(death_killers, len(deaths), top),
            'avg_death_turn': round(sum(death_turns) / len(death_turns), 1) if death_turns else None,
        },
        'opponents': [{'arch': a, 'times': len(v), 'you_killed_rate': _pct(sum(1 for x in v if x), len(v)), 'games_won': opp_wins.get(a, 0)}
                      for a, v in sorted(opp_kills.items(), key=lambda x: -len(x[1]))[:top]],
        'categories': [{'category': c, 'games': d['games'], 'game_win': _pct(d['wins'], d['games']),
                        'series': d['series'], 'series_win': round(d['series_wins'] / d['series'], 3) if d['series'] else None}
                       for c, d in sorted(per_cat.items(), key=lambda x: x[1]['games'], reverse=True)],
        'cards_in_wins': [{'card': c, 'win_rate_when_cast': w, 'games_cast': t, 'wins': k}
                          for c, w, t, k in cards[:top]],
        'cards_you_lose_with': [{'card': c, 'win_rate_when_cast': w, 'games_cast': t}
                                for c, w, t, k in sorted(cards, key=lambda x: (x[1] if x[1] is not None else 1))[:top]],
        'stat_deltas': [{'stat': k, 'avg': a, 'win_rate_when_present': w, 'games': c} for k, a, w, c in stat_rows[:top]],
        'fought': f'{n} games' + (f' over {len(deaths)} deaths' if deaths else ''),
    }


ORACLE_DB = os.environ.get('ORACLE_DB', '/mnt/expansion/mtg-data/cards.sqlite')


def oracle_lookup(names):
    """name -> (legalities dict, oracle row) for names present in the rules MCP's
    Scryfall DB. Empty if that DB is not reachable, so this still works without it."""
    if not os.path.exists(ORACLE_DB): return {}, 'no Oracle DB at ' + ORACLE_DB
    import sqlite3
    con = sqlite3.connect(f'file:{ORACLE_DB}?mode=ro', uri=True, check_same_thread=False)
    try:
        out = {}
        for n in names:
            low = n.lower()
            rows = con.execute(
                'select name, legalities, type_line, color_identity, image_set, layout, name_lower '
                'from cards where name_lower = ? or name_lower like ?', (low, f'%{low}%')).fetchall()
            if not rows: continue
            # Scryfall stores double-faced and split cards as "Front // Back", so an exact
            # match misses them; prefer an exact name, then a real printing over art_series.
            def rank(r):
                exact = 0 if r[6] == low else 1
                series = 1 if r[5] in ('art_series', 'token') else 0
                return (series, exact)
            r = sorted(rows, key=rank)[0]
            try: legal = json.loads(r[1] or '{}')
            except ValueError: legal = {}
            out[n] = {'name': r[0], 'legalities': legal, 'type_line': r[2],
                      'color_identity': r[3], 'image_set': r[4]}
        return out, None
    finally:
        con.close()


ORACLE_DB = os.environ.get('ORACLE_DB', '/mnt/expansion/mtg-data/cards.sqlite')
RULES_JSON = os.environ.get('RULES_JSON', '/home/kevin/mtg-rules/data/rules.json')
IMAGE_BASE = os.environ.get('MTG_IMAGE_BASE_URL', 'https://mtg-cards.lab.kstevens.ca/images')


def _oracle_conn():
    if not os.path.exists(ORACLE_DB): return None
    import sqlite3
    con = sqlite3.connect(f'file:{ORACLE_DB}?mode=ro', uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def resolve_card(name):
    """Card row for a name, matching the rules MCP's own lookup: substring, preferring a
    real printing over art_series. Scryfall stores double-faced cards as "Front // Back",
    so an exact name match misses them."""
    con = _oracle_conn()
    if not con: return None
    try:
        low = name.strip().lower()
        rows = con.execute('select * from cards where name_lower = ? or name_lower like ?',
                           (low, f'%{low}%')).fetchall()
        if not rows: return None
        def rank(r):
            series = 1 if r['layout'] in ('art_series', 'token') else 0
            exact = 0 if r['name_lower'] == low else 1
            return (series, exact)
        return sorted(rows, key=rank)[0]
    finally:
        con.close()


def card_rules_for(row):
    con = _oracle_conn()
    if not con or not row: return []
    try:
        return [(r[0], r[1]) for r in con.execute(
            'select keyword, rule_num from card_rules where oracle_id = ? and rule_num is not null '
            'order by keyword', (row['oracle_id'],))]
    finally:
        con.close()


_rules_cache = {}


def rule_text(nums):
    """Rule number -> text, from the rules MCP's parsed corpus. Empty if not readable."""
    if not nums: return []
    if not _rules_cache:
        try:
            data = json.load(open(RULES_JSON))
            _rules_cache['by_num'] = {r['num']: r.get('text', '') for r in data['rules']}
        except Exception:
            _rules_cache['by_num'] = {}
    by = _rules_cache['by_num']
    return [{'rule': n, 'text': by.get(n, '')} for n in nums]


@mcp.tool()
def card_context(name: str, rules: int = 6) -> dict:
    """Everything the rules MCP knows about a card, in one call.

    The bridge between the two servers: hand it a card name that came out of a gauntlet
    result - the thing that killed you, the one your opponent cast - and get the art,
    the oracle text and the Comprehensive Rules that govern it, without a second MCP
    round trip. Reads the same Scryfall database and parsed rules corpus the rules MCP
    serves, read-only.

    name: card name, front face is fine for double-faced cards.
    rules: how many governing rules to include.
    """
    row = resolve_card(name)
    if not row:
        return {'error': f'{name!r} is not in the card database',
                'db': ORACLE_DB if os.path.exists(ORACLE_DB) else None}
    try: legal = json.loads(row['legalities'] or '{}')
    except ValueError: legal = {}
    pairs = card_rules_for(row)
    return {
        'name': row['name'], 'layout': row['layout'], 'type_line': row['type_line'],
        'mana_cost': row['mana_cost'], 'cmc': row['cmc'],
        'power': row['power'], 'toughness': row['toughness'],
        'colors': row['colors'], 'oracle_text': row['oracle_text'],
        'legalities': {k: v for k, v in legal.items() if v != 'legal'},
        'legal_in': sorted(k for k, v in legal.items() if v == 'legal'),
        'image': f"{IMAGE_BASE}/{row['image_path']}" if row['image_path'] else None,
        'governing_rules': [{'keyword': k, 'rule': n} for k, n in pairs[:max(1, min(rules, 20))]],
        'rules_counted': len(pairs),
        'rulings_available': row['rulings_count'],
    }


@mcp.tool()
def audit_deck(deck: str, check_oracle: bool = True) -> dict:
    """Validate a deck before spending an hour simulating it.

    Checks the list format and count, whether the simulator can actually parse every
    card, whether each card exists in Scryfall, and whether it is legal in the formats
    that matter - so a stale ban list or an unparseable card shows up here instead of
    quietly skewing a gauntlet.

    deck: folder name under decks/.
    check_oracle: also cross-check names and legality against the rules MCP's card DB.
    """
    path = os.path.join(ROOT, 'decks', deck, 'list.txt')
    if not os.path.exists(path):
        return {'error': f'no list.txt for {deck!r}', 'decks': decks()}
    raw = [l.rstrip('\n') for l in open(path) if l.strip()]
    entries, malformed = [], []
    for i, line in enumerate(raw, 1):
        m = re.match(r'^\s*(\d+)\s+(.+?)\s*$', line)
        if m: entries.append((int(m.group(1)), m.group(2)))
        else: malformed.append({'line': i, 'text': line})

    names = [n for _, n in entries]
    counts: dict[str, int] = {}
    for _, n in entries: counts[n] = counts.get(n, 0) + 1
    dupes = [{'card': n, 'listed': c, 'entries': sum(1 for _, x in entries if x == n)}
             for n, c in counts.items() if sum(1 for _, x in entries if x == n) > 1]
    total = sum(c for c, _ in entries)

    sys.path.insert(0, ROOT)
    from engine import cards as CD
    unparseable, unresolved = [], []
    for n in sorted(set(names)):
        f = os.path.join(CD.FORGE_DIR, CD.slug(n) + '.txt')
        if not os.path.exists(f):
            unresolved.append(n); continue
        try: CD.get(n)
        except Exception as e: unparseable.append({'card': n, 'error': f'{type(e).__name__}: {e}'})
    dfc = os.path.join(ROOT, 'cards', 'dfc_map.json')
    dmap = json.load(open(dfc)) if os.path.exists(dfc) else {}

    out = {
        'deck': deck, 'entries': len(entries), 'listed_total': total,
        'unique_cards': len(set(names)), 'commander': names[0] if names else None,
        'malformed_lines': malformed, 'duplicate_entries': dupes,
        'zero_or_negative_counts': [{'card': n, 'count': c} for c, n in entries if c < 1],
        'simulator_cannot_parse': unparseable,
        'no_card_data': [{'card': n, 'in_dfc_map': n in dmap} for n in unresolved],
        'issues': len(malformed) + len(dupes) + len(unparseable) + len(unresolved)
                   + (1 if total != 100 else 0),
    }
    if check_oracle:
        found, err = oracle_lookup(sorted(set(names)))
        unknown = [n for n in sorted(set(names)) if n not in found]
        banned, not_legal = [], []
        for n, v in found.items():
            leg = v['legalities'] or {}
            if 'banned' in leg: banned.append({'card': n, 'banned_in': [k for k, s in leg.items() if s == 'banned']})
            if leg and not (leg.get('legal') or leg.get('commander')):
                not_legal.append({'card': n, 'legalities': leg})
        out['oracle'] = {
            'db': ORACLE_DB if not err else None,
            'not_in_scryfall': unknown,
            'banned_somewhere': banned,
            'no_format_allows_it': not_legal,
            'standard': sum(1 for v in found.values() if (v['legalities'] or {}).get('standard') == 'legal'),
            'modern': sum(1 for v in found.values() if (v['legalities'] or {}).get('modern') == 'legal'),
        }
        if err: out['oracle']['error'] = err
        out['issues'] += len(unknown) + len(banned) + len(not_legal)
    return out


@mcp.tool()
def compare_runs(deck: str, limit: int = 8) -> dict:
    """Compare a deck's stored runs oldest to newest, per category.

    Answers "did that change help?" - a deck edit usually helps some categories and
    hurts others, which a single win rate hides. Categories only present in some runs
    are reported as null rather than treated as zero.

    deck: folder name under decks/.
    limit: how many of the most recent runs to compare.
    """
    files = run_files(deck, 'all')[::-1][:max(2, min(limit, 20))]
    if len(files) < 2:
        return {'error': f'need at least two stored runs to compare, {deck!r} has {len(files)}',
                'decks_with_results': sorted(d for d in decks() if run_files(d))}
    seq = []
    for f in files:
        try:
            data = json.load(gzip.open(f, 'rt'))
        except Exception:
            continue
        name = os.path.basename(os.path.dirname(f))
        row = {'run': name}
        g_tot = g_win = 0
        for cat, v in (data or {}).items():
            gs = v.get('games') or []
            w = sum(1 for g in gs if g.get('won'))
            row[cat] = _pct(w, len(gs))
            g_tot += len(gs); g_win += w
        row['_games'] = g_tot; row['_win'] = _pct(g_win, g_tot)
        seq.append(row)

    META = ('run', '_games', '_win')
    cats = [c for c in seq[0] if c not in META]
    for r in seq[1:]: cats += [c for c in r if c not in META and c not in cats]
    deltas = []
    for c in cats:
        first, last = next((r.get(c) for r in seq if r.get(c) is not None), None), \
                  next((r[c] for r in reversed(seq) if r.get(c) is not None), None)
        if first is None or last is None: continue
        deltas.append({'category': c, 'first': first, 'last': last, 'delta': round(last - first, 3),
                       'direction': 'up' if last > first else ('down' if last < first else 'flat')})
    deltas.sort(key=lambda d: -d['delta'])
    gains = [d for d in deltas if d['delta'] > 0]
    regressions = [d for d in deltas if d['delta'] < 0]
    return {
        'deck': deck,
        'runs': [r['run'] for r in seq],
        'overall': [{'run': r['run'], 'games': r['_games'], 'game_win': r['_win']} for r in seq],
        'biggest_gains': gains[:6],
        'biggest_regressions': regressions[:6],
        'flat_categories': sum(1 for d in deltas if d['delta'] == 0),
        'note': 'null means that category was not in that run',
    }


@mcp.tool()
def list_jobs(limit: int = 10) -> dict:
    """Recent jobs, newest first, with live/queued detail so you can see where a job sits
    in the queue."""
    jobs, q = [], queued_jobs()
    for j in sorted(map(refresh, all_jobs()), key=lambda j: j.get('created', ''), reverse=True)[:max(1, min(limit, 50))]:
        d = {k: j.get(k) for k in ('id', 'deck', 'kind', 'state', 'created', 'finished')}
        if j['state'] == 'queued' and j in q: d['queue_position'] = q.index(j) + 1
        if j['state'] in ('queued', 'running'): d['alive'] = alive(j.get('pid'))
        jobs.append(d)
    active = running_job()
    return {'jobs': jobs, 'running': active['id'] if active else None,
            'queued': len(q), 'engine_workers': (os.cpu_count() or 2)}

@mcp.tool()
def cancel_job(job_id: str) -> dict:
    """Stop a running job. Results from a cancelled job are not committed."""
    job = load(job_id)
    if not job: return {'error': 'no such job'}
    if refresh(job)['state'] not in ('queued', 'running'): return {'error': f"job is {job['state']}"}
    job['state'] = 'cancelled'; save(job)
    for pid in (job.get('child'), job.get('pid')):
        try: os.killpg(os.getpgid(pid), signal.SIGTERM)
        except Exception:
            try: os.kill(pid, signal.SIGTERM)
            except Exception: pass
    job['finished'] = now(); save(job)
    return {'job_id': job_id, 'state': 'cancelled'}

@mcp.tool()
def sync() -> dict:
    """git pull --rebase in the gauntlet repo, so decks and pilots pushed from elsewhere are available here."""
    if any(j['state'] == 'running' for j in map(refresh, all_jobs())):
        return {'error': 'a job is running; sync after it finishes'}
    r = git('pull', '--rebase', '--autostash', check=False)
    return {'ok': r.returncode == 0, 'output': (r.stdout + r.stderr)[-2000:],
            'head': git('log', '--oneline', '-1', check=False).stdout.strip()}


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--spawn':
        jid = sys.argv[2]
        p = subprocess.Popen([PY, os.path.abspath(__file__), '--worker', jid], cwd=ROOT,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=open(jpath(jid, 'log'), 'a'),
                             start_new_session=True)
        print(p.pid)
    elif len(sys.argv) == 3 and sys.argv[1] == '--worker':
        worker(sys.argv[2])
    elif len(sys.argv) == 3 and sys.argv[1] == '--http':
        mcp.settings.host = '127.0.0.1'; mcp.settings.port = int(sys.argv[2])
        mcp.run(transport='streamable-http')
    else:
        # recover: a job that was queued when the server last went away never got a
        # worker, so nothing would ever start it
        try: dispatch_next()
        except Exception: pass
        mcp.run()
