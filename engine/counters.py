"""+1/+1 counters, planeswalker loyalty and Lae'zel, Vlaakith's Champion.

Only switched on for decks whose pilot file sets `counters_engine: true`, so every other deck (and every opponent)
plays exactly as before. Hooks are called from engine.py at: resolve (enter with counters / loyalty), etb_triggers
(Cathars' Crusade), gain (life-gain counters), landfall (Felidar Retreat), precombat (loyalty abilities and
beginning-of-combat counters), combat (attack triggers, damage diverted to planeswalkers) and kw/power (statics).
"""
import copy, re

LAEZEL = "Lae'zel, Vlaakith's Champion"

def on(P):
    return bool(P.pilot.get('counters_engine'))

def laezel(P):
    return any(p.name == LAEZEL and not p.neutral for p in P.bf)

def add(g, p, n, loyalty=False):
    """Put n counters on p (a +1/+1 counter on a creature, or loyalty on a planeswalker). Lae'zel adds one."""
    P = p.owner
    if n <= 0 or p not in P.bf: return 0
    if on(P) and laezel(P) and (p.creature or getattr(p, 'walker', False)): n += 1
    if loyalty: p.loyalty += n
    else:
        p.counters += n
        if p.name == 'Exemplar of Light' and getattr(p, 'ex_turn', None) != (g.round, P.idx):
            p.ex_turn = (g.round, P.idx); P.draw(1)
        if p.name == 'Constable of the Realm':
            opp = [q for V in P.opps() for q in V.bf if q.card and not q.card.is_land and g.targetable(q, P)]
            if opp and getattr(p, 'con_turn', None) != (g.round, P.idx):
                p.con_turn = (g.round, P.idx); t = max(opp, key=lambda q: g.value(P, q))
                g.log(f'{P.label} Constable exiles {t.name}'); g.kill(t, 'exile')
    return n

def each(g, P, n=1, only=None):
    for p in list(P.creatures()):
        if only is None or only(p): add(g, p, n)

def best(g, P, pred=lambda p: True):
    cs = [p for p in P.creatures() if pred(p) and not p.neutral]
    return max(cs, key=lambda p: (g.power(p), -p.token), default=None)

# ---------------------------------------------------------------- entering the battlefield
X_COUNTERS = {'Walking Ballista': 2, 'Stonecoil Serpent': 1, 'Mikaeus, the Lunarch': 1}

def on_enter(g, P, p, c):
    """Called for every permanent P resolves, before its ETB effects."""
    if not on(P): return
    if c.is_planeswalker:
        p.walker = True; p.loyalty = 0; p.acted = -1
        base = int(getattr(c, 'loyalty_base', 0) or WALKERS.get(c.name, {}).get('start', 3))
        add(g, p, base, loyalty=True)
        # the generic walker tags (draw engine, anthem, recurring tokens) are replaced by the loyalty model below
        if c.name in WALKERS:
            cc = copy.copy(c); cc.draw_engine = 0; cc.anthem = 0; cc.overrun = None; cc.tokens_rec = None
            cc.wipe = None; cc.tokens_now = None; cc.removal = None; p.card = cc
        return
    if c.name == 'Walking Ballista' and ('Heliod, Sun-Crowned' in P.pilot.get('engine', []) or P.has('Heliod, Sun-Crowned')):
        cc = copy.copy(c); cc.removal = None; p.card = cc   # keep its counters for the Heliod combo, don't ping them away
    k = X_COUNTERS.get(c.name)
    if k:
        x = min(6, int(g.avail(P) // k))
        if x: g.pay(P, x * k)
        add(g, p, x)
    m = re.search(r'enters with (a|an|one|two|three) \+1/\+1 counters?', c.oracle)
    if m and c.is_creature: add(g, p, {'a': 1, 'an': 1, 'one': 1, 'two': 2, 'three': 3}[m.group(1)])
    if c.name == 'Angel of Invention': add(g, p, 2)   # fabricate 2: counters (tokens are tagged separately)
    if c.name in ('Ascendant Dustspeaker', 'Supply Runners', 'Daily Bugle Reporters', 'White Widow, Free Agent'):
        if c.name == 'Supply Runners': each(g, P, 1, lambda q: q is not p)
        else:
            t = best(g, P, lambda q: q is not p)
            if t: add(g, t, 1)

def on_creatures_enter(g, P, perms):
    """Cathars' Crusade: each creature entering puts a +1/+1 counter on each creature you control."""
    if not on(P): return
    n = sum(1 for x in perms if x.creature)
    if not n: return
    crusades = sum(1 for p in P.bf if p.name == "Cathars' Crusade" and not p.neutral)
    for _ in range(min(n * crusades, 12)): each(g, P, 1)

def on_gain(g, P):
    if not on(P): return
    for p in list(P.bf):
        if p.neutral: continue
        if p.name in ('Heliod, Sun-Crowned',):
            t = best(g, P)
            if t: add(g, t, 1)
        elif p.name in ('Exemplar of Light', "Ajani's Pridemate", 'Ajani Pridemate'): add(g, p, 1)
        elif p.name == 'Ajani Resolute' and getattr(p, 'walker', False): add(g, p, 1, loyalty=True)
        elif p.name == 'Way of the Mentor':
            for w in walkers(P): add(g, w, 1, loyalty=True)

def on_landfall(g, P):
    if not on(P): return
    for p in list(P.bf):
        if p.name == 'Felidar Retreat' and not p.neutral:
            if len(P.creatures()) >= 4: each(g, P, 1)
            else: g.make_tokens(P, 1, 2, 2, set(), name='Cat Beast')
        if p.name == 'Prowling Felidar' and not p.neutral: add(g, p, 1)

# ---------------------------------------------------------------- planeswalkers
def walkers(P):
    return [p for p in P.bf if getattr(p, 'walker', False)]

def emblem(P, k, v=1):
    em = P.__dict__.setdefault('emblems', {})
    em[k] = em.get(k, 0) + v

def em(P, k):
    return getattr(P, 'emblems', {}).get(k, 0)

def tok(g, P, n, pw, tg, kw=(), name='Token'):
    return g.make_tokens(P, n, pw, tg, set(kw), name=name)

def _ajani_steadfast(g, P, w):
    if w.loyalty >= 2 and len(P.creatures()) >= 3:
        w.loyalty -= 2; each(g, P, 1)
        for o in walkers(P):
            if o is not w: add(g, o, 1, loyalty=True)
        return '-2: counter on each creature'
    add(g, w, 1, loyalty=True); return '+1'

def _ajani_resolute(g, P, w):
    if w.loyalty >= 10:
        w.loyalty -= 10; emblem(P, 'pump', 2); return '-10: emblem +2/+2'
    if w.loyalty >= 7 and not any(p.name == "Ajani's Pridemate" for p in P.bf):
        w.loyalty -= 4; tok(g, P, 1, 2, 2, name="Ajani's Pridemate"); return "-4: Pridemate"
    g.gain(P, 1); return '0: gain 1'

def _ajani_unrelenting(g, P, w):
    if w.loyalty >= 2 and len(P.hand) <= 1 and len(P.creatures()) >= 4:
        w.loyalty -= 2; P.gy += P.hand; P.hand = []; P.draw(len(P.creatures())); r = '-2: wheel'
    else:
        add(g, w, 1, loyalty=True)
        for p in P.creatures(): p.pump += 1; p.sick = False
        r = '+1: team +1/+0, haste'
    tok(g, P, 1, 2, 2, name='Cadet')
    return r

def _basri(g, P, w):
    if w.loyalty >= 6 and not em(P, 'basri'):
        w.loyalty -= 6; emblem(P, 'basri'); return '-6: emblem'
    t = best(g, P)
    add(g, w, 1, loyalty=True)
    if t: add(g, t, 1)
    return '+1: counter'

def _elspeth_resplendent(g, P, w):
    if w.loyalty >= 7:
        w.loyalty -= 7; tok(g, P, 5, 3, 3, ('flying',), name='Angel'); return '-7: five 3/3 Angels'
    t = best(g, P); add(g, w, 1, loyalty=True)
    if t: add(g, t, 1); t.kw.add('flying')
    return '+1: counter + flying'

def _elspeth_sun(g, P, w):
    if w.loyalty >= 7 and not em(P, 'elspeth'):
        w.loyalty -= 7; emblem(P, 'pump', 2); emblem(P, 'elspeth'); emblem(P, 'flying'); return '-7: emblem +2/+2 flying'
    add(g, w, 1, loyalty=True); tok(g, P, 3, 1, 1, name='Soldier'); return '+1: three Soldiers'

def _wandering_emperor(g, P, w):
    big = [p for V in P.opps() for p in V.creatures() if g.power(p) >= 4 and g.targetable(p, P) and not p.neutral]
    if big and w.loyalty >= 2:
        t = max(big, key=lambda p: g.value(P, p)); w.loyalty -= 2; g.log(f'{P.label} Emperor exiles {t.name}')
        g.kill(t, 'exile'); g.gain(P, 2); return '-2: exile'
    if w.loyalty >= 4:
        w.loyalty -= 1; tok(g, P, 1, 2, 2, ('vigilance',), name='Samurai'); return '-1: Samurai'
    t = best(g, P); add(g, w, 1, loyalty=True)
    if t: add(g, t, 1)
    return '+1: counter'

def _gideon(g, P, w):
    if not em(P, 'gideon') and w.loyalty >= 4:
        w.loyalty -= 4; emblem(P, 'pump', 1); emblem(P, 'gideon'); return '-4: emblem +1/+1'
    tok(g, P, 1, 2, 2, name='Knight Ally'); return '0: 2/2 Knight'

def _jace(g, P, w):
    if w.loyalty >= 3: w.loyalty -= 3; P.draw(1); return '-3: draw'
    w.loyalty -= 1; return '-1: surveil'

WALKERS = {
    'Ajani Steadfast': dict(start=4, act=_ajani_steadfast),
    'Ajani Resolute': dict(start=2, act=_ajani_resolute),
    'Ajani Unrelenting': dict(start=5, act=_ajani_unrelenting),
    'Basri Ket': dict(start=3, act=_basri),
    'Elspeth Resplendent': dict(start=5, act=_elspeth_resplendent),
    "Elspeth, Sun's Champion": dict(start=4, act=_elspeth_sun),
    'The Wandering Emperor': dict(start=3, act=_wandering_emperor),
    'Gideon, Ally of Zendikar': dict(start=4, act=_gideon),
}

def precombat(g, P):
    """Your main phase before combat: loyalty abilities, then beginning-of-combat counter triggers."""
    if not on(P): return
    for w in walkers(P):
        if w.acted == g.round or w not in P.bf: continue
        spec = WALKERS.get(w.name)
        if not spec: continue
        w.acted = g.round
        r = spec['act'](g, P, w)
        g.log(f'{P.label} {w.name} {r} (loyalty {w.loyalty})'); P.stats['loyalty_acts'] += 1
        if w.loyalty <= 0: g.kill(w, 'sba')
    # tap abilities and beginning of combat
    for p in list(P.bf):
        if p.neutral or p not in P.bf: continue
        n = p.name
        if n == 'Luminarch Aspirant':
            t = best(g, P)
            if t: add(g, t, 1)
        elif n == 'Mikaeus, the Lunarch' and not p.tapped and not p.sick:
            p.tapped = True
            if p.counters >= 1 and len(P.creatures()) >= 3:
                p.counters -= 1; each(g, P, 1, lambda q: q is not p)
            else: add(g, p, 1)
        elif n == 'Steel Overseer' and not p.tapped and not p.sick:
            p.tapped = True; each(g, P, 1, lambda q: q.card is not None and q.card.is_artifact or q.name in ('Servo', 'Gnome', 'Thopter'))
        elif n in ('Ainok Bond-Kin', 'Abzan Falconer') and p.counters == 0 and not p.sick and g.avail(P) >= 2:
            g.pay(P, 2 if n == 'Ainok Bond-Kin' else 1); p.tapped = True; add(g, p, 1)
        elif n == 'The Ozolith' and getattr(p, 'ozo', 0):
            t = best(g, P)
            if t: add(g, t, p.ozo); p.ozo = 0
    if em(P, 'basri'):
        tok(g, P, 1, 1, 1, name='Soldier'); each(g, P, 1)
    combo(g, P)

def combo(g, P):
    """Heliod, Sun-Crowned + Walking Ballista: give Ballista lifelink ({1}{W}), then ping/gain/counter forever.
    A Ballista cast for X=0 enters with no counters, so Lae'zel can't save it (it adds to counters being placed)."""
    if not on(P): return
    if P.has('Heliod, Sun-Crowned') and any(p.name == 'Walking Ballista' and p.counters for p in P.bf) and g.avail(P) >= 2:
        g.pay(P, 2); g.win_all(P, 'combo: Heliod, Sun-Crowned + Walking Ballista')

def on_leave(g, p):
    """The Ozolith keeps the counters of creatures that leave."""
    P = p.owner
    if not on(P) or not p.creature or not p.counters: return
    for o in P.bf:
        if o.name == 'The Ozolith' and not o.neutral: o.ozo = getattr(o, 'ozo', 0) + p.counters; return

# ---------------------------------------------------------------- combat
def on_attack(g, A, D, atk):
    if not on(A): return
    cmd = [a for a in atk if a.is_cmd]
    if cmd and A.has('Guild Artisan') and all(D.life >= q.life for q in A.opps()):
        A.treasure += 2; A.stats['artisan_treasure'] += 2
    for a in atk:
        if a.name == 'Laelia, the Blade Reforged':
            if A.lib: A.draw(1)
            add(g, a, 1)
        if a.name == 'Anim Pakal, Thousandth Moon': add(g, a, 1)
        if a.name == 'Legion Warboss':
            t = [x for x in atk if g.power(x) < g.power(a)]
            if t: add(g, t[0], 1)

def divert_to_walker(g, A, D, n):
    """Attackers send some damage at the defender's planeswalkers. Returns damage still going to the player."""
    if not on(D): return n
    ws = walkers(D)
    if not ws or g.rng.random() > 0.5 or D.life <= n * 2: return n
    w = max(ws, key=lambda p: p.loyalty)
    k = min(n, w.loyalty); w.loyalty -= k
    if w.loyalty <= 0: g.log(f'{A.label} kills {D.label} {w.name}'); g.kill(w, 'damage')
    return n - k

def on_hit(g, A, D, a):
    if not on(A): return
    if a.name == 'Grateful Apparition':
        for p in A.bf:
            if p.creature and p.counters: add(g, p, 1)
            elif getattr(p, 'walker', False): add(g, p, 1, loyalty=True)

# ---------------------------------------------------------------- statics
def kw(g, p, k):
    P = p.owner
    if not on(P): return k
    if p.creature and p.counters:
        if P.has('Abzan Falconer'): k.add('flying')
        if P.has('Ainok Bond-Kin') or (P.has('Inspiring Paladin') and g.active is P): k.add('first strike')
    if p.creature and em(P, 'flying'): k.add('flying')
    return k

def pump(P, p):
    return em(P, 'pump') if p.creature and on(P) else 0
