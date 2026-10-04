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
import json, os, re, signal, subprocess, sys, time, uuid
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

def decks():
    d = os.path.join(ROOT, 'decks')
    return sorted(x for x in os.listdir(d) if os.path.isfile(os.path.join(d, x, 'list.txt')))


# ---------------------------------------------------------------- worker (runs detached, one per job)
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
    """Start a gauntlet job in the background and return its job id. Poll it with job_status.

    deck: folder name under decks/ (e.g. "codie").
    series: best-of-3 series per category (use 300 to compare runs).
    jobs: parallel worker processes; 0 means all cores but two.
    swaps: optional ["Out Card->In Card", ...]. If given, runs a swap test (variants) instead of a plain run;
           categories and tag don't apply to swap tests.
    categories: optional category names to limit a plain run to (as in gauntlets.yaml).
    tag: optional suffix for the results folder of a plain run.
    push: commit results/ and decks/ and push to GitHub when the job succeeds.
    """
    if deck not in decks(): return {'error': f'unknown deck {deck!r}', 'decks': decks()}
    if not 1 <= series <= MAX_SERIES: return {'error': f'series must be 1..{MAX_SERIES}'}
    running = [j for j in map(refresh, all_jobs()) if j['state'] in ('queued', 'running')]
    if running: return {'error': 'a job is already running', 'job_id': running[0]['id']}
    jobs = jobs or max(1, (os.cpu_count() or 2) - 2)
    argv = [PY, 'gauntlet.py']
    if swaps:
        bad = [s for s in swaps if s.count('->') != 1 or not all(NAME_RE.match(x.strip()) for x in s.split('->'))]
        if bad: return {'error': 'swaps must look like "Out Card->In Card"', 'bad': bad}
        argv += ['variants', deck, '--series', str(series), '--jobs', str(jobs)]
        for s in swaps: argv += ['--swap', s]
        kind = 'swap test'
    else:
        argv += ['run', deck, '--series', str(series), '--jobs', str(jobs)]
        if categories: argv += ['--categories', ','.join(categories)]
        if tag:
            if not re.fullmatch(r'[a-z0-9-]{1,40}', tag): return {'error': 'tag must be lowercase letters, digits and hyphens'}
            argv += ['--tag', tag]
        kind = 'gauntlet'
    os.makedirs(JOBS, exist_ok=True)
    jid = datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:4]
    job = dict(id=jid, deck=deck, kind=kind, series=series, jobs=jobs, swaps=swaps or [], push=push,
               argv=argv, state='queued', created=now())
    save(job)
    # Double fork via --spawn: the worker is reparented to init, survives this MCP session ending
    # (e.g. the SSH connection dropping) and never lingers as a zombie of the server.
    r = subprocess.run([PY, os.path.abspath(__file__), '--spawn', jid], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip().isdigit():
        job['state'] = 'failed'; job['finished'] = now(); save(job)
        return {'error': 'could not start the worker', 'detail': (r.stdout + r.stderr)[-1000:]}
    job['pid'] = int(r.stdout.strip()); save(job)
    est = round(15 * (len(swaps) + 1 if swaps else 1) * series / 300 / max(1, min(jobs, 18)), 1)
    return {'job_id': jid, 'state': 'started', 'command': ' '.join(argv[1:]), 'rough_minutes': est}

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
def list_jobs(limit: int = 10) -> list[dict]:
    """Recent jobs, newest first."""
    return [{k: j.get(k) for k in ('id', 'deck', 'kind', 'state', 'created', 'finished')}
            for j in map(refresh, all_jobs()[:max(1, min(limit, 50))])]

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
        mcp.run()
