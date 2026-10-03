"""4-player Commander game engine (abstracted). Opponents play their real decklists by card role."""
import random, collections, math, re
try:
    from . import cards as CD
except ImportError:
    import cards as CD

ME = 'The Serpent Society'  # commander with a hand-coded trigger (deathtouch death -> nontoken edicts)
SYM_STAX = {'Cursed Totem', 'Collector Ouphe', 'Winter Orb', 'Rest in Peace', 'Hushbringer', 'Archon of Emeria',
            'Thalia, Guardian of Thraben', 'Deafening Silence', 'Sphere of Resistance'}
COMBAT_DRAW_ALL = {'Ohran Frostfang', 'Toski, Bearer of Secrets'}
ATTACK_TOKENS = {'Adeline, Resplendent Cathar': 'opps', 'Rabble Rousing': 'attackers', 'Krenko, Tin Street Kingpin': 2,
                 'Myrel, Shield of Argive': 2, 'Anim Pakal, Thousandth Moon': 2, 'Elspeth, Storm Slayer': 0}
NONTOKEN_EDICT_SPELLS = {"Sheoldred's Edict"}
FLYER_EDICT_SPELLS = {'Pick Your Poison'}
BITE = {'Devouring Tendrils', 'Wolf Strike', 'Punishing Punch'}
CODIE = 'Codie, Ravenous Codex'
CREATURE_MANA = {'Cryptolith Rite', 'Elven Chorus', 'Enduring Vitality'}   # creatures you control tap for any color
LOOP_PAYOFFS = {'Flaming Tyrannosaurus', 'Impending Flux', 'Stensian Sanguinist', 'Emeritus of Conflict'}

class Perm:
    _id = 0
    def __init__(s, owner, card=None, token=None, is_cmd=False):
        Perm._id += 1; s.id = Perm._id
        s.owner = owner; s.card = card; s.is_cmd = is_cmd
        if card:
            s.name = card.name; s.bp, s.bt = card.power, card.toughness; s.kw = set(card.kw); s.token = False
            s.creature = card.is_creature
        else:
            s.name, s.bp, s.bt, kw = token; s.kw = set(kw); s.token = True; s.creature = True
        s.tapped = False; s.sick = True; s.counters = 0; s.pump = 0; s.pumpt = 0; s.tmpkw = set()
        s.auras = 0; s.aura_p = 0; s.aura_t = 0; s.aura_kw = set(); s.neutral = False; s.infect_turn = False
        s.slime = 0; s.rankled = False; s.prepared = False
    @property
    def c(s): return s.card
    def is_art(s): return s.card is not None and s.card.is_artifact
    def is_ench(s): return s.card is not None and s.card.is_enchantment
    def __repr__(s): return f'{s.name}'

class Player:
    def __init__(s, g, idx, label, deck, is_me, group, bracket, pilot=None):
        s.g = g; s.idx = idx; s.label = label; s.is_me = is_me; s.group = group; s.bracket = bracket
        s.pilot = pilot or {}
        cmd_name = deck[0]; s.cmd_card = CD.get(cmd_name)
        s.lib = [CD.get(n) for n in deck[1:]]; g.rng.shuffle(s.lib)
        s.hand = []; s.gy = []; s.bf = []; s.lands = 0; s.lands_named = 0
        s.life = 40; s.poison = 0; s.cmd_dmg = collections.Counter(); s.alive = True
        s.cmd_zone = True; s.cmd_tax = 0; s.pool = 0; s.reserve = 0; s.treasure = 0
        s.spells_turn = 0; s.noncre_turn = 0; s.land_drops = 1; s.exp = 0; s.quest = 0
        s.approach = 0; s.flashback = False; s.lathril_used = False; s.died = None
        s.combo_names = [cb for cb in CD.COMBOS if all(any(c.name == p for c in s.lib) or p == cmd_name for p in cb)]
        s.stats = collections.Counter(); s.cast_log = []
        s.mulligan()
    # ------------- basics
    def creatures(s): return [p for p in s.bf if p.creature]
    def perms(s): return s.bf
    def opps(s): return [p for p in s.g.players if p is not s and p.alive]
    def has(s, name): return any(p.name == name for p in s.bf)
    def count(s, name): return sum(1 for p in s.bf if p.name == name)
    def cmd_on_bf(s): return any(p.is_cmd for p in s.bf)
    def draw(s, n=1):
        g = s.g
        for _ in range(int(n)):
            if not s.lib:
                if s.has('Laboratory Maniac') or s.has("Thassa's Oracle") or s.has('Jace, Wielder of Mysteries'):
                    g.win_all(s, 'empty-library win'); return
                g.eliminate(s, 'decked', None); return
            s.hand.append(s.lib.pop())
            g.on_draw(s)
    def mulligan(s):
        for att in range(3):
            s.draw(7)
            nl = sum(1 for c in s.hand if c.is_land)
            if 2 <= nl <= 5 or att == 2: break
            s.lib += s.hand; s.hand = []; s.g.rng.shuffle(s.lib)
        if att == 2:
            sp = [c for c in s.hand if not c.is_land]
            if sp: w = max(sp, key=lambda c: c.cmc); s.hand.remove(w); s.lib.insert(0, w)

class Game:
    def __init__(s, specs, rng, log=False, max_rounds=25):
        s.rng = rng; s.logging = log; s.events = []; s.max_rounds = max_rounds
        s.players = [Player(s, i, *sp) for i, sp in enumerate(specs)]
        rng.shuffle(s.players)
        for i, p in enumerate(s.players): p.seat = i
        s.round = 0; s.active = None; s.winner = None; s.over = False; s.elim = []
        s.death_depth = 0; s._lp = False
        s.doran = False; s.assault = set(); s.tox_owners = []

    def log(s, msg):
        if s.logging: s.events.append(f'T{s.round} {msg}')

    # ---------------------------------------------------------------- stax helpers
    def stax_on(s, player, flag):
        """Is a stax effect with this flag affecting `player`?"""
        for q in s.players:
            if not q.alive: continue
            for p in q.bf:
                if p.card and p.card.stax.get(flag) and not p.neutral:
                    if q is not player or p.name in SYM_STAX: return p.card.stax[flag]
        return 0
    def no_dies(s): return any(q.alive and q.has('Rest in Peace') for q in s.players)
    def no_triggers(s): return any(q.alive and any(p.name == 'Hushbringer' and not p.neutral for p in q.bf) for q in s.players)

    # ---------------------------------------------------------------- commander-specific statics
    def update_static(s):
        alive = [q for q in s.players if q.alive]
        s.doran = any(p.name == 'Doran, the Siege Tower' and not p.neutral for q in alive for p in q.bf)
        s.assault = {q.idx for q in alive if any(p.name == 'Assault Formation' and not p.neutral for p in q.bf)}
        s.tox_owners = [q for q in alive if any(p.name == 'Toxrill, the Corrosive' and not p.neutral for p in q.bf)]
    def slime_on(s, p): return p.slime and any(q is not p.owner for q in s.tox_owners)

    def sba(s):
        """State-based actions: creatures with toughness 0 or less die."""
        for q in s.players:
            if not q.alive: continue
            for p in [p for p in q.bf if p.creature and s.tough(p) <= 0]:
                if p in q.bf: s.kill(p, 'sac', sac=True)

    def toxrill_end_step(s):
        if not s.tox_owners or s.no_triggers() and False: return
        for T in s.tox_owners:
            for V in T.opps():
                for p in V.creatures(): p.slime += 1
        s.sba()

    def prowess(s, S, c):
        """Prowess (+1/+1 per noncreature spell), Bria granting it and an unblockable creature, Balmor's team pump."""
        bria = any(p.name == 'Bria, Riptide Rogue' and not p.neutral for p in S.bf)
        balmor = (c.is_instant or c.is_sorcery) and sum(1 for p in S.bf if p.name == 'Balmor, Battlemage Captain' and not p.neutral)
        for p in S.creatures():
            if p.neutral: continue
            if bria or 'prowess' in p.kw: p.pump += 1; p.pumpt += 1
            if balmor: p.pump += balmor; p.tmpkw.add('trample')
        if bria:
            cand = [p for p in S.creatures() if 'unblockable' not in p.tmpkw and not p.neutral and 'defender' not in p.kw]
            if cand: max(cand, key=lambda p: s.power(p)).tmpkw.add('unblockable')

    def discard(s, V, src=None):
        if not V.hand: return None
        lands = [c for c in V.hand if c.is_land]
        c = lands[0] if len(lands) >= 2 else min(V.hand, key=lambda x: (x.is_land, x.cmc))
        V.hand.remove(c); V.gy.append(c)
        for q in s.players:
            if not q.alive or q is V: continue
            for p in q.bf:
                if p.neutral: continue
                if p.name in ('Megrim', "Liliana's Caress"): s.lose_life(V, 2, q, 'discard')
                if p.name == 'Waste Not':
                    if c.is_creature: s.make_tokens(q, 1, 2, 2, set(), name='Zombie')
                    elif c.is_land: q.reserve += 2
                    else: q.draw(1)
        return c

    def rankle(s, A, rk):
        others = A.opps()
        # sacrifice mode: only when Rankle's controller has fodder of its own
        fod = [p for p in A.creatures() if p is not rk and (p.token or (p.card and s.value(A, p) < 3.5 and p.name not in s.eng(A)))]
        if fod and any(q.creatures() for q in others):
            s.kill(min(fod, key=lambda p: (not p.token, s.value(A, p))), 'sac', sac=True)
            for v in others: s.force_sac(v, src=A, why='rankle')
        if A.life >= 10:
            for q in [A] + others:
                if q.alive: s.lose_life(q, 1, A if q is not A else None, 'rankle'); q.draw(1)
        if len(A.hand) <= 1 or any(A.has(n) for n in ('Waste Not', 'Megrim', "Liliana's Caress")):
            for q in [A] + others:
                if q.alive: s.discard(q, A)
        A.stats['rankle_triggers'] += 1
        s.log(f'{A.label} Rankle trigger')

    # ---------------------------------------------------------------- stats of permanents
    def power(s, p):
        o = p.owner
        if p.creature and (s.doran or o.idx in s.assault):
            return 0 if p.neutral else max(0, s.tough(p))
        v = p.bp + p.counters + p.pump + p.aura_p
        if p.slime and s.slime_on(p): v -= p.slime
        if p.creature:
            v += sum(q.card.anthem for q in o.bf if q.card and q.card.anthem and q is not p and not q.neutral)
            if o.cmd_card.name == 'Jetmir, Nexus of Revels' and o.cmd_on_bf() and len(o.creatures()) >= 3: v += 1
            if p.name == 'Serra Ascendant' and o.life >= 30: v += 5
            m = s.stax_on(o, 'opp_minus')
            if m: v -= m
        if p.neutral: v = 0
        return max(0, v)
    def tough(s, p):
        o = p.owner; v = p.bt + p.counters + p.pumpt + p.aura_t
        if p.slime and s.slime_on(p): v -= p.slime
        if p.creature:
            v += sum(q.card.anthem for q in o.bf if q.card and q.card.anthem and q is not p and not q.neutral)
            m = s.stax_on(o, 'opp_minus')
            if m: v -= m
        if p.neutral: v = 1
        return v
    def kw(s, p):
        k = set(p.kw) | p.aura_kw | p.tmpkw
        o = p.owner
        if p.token and o.cmd_card.name == 'Teysa Karlov' and o.cmd_on_bf(): k |= {'lifelink', 'vigilance'}
        if o.cmd_card.name == 'Jetmir, Nexus of Revels' and o.cmd_on_bf():
            n = len(o.creatures())
            if n >= 3: k.add('vigilance')
            if n >= 6: k.add('trample')
            if n >= 9: k.add('double strike')
        if o.has("Garruk's Uprising"): k.add('trample')
        if p.neutral: k = set()
        return k
    def has_dt(s, p): return 'deathtouch' in s.kw(p)
    def targetable(s, p, src_player, src_card=None):
        if p.owner is src_player: return True
        k = s.kw(p)
        if 'hexproof' in k or 'shroud' in k: return False
        if 'ward_poison' in k: return False
        if 'pro_bg' in k and src_card is not None and (src_card.colors & {'B', 'G'}): return False
        if p.is_cmd and p.owner.has('Swiftfoot Boots') or p.is_cmd and p.owner.has('Lightning Greaves'): return False
        if p.owner.has('Mother of Runes') and p.creature and s.rng.random() < .5: return False
        return True

    # ---------------------------------------------------------------- value of permanents (for AI)
    def value(s, viewer, p):
        c = p.card; o = p.owner
        if c is None:
            v = 0.6 * s.power(p) + 0.3
            if 'deathtouch' in p.kw and o.cmd_on_bf() and o.cmd_card.name == ME: v -= 0.5
            return v
        v = 0.5 * c.cmc
        if p.creature: v += s.power(p) * 0.8 + s.tough(p) * 0.2
        v += c.draw_engine * 4 + c.rock * 1.5 + c.anthem * 3 + (6 if c.overrun else 0) + (4 if c.tokens_rec else 0)
        if c.death_trig:
            v += 7 if c.death_trig.get('edict') else 3
        if c.life_trig: v += 5
        if c.spell_trig and c.spell_trig.get('drain_each'): v += 4
        if c.alt_win: v += 10
        if c.free_outlet: v += 2
        if c.stax and viewer is not o:
            hurt = 0
            for f in c.stax:
                if f in ('no_triggers', 'no_dies') and viewer.is_me: hurt += 12
                elif f in ('no_creature_abilities', 'no_artifact_abilities', 'no_cmd_cast') and viewer.is_me: hurt += 6
                else: hurt += 4
            v += hurt
        if any(c.name in cb for cb in o.combo_names): v += 10
        if p.is_cmd: v += 5 + p.auras * 2
        if o.cmd_card.name == 'Light-Paws, Emperor\'s Voice' and p.is_cmd: v += 6
        v += o.pilot.get('value_bonus', {}).get(c.name, 0)
        if o.cmd_card.name == ME and p.creature and 'deathtouch' in s.kw(p) and o.cmd_on_bf(): v -= 3   # killing it triggers the commander
        return v

    def threat(s, viewer, q):
        """How dangerous player q looks to viewer (archenemy logic)."""
        t = sum(s.power(p) for p in q.creatures()) * 0.5
        t += sum(s.value(viewer, p) for p in q.bf if not p.creature) * 0.3
        t += 8 * sum(1 for cb in q.combo_names if sum(1 for n in cb if q.has(n)) >= len(cb) - 1)
        t += max(0, (40 - q.life)) * -0.1
        if q.is_me and q.cmd_on_bf(): t += 3
        return t

    # ---------------------------------------------------------------- costs & mana
    def cost(s, P, c, is_cmd=False):
        x = c.cmc + (P.cmd_tax if is_cmd else 0)
        x += s.stax_on(P, 'tax_all')
        if not c.is_creature: x += s.stax_on(P, 'tax_noncreature')
        if c.is_artifact or c.is_enchantment: x += s.stax_on(P, 'tax_artench')
        cn = P.cmd_card.name
        if cn == 'Grand Arbiter Augustin IV' and P.cmd_on_bf() and (c.colors & {'W', 'U'}): x -= 1
        if cn == 'Baral, Chief of Compliance' and P.cmd_on_bf() and (c.is_instant or c.is_sorcery): x -= 1
        for med, col in (('Ruby Medallion', 'R'), ('Sapphire Medallion', 'U'), ('Pearl Medallion', 'W')):
            if P.has(med) and col in c.colors: x -= 1
        if c.name == 'Punishing Punch' and sum(1 for g in P.gy if g.is_creature) >= 2: x -= 2
        if c.name == 'Blasphemous Act': x -= sum(len(q.creatures()) for q in s.players if q.alive)
        return max(x, c.pips if c.cmc else 0, 0)

    def mana_avail(s, P):
        lands = P.lands
        if s.stax_on(P, 'winter_orb'): lands = min(lands, 2)
        m = lands + sum(1 for c in [] )
        ouphe = s.stax_on(P, 'no_artifact_abilities'); totem = s.stax_on(P, 'no_creature_abilities')
        for p in P.bf:
            if not p.card or p.neutral: continue
            r = p.card.rock
            if not r: continue
            if p.creature and (p.sick and 'haste' not in s.kw(p) or totem): continue
            if p.card.is_artifact and ouphe: continue
            if p.name in ('Priest of Titania', 'Elvish Archdruid', 'Circle of Dreams Druid', 'Wirewood Channeler', 'Marwyn, the Nurturer'):
                r = max(1, min(6, len(P.creatures()) // 2))
            m += r
            if P.cmd_card.name == 'Kinnan, Bonder Prodigy' and P.cmd_on_bf(): m += 1
        if P.has("Gaea's Cradle"): m += len(P.creatures()) - 1
        if not totem and any(p.name in CREATURE_MANA and not p.neutral for p in P.bf):
            m += sum(1 for p in P.creatures() if not p.neutral and not (p.card and p.card.rock) and (not p.sick or 'haste' in s.kw(p)))
        if P.has('Smothering Tithe'): m += 1
        return max(0, m)

    def pay(s, P, x):
        if P.pool >= x: P.pool -= x; return True
        if P.pool + P.treasure >= x: P.treasure -= x - P.pool; P.pool = 0; return True
        return False
    def avail(s, P): return P.pool + P.treasure

    # ---------------------------------------------------------------- life / damage
    def lose_life(s, V, n, src=None, why=''):
        if not V.alive or n <= 0: return
        V.life -= n
        if src is not None and src is not V:
            src.stats['dmg_dealt'] += n; src.stats['dmg_' + why] += n; V.last_src = (src, why)
        for q in s.players:
            if q.alive and q is not V and q.has('Exquisite Blood') and not s.over:
                if s.death_depth >= 12:
                    s.win_all(q, 'combo: Exquisite Blood life loop'); return
                s.death_depth += 1; s.gain(q, n); s.death_depth -= 1
    def gain(s, P, n):
        if not P.alive or n <= 0: return
        if P.has('Rhox Faithmender'): n *= 2
        if P.has("Alhammarret's Archive"): n *= 2
        P.life += n
        for p in list(P.bf):
            lt = p.card.life_trig if p.card else None
            if not lt or p.neutral: continue
            opps = P.opps()
            if not opps: break
            if lt.get('drain_equal'):
                t = min(opps, key=lambda q: q.life); s.lose_life(t, n, P, 'lifegain')
            if lt.get('drain_each'):
                for q in opps: s.lose_life(q, lt['drain_each'], P, 'lifegain')
            if lt.get('draw'): P.draw(1 if s.rng.random() < .5 else 0)
        if P.cmd_card.name == 'Oloro, Ageless Ascetic' and P.cmd_on_bf() and P.pool + P.treasure >= 1 and s.rng.random() < .6:
            s.pay(P, 1); P.draw(1)
            for q in P.opps(): s.lose_life(q, 1, P, 'lifegain')
        for p in P.bf:
            if p.name in ("Ajani's Pridemate", 'Heliod, Sun-Crowned', 'Karlov of the Ghost Council', 'Exemplar of Light'):
                p.counters += 1

    # ---------------------------------------------------------------- tokens
    def make_tokens(s, P, n, pw, tg, kw, name='Token', tapped=False):
        if s.no_triggers() and False: return []
        if n == 'each': n = max(1, P.lands if name == 'Plant' else len(P.creatures()))
        dbl = sum(1 for p in P.bf if p.card and p.card.token_double)
        n = int(n) * (2 ** min(dbl, 3))
        n = min(n, max(0, 80 - len(P.creatures())))
        out = []
        for _ in range(n):
            t = Perm(P, token=(name, pw, tg, set(kw)))
            if tapped or s.stax_on(P, 'opp_enter_tapped'): t.tapped = True
            P.bf.append(t); out.append(t)
        P.stats['tokens'] += n
        if out: s.etb_triggers(P, out)
        return out

    # ---------------------------------------------------------------- deaths
    def kill(s, p, cause='destroy', sac=False):
        """Creature/permanent leaves battlefield to graveyard (dies)."""
        o = p.owner
        if p not in o.bf: return
        if not sac and 'indestructible' in s.kw(p) and cause in ('destroy', 'damage', 'deathtouch'): return
        was_dt = s.has_dt(p) or o.has('Archetype of Finality')
        was_cre = p.creature
        o.bf.remove(p)
        if p.name in ('Doran, the Siege Tower', 'Assault Formation', 'Toxrill, the Corrosive'): s.update_static()
        if p.is_cmd:
            o.cmd_zone = True; o.cmd_tax += 2
        elif p.card:
            if s.no_dies(): pass
            else: o.gy.append(p.card)
        if was_cre: s.on_creature_dies(p, was_dt)

    def on_creature_dies(s, p, was_dt):
        if s.no_dies() or s.no_triggers(): return
        o = p.owner
        if s.death_depth > 250: return
        s.death_depth += 1
        try:
            for q in s.players:
                if not q.alive: continue
                teysa = 2 if (q.cmd_card.name == 'Teysa Karlov' and q.cmd_on_bf()) else 1
                for perm in list(q.bf):
                    c = perm.card
                    if c is None or perm.neutral: continue
                    # The Serpent Society
                    if c.name == ME and q is o and was_dt and p is not perm:
                        q.stats['cmd_triggers'] += 1
                        for _ in range(teysa):
                            for v in q.opps():
                                s.force_sac(v, nontoken=True, src=q, why='commander')
                        continue
                    if c.name == 'Toxrill, the Corrosive' and o is not q and p.slime:
                        s.make_tokens(q, 1, 1, 1, set(), name='Slug'); continue
                    if c.name == 'Massacre Wurm' and o is not q:
                        s.lose_life(o, 2, q, 'wurm'); continue
                    if c.name == 'Meren of Clan Nel Toth' and o is q and p is not perm: q.exp += 1
                    dt = c.death_trig
                    if not dt: continue
                    sc = dt.get('scope')
                    if sc == 'self' and perm is not p: continue
                    if sc == 'own' and o is not q: continue
                    if sc == 'opp' and o is q: continue
                    if sc in ('own', 'any') and perm is p and c.name not in ('Blood Artist',): continue
                    if dt.get('nontoken') and p.token: continue
                    for _ in range(teysa):
                        s.apply_effect(q, dt, why='death')
            # the dying card's own "when ~ dies" handled above via scope self only if still referenced
            if p.card and p.card.death_trig and p.card.death_trig.get('scope') == 'self':
                s.apply_effect(o, p.card.death_trig, why='death')
        finally:
            s.death_depth -= 1

    def apply_effect(s, q, e, why=''):
        opps = q.opps()
        if e.get('drain_each'):
            for v in opps: s.lose_life(v, e['drain_each'], q, why)
        if e.get('drain_one') and opps:
            v = min(opps, key=lambda x: x.life); s.lose_life(v, e['drain_one'], q, why)
        if e.get('life'): s.gain(q, e['life'])
        if e.get('draw'): q.draw(e['draw'] if s.rng.random() < .8 else 0)
        if e.get('edict'):
            for v in opps: s.force_sac(v, nontoken=False, src=q, why='pact')
        if e.get('mana'):
            q.treasure += 1
        if e.get('token'):
            n, pw, tg, kw = e['token']; s.make_tokens(q, n if n != 'each' else 1, pw, tg, kw)

    def force_sac(s, V, nontoken=False, src=None, why='edict', flying=False):
        cands = [p for p in V.creatures() if (not nontoken or not p.token) and (not flying or 'flying' in s.kw(p))]
        if not cands: return None
        if V.is_me:
            def key(p):
                k = 0 if p.token else 1
                if s.has_dt(p): k -= .5
                if p.name in s.eng(V): k += 3
                if p.is_cmd: k += 10
                return (k, s.value(V, p))
        else:
            def key(p): return (0 if p.token else 1, s.value(V, p) + (8 if p.is_cmd else 0))
        p = min(cands, key=key)
        if src is not None: src.stats['edict_kills'] += 1; src.stats['edict_' + why] += 1
        s.kill(p, 'sac', sac=True)
        return p

    # ---------------------------------------------------------------- triggers
    def etb_triggers(s, P, perms):
        if s.no_triggers(): return
        for perm in P.bf:
            d = getattr(perm.card, 'draw_once', None) if perm.card else None
            if not d or perm.neutral or getattr(perm, 'once_turn', -1) == (s.round, s.active.idx if s.active else 0): continue
            ok = any((d == 'token' and x.token) or (d == 'small' and s.power(x) <= 2 and x is not perm)
                     or (d == 'mv3' and (x.token or (x.card and x.card.cmc <= 3))) for x in perms if x.creature)
            if ok: perm.once_turn = (s.round, s.active.idx if s.active else 0); P.draw(1)
        for q in s.players:
            if not q.alive: continue
            for perm in q.bf:
                e = perm.card.etb_trig if perm.card else None
                if not e or perm.neutral: continue
                if e.get('own') and q is not P: continue
                for _ in perms:
                    s.apply_effect(q, {k: v for k, v in e.items() if k != 'edict'}, why='etb')

    def on_draw(s, P):
        if not P.alive or not hasattr(s, 'players'): return
        for q in s.players:
            if q.alive and q.has('Sheoldred, the Apocalypse'):
                if q is P: s.gain(P, 2)
                else: s.lose_life(P, 2, q, 'sheoldred')
        for p in P.bf:
            if p.name in ('Niv-Mizzet, Parun', 'Niv-Mizzet, the Firemind') and not p.neutral:
                s.ping(P, 1)
            if p.name == 'Psychosis Crawler':
                for v in P.opps(): s.lose_life(v, 1, P, 'draw')

    def ping(s, P, n):
        opps = P.opps()
        if not opps: return
        # kill a key 1-toughness non-deathtouch creature, else face the lowest-life opponent
        tgts = [p for v in opps for p in v.creatures() if not s.has_dt(p) and s.tough(p) <= n and s.targetable(p, P) and s.value(P, p) > 2]
        if tgts and s.rng.random() < .5:
            t = max(tgts, key=lambda p: s.value(P, p)); s.kill(t, 'damage')
        else:
            v = min(opps, key=lambda x: x.life); s.lose_life(v, n, P, 'ping')

    def spell_triggers(s, S, c, nonhand=False):
        if nonhand and not s.no_triggers(): s.nonhand_triggers(S, c)
        if c.is_creature: return
        S.spells_turn += 1
        s.prepare_triggers(S, c)
        s.prowess(S, c)
        for q in s.players:
            if not q.alive: continue
            for p in q.bf:
                st = p.card.spell_trig if p.card else None
                if p.name in ('Niv-Mizzet, Parun',) and (c.is_instant or c.is_sorcery) and not p.neutral:
                    q.draw(1)
                if not st or p.neutral or p.name in ('Rhystic Study', 'Mystic Remora'): continue
                who = st.get('who')
                if who == 'self' and q is not S: continue
                if who == 'opp' and q is S: continue
                if st.get('noncreature') and c.is_creature: continue
                s.apply_effect(q, st, why='spell')
                if p.name == 'Aetherflux Reservoir' and q is S: s.gain(q, S.spells_turn)
        k = s.stax_on(S, 'spell_ping')
        if k: s.lose_life(S, k, None, 'kambal')

    # ---------------------------------------------------------------- prepare (Secrets of Strixhaven) + Codie, Ravenous Codex
    def prep_perms(s, P, prepared=None):
        return [p for p in P.creatures() if p.card and getattr(p.card, 'prep_card', None) and not p.neutral
                and (prepared is None or p.prepared == prepared)]

    def prepare_triggers(s, S, c):
        """Noncreature spell cast by S: third-spell preparers, Displacer Kitten flickers, untappers, Song of Creation."""
        if s.no_triggers(): return
        if S.spells_turn + S.stats['cre_cast_turn'] == 3:
            for p in s.prep_perms(S, False):
                if p.card.prep_third: p.prepared = True
        for k in [p for p in S.bf if p.name == 'Displacer Kitten' and not p.neutral]:
            cand = [p for p in s.prep_perms(S, False) if p.card.prep_enter]
            if cand:
                t = max(cand, key=lambda p: s.prep_value(S, p.card.prep_card))
                t.prepared = True; t.sick = True; t.tapped = False; S.stats['kitten_blinks'] += 1
        if s.active is S:
            for p in S.bf:
                if p.name == 'Chakram Retriever' and not p.neutral:
                    cd = next((q for q in S.creatures() if q.name == CODIE and q.tapped), None) or \
                         next((q for q in S.creatures() if q.tapped and q.card and q.card.rock), None)
                    if cd: cd.tapped = False
            if any(p.name == 'Jeskai Ascendancy' and not p.neutral for p in S.bf):
                for q in S.creatures(): q.tapped = False; q.pump += 1; q.pumpt += 1
                if any(p.name in CREATURE_MANA and not p.neutral for p in S.bf) and getattr(S, 'asc_mana', 0) < 40:
                    n = min(8, len(S.creatures())); S.pool += n; S.asc_mana = getattr(S, 'asc_mana', 0) + n
        if any(p.name == 'Song of Creation' and not p.neutral for p in S.bf): S.draw(2)

    def nonhand_triggers(s, S, c):
        """'Whenever you cast a spell from anywhere other than your hand' (prepare spells are cast from exile)."""
        S.nonhand_turn = getattr(S, 'nonhand_turn', 0) + 1
        for p in list(S.bf):
            if p.neutral: continue
            if p.name == 'Vega, the Watcher': S.draw(1)
            elif p.name == 'Flaming Tyrannosaurus': s.ping(S, 3); p.counters += 1
            elif p.name == 'Kellan, the Kid':
                perm = [x for x in S.hand if not x.is_land and (x.is_creature or x.is_artifact or x.is_enchantment) and x.cmc <= c.cmc]
                if perm:
                    x = max(perm, key=lambda x: x.cmc); S.hand.remove(x); s.log(f'{S.label} Kellan puts in {x.name}'); s.resolve(S, x)
        s.check_deaths(S, 'burn')

    def prep_value(s, P, c):
        if c.ritual or c.tutor or c.draw_now >= 2 or c.drain_now or getattr(c, 'special', None) in ('reanimate',): return 3
        if c.removal or c.draw_now or getattr(c, 'treasure_now', 0) or c.ramp_lands: return 2
        return 0

    def codie_copies(s, P):
        if s.no_triggers(): return 0
        n = sum(1 for p in P.bf if p.name == CODIE and not p.neutral)
        if not n: return 0
        if any(p.name == 'Annie Joins Up' and not p.neutral for p in P.bf): n *= 2   # Codie is a legendary creature
        if any(p.card and getattr(p.card, 'special', None) == 'twinning' and not p.neutral for p in P.bf): n += 1
        return n

    def codie_activate(s, P):
        """{W}{U}{B}{R}{G}, {T}: each creature you control becomes prepared. Used when it re-arms enough value."""
        if s.stax_on(P, 'no_creature_abilities') or getattr(P, 'codie_acts', 0) >= 4: return False
        cd = next((p for p in P.creatures() if p.name == CODIE and not p.tapped and not p.neutral and (not p.sick or 'haste' in s.kw(p))), None)
        if cd is None or s.avail(P) < 5: return False
        un = s.prep_perms(P, False)
        val = sum(s.prep_value(P, p.card.prep_card) for p in un)
        ritual = any(p.card.prep_card.ritual for p in un)
        if val < 5 and not (ritual and s.avail(P) >= 8): return False
        s.pay(P, 5); cd.tapped = True; P.codie_acts = getattr(P, 'codie_acts', 0) + 1; P.stats['codie_acts'] += 1
        for p in un: p.prepared = True
        s.log(f'{P.label} activates Codie: {len(un)} creatures prepared')
        return True

    def prep_upkeep(s, P):
        for p in s.prep_perms(P, False):
            u = p.card.prep_upkeep
            if u == 'always' or (u == 'gy3' and sum(1 for g in P.gy if g.is_creature or g.is_artifact) >= 3): p.prepared = True

    def prep_tap2(s, P):
        keep = set(P.pilot.get('keep_home', [])) | {CODIE}
        for p in s.prep_perms(P, False):
            if not p.card.prep_tap2 or p.tapped or p.sick: continue
            others = [q for q in s.untapped(P) if q is not p and q.name not in keep and not (q.card and q.card.rock)]
            if len(others) >= 2:
                p.tapped = True
                for q in others[:2]: q.tapped = True
                p.prepared = True

    def cast_prep(s, P, perm):
        c = perm.card.prep_card
        if not s.pay(P, s.cost(P, c)): return False
        perm.prepared = False
        P.noncre_turn += 1; P.cast_log.append((s.round, c.name)); P.stats['spells'] += 1; P.stats['prep_casts'] += 1
        P.cur_x = 0
        s.spell_triggers(P, c, nonhand=True)
        if s.try_counter(P, c): return True
        s.spell_effect(P, c)
        for _ in range(s.codie_copies(P)):
            if s.over or not P.alive: break
            P.stats['codie_copies'] += 1; s.magecraft(P); s.spell_effect(P, c, copy=True)
        return True

    def prep_options(s, P, score):
        out = []
        for p in s.prep_perms(P, True):
            c = p.card.prep_card
            if not (c.is_instant or c.is_sorcery): continue
            sc = score(c)
            if sc > 0: out.append((sc, c, ('prep', p)))
        return out

    def loop_combo(s, P):
        """Deterministic loops the tag-based combos can't express. Returns (label, piece names) or None."""
        if s.no_triggers(): return None
        on = {p.name for p in P.bf if not p.neutral}
        if 'Blazing Firesinger' not in on or s.avail(P) < 3: return None
        cre_mana = bool(on & CREATURE_MANA)
        codie_ok = any(p.name == CODIE and (not p.sick or 'haste' in s.kw(p)) for p in P.creatures()) and not s.stax_on(P, 'no_creature_abilities')
        kitten = 'Displacer Kitten' in on
        codie_loop = codie_ok and ('Chakram Retriever' in on and 'Chromatic Orrery' in on
                                   or 'Jeskai Ascendancy' in on and ('Chromatic Orrery' in on or cre_mana and len(P.creatures()) >= 6))
        if not (kitten or codie_loop): return None
        engine = ['Displacer Kitten', 'Blazing Firesinger'] if kitten else \
                 [CODIE, 'Blazing Firesinger'] + [n for n in ('Chakram Retriever', 'Jeskai Ascendancy', 'Chromatic Orrery') if n in on][:2]
        pay = None
        if 'Flaming Tyrannosaurus' in on: pay = 'Flaming Tyrannosaurus'
        elif any(c.name == 'Impending Flux' for c in P.hand): pay = 'Impending Flux'
        elif codie_loop and on & {'Stensian Sanguinist', 'Emeritus of Conflict'}: pay = sorted(on & {'Stensian Sanguinist', 'Emeritus of Conflict'})[0]
        elif kitten and any(p.name == 'Stensian Sanguinist' and p.prepared for p in P.bf): pay = 'Stensian Sanguinist'
        elif on & {'Vega, the Watcher', 'Archmage Emeritus', 'Song of Creation'} and \
             any(c.name in LOOP_PAYOFFS for c in P.lib + P.hand): pay = 'draw into payoff'
        if pay is None: return None
        return ('infinite mana loop (' + ' + '.join(engine) + ') into ' + pay, [n for n in engine + [pay] if n in on])

    # ---------------------------------------------------------------- elimination
    def eliminate(s, P, cause, killer):
        if not P.alive: return
        P.alive = False; P.died = (s.round, cause, killer.label if killer else None)
        s.elim.append((P, s.round, cause, killer))
        s.log(f'{P.label} eliminated ({cause}{" by " + killer.label if killer else ""})')
        P.bf = []
        alive = [p for p in s.players if p.alive]
        if len(alive) <= 1:
            s.over = True; s.winner = alive[0] if alive else None

    def check_deaths(s, killer=None, cause='damage'):
        for P in s.players:
            if not P.alive: continue
            ls = getattr(P, 'last_src', None)
            if P.life <= 0:
                k, why = (ls if ls else (killer, cause))
                s.eliminate(P, why or cause, k)
            elif P.poison >= 10: s.eliminate(P, 'poison', killer)
            elif any(v >= 21 for v in P.cmd_dmg.values()): s.eliminate(P, 'commander damage', killer)

    def win_all(s, P, how):
        s.log(f'{P.label} wins via {how}')
        P.stats['combo_win'] += 1
        for q in P.opps():
            if any(x.name == "Teferi's Protection" for x in q.hand) and s.avail(q) + q.reserve >= 3:
                q.hand = [x for x in q.hand if x.name != "Teferi's Protection"]; continue
            q.life = 0; s.eliminate(q, how, P)
        if P.alive and len([p for p in s.players if p.alive]) > 1:
            pass

    # ---------------------------------------------------------------- casting
    def can_cast_now(s, P, c, is_cmd=False):
        if is_cmd and s.stax_on(P, 'no_cmd_cast'): return False
        if s.stax_on(P, 'one_spell') and P.spells_turn + P.stats['cre_cast_turn'] >= 1: return False
        if not c.is_creature and s.stax_on(P, 'one_noncreature') and P.noncre_turn >= 1: return False
        if s.stax_on(P, 'no_even') and c.cmc % 2 == 0 and c.cmc > 0: return False
        return True

    def try_counter(s, S, c, is_cmd=False):
        """Other players may counter spell c cast by S. Returns True if countered."""
        if s.stax_on(S, 'abolisher') is None: pass
        abol = any(p.name == 'Grand Abolisher' for p in S.bf)
        if abol: return False
        thr = s.spell_threat(S, c, is_cmd)
        for Q in S.opps():
            if any(p.name == 'Teferi, Time Raveler' for x in s.players if x is not Q and x.alive for p in x.bf): continue
            # Jin-Gitaxias: counters first artifact/instant/sorcery each turn
            if Q.has('Jin-Gitaxias, Progress Tyrant') and (c.is_artifact or c.is_instant or c.is_sorcery) and not S.stats.get('jin_' + str(s.round)):
                S.stats['jin_' + str(s.round)] = 1; s.log(f'{Q.label} Jin-Gitaxias counters {c.name}'); S.stats['countered'] += 1
                if S.is_me: S.stats['countered_by_' + Q.label] += 1
                return True
            cs = [x for x in Q.hand if x.counter and (x.counter['scope'] == 'any' or (x.counter['scope'] == 'noncreature' and not c.is_creature) or (x.counter['scope'] == 'creature' and c.is_creature))
                  and c.cmc >= x.counter.get('mvmin', 0)]
            if not cs: continue
            need = 8 if all(x.counter['cost'] == 0 for x in cs) else 6
            if s.threat_to(Q, S, c, thr) < need: continue
            cs.sort(key=lambda x: (x.counter['cost'], x.counter['soft']))
            for x in cs:
                cost = s.cost(Q, x) if x.counter['cost'] else 0
                if Q.reserve >= cost:
                    Q.reserve -= cost; Q.hand.remove(x); Q.gy.append(x)
                    if x.counter['soft'] and s.avail(S) >= x.counter['soft']:
                        s.pay(S, x.counter['soft']); continue
                    s.log(f'{Q.label} counters {S.label}\'s {c.name} with {x.name}')
                    S.stats['countered'] += 1; Q.stats['counters_used'] += 1
                    if S.is_me: S.stats['countered_by_' + Q.label] += 1; S.stats['countered_card_' + c.name] += 1
                    if Q.cmd_card.name == 'Baral, Chief of Compliance' and Q.cmd_on_bf(): Q.draw(1)
                    return True
        return False

    def spell_threat(s, S, c, is_cmd):
        t = 0
        if any(c.name in cb for cb in S.combo_names):
            cb_done = [cb for cb in S.combo_names if c.name in cb and all(S.has(n) or n == c.name for n in cb)]
            t = 11 if cb_done else 5
        if c.wipe: t = max(t, 7)
        if c.overrun or c.alt_win: t = max(t, 8)
        if c.stax: t = max(t, 6)
        if c.draw_engine >= 1: t = max(t, 5)
        if is_cmd: t = max(t, 6)
        if c.is_creature and c.cmc >= 6: t = max(t, 6)
        if c.tutor: t = max(t, 4)
        if c.name in S.pilot.get('key_cards', []):
            t = max(t, 9 if c.overrun else 7)
        if c.drain_now in ('X', 'X2', 'TORMENT', 'STORM'): t = max(t, 7)
        return t

    def threat_to(s, Q, S, c, thr):
        # wipes that hurt Q a lot, or general threats scaled by how threatening S already is
        t = thr
        if c.wipe and not c.wipe.get('asym'): t = thr if len(Q.creatures()) >= 3 else thr - 3
        if c.wipe and c.wipe.get('asym'): t = thr + 1
        if s.threat(Q, S) > 10: t += 1
        return t

    def cast(s, P, c, from_cmd=False, free=False, from_gy=False):
        cost = 0 if free else s.cost(P, c, from_cmd)
        if not free and not s.pay(P, cost): return False
        P.cur_x = 0
        if getattr(c, 'x_tokens', False):
            P.cur_x = max(0, s.avail(P) - (P.pilot.get('x_reserve', 0) if P.is_me else 0)); s.pay(P, P.cur_x)
        if from_cmd: P.cmd_zone = False
        elif from_gy: P.gy.remove(c)
        else: P.hand.remove(c)
        if c.is_creature: P.stats['cre_cast_turn'] += 1
        else: P.noncre_turn += 1
        P.cast_log.append((s.round, c.name))
        P.stats['spells'] += 1
        s.spell_triggers(P, c)
        if s.try_counter(P, c, from_cmd):
            if from_cmd: P.cmd_zone = True; P.cmd_tax += 2
            else: P.gy.append(c)
            return True
        s.resolve(P, c, from_cmd)
        if (c.is_instant or c.is_sorcery) and P.alive and not s.over:
            s.aziza_copy(P, c)
            if c.name == 'Battle Screech' and not from_gy and c in P.gy and len(s.untapped(P)) >= 3:
                s.tap_n(P, 3); s.log(f'{P.label} flashes back Battle Screech')
                s.cast(P, c, free=True, from_gy=True)
                if c in P.gy: P.gy.remove(c)
        return True

    # ---------------------------------------------------------------- spell copying (Aziza, Twinning Staff, magecraft)
    def untapped(s, P): return [p for p in P.creatures() if not p.tapped and not p.neutral]

    def tap_n(s, P, n):
        keep = set(P.pilot.get('keep_home', []))
        pool = sorted(s.untapped(P), key=lambda p: (not p.sick, p.name not in keep, not p.token, s.power(p)))
        for p in pool[:n]: p.tapped = True

    def magecraft(s, P):
        for p in P.bf:
            st = p.card.spell_trig if p.card else None
            if st and st.get('magecraft') and not p.neutral: s.apply_effect(P, st, why='spell')

    def copy_worth(s, P, c):
        if c.wipe or c.protect or c.counter or c.fog: return False
        if c.overrun:
            atk = [p for p in s.untapped(P) if s.can_attack(p) or c.overrun.get('haste')]
            return len(atk) - 3 >= 4
        if c.removal: return s.pick_removal_target(P, c, c.removal) is not None
        return bool(c.tokens_now or c.ritual or c.special or c.mob or c.treasure_now or c.draw_now or c.drain_now or c.edict)

    def aziza_copy(s, P, c):
        az = [p for p in P.bf if p.name == 'Aziza, Mage Tower Captain' and not p.neutral]
        if not az or s.no_triggers() or not s.copy_worth(P, c): return
        for _ in az:
            if len(s.untapped(P)) < 3 or not P.alive or s.over: break
            s.tap_n(P, 3)
            n = 1 + sum(1 for p in P.bf if p.card and getattr(p.card, 'special', None) == 'twinning' and not p.neutral)
            for _ in range(n):
                P.stats['copies'] += 1
                s.magecraft(P)
                s.spell_effect(P, c, copy=True)
                if s.over: return

    def resolve(s, P, c, is_cmd=False):
        g = s
        if c.is_creature or c.is_artifact or c.is_enchantment or c.is_planeswalker or c.is_land:
            if c.is_aura:
                tgt = s.aura_target(P, c)
                if tgt is None: P.gy.append(c); return
                s.attach(P, c, tgt); P.bf.append(Perm(P, c)); P.bf[-1].creature = False
                return
            p = Perm(P, c, is_cmd=is_cmd)
            if c.is_creature and s.stax_on(P, 'opp_enter_tapped'): p.tapped = True
            if 'haste' in c.kw: p.sick = False
            P.bf.append(p)
            if c.is_creature and getattr(c, 'prep_card', None) and c.prep_enter: p.prepared = True
            if c.name in ('Doran, the Siege Tower', 'Assault Formation', 'Toxrill, the Corrosive'): s.update_static()
            if c.name in ('Swiftfoot Boots', 'Lightning Greaves'):
                for q in P.bf:
                    if q.is_cmd: q.aura_kw |= {'hexproof', 'haste'}; q.sick = False
            s.log(f'{P.label} casts {c.name}')
            if c.is_creature and not s.no_triggers():
                s.etb(P, p, c)
                s.etb_triggers(P, [p])
            elif not c.is_creature:
                s.etb(P, p, c)
            if c.is_creature and P.has("Garruk's Uprising") and s.power(p) >= 4: P.draw(1)
            if c.is_creature and P.has('Beast Whisperer') or c.is_creature and P.has('Guardian Project'): P.draw(1)
            return
        # instants / sorceries
        s.spell_effect(P, c)
        if c.name not in ('Approach of the Second Sun',):
            P.gy.append(c)

    def etb(s, P, p, c):
        """ETB / static-on-entry effects of permanent p."""
        if c.overrun and c.is_creature and not c.overrun.get('static') and not c.overrun.get('activated'):
            s.apply_overrun(P, c)
        if c.tokens_now:
            n, pw, tg, kw = c.tokens_now
            nm = 'Plant' if c.name == 'Avenger of Zendikar' else 'Insect' if c.name == 'Hornet Queen' else 'Token'
            s.make_tokens(P, n, pw, tg, kw, name=nm)
        if c.draw_now: P.draw(c.draw_now)
        if c.ramp_lands: s.fetch_lands(P, c)
        if c.drain_now and isinstance(c.drain_now, int):
            for v in P.opps(): s.lose_life(v, c.drain_now, P, 'etb')
            s.gain(P, c.drain_now if c.name == 'Gray Merchant of Asphodel' else 0)
        if c.life_now: s.gain(P, c.life_now)
        if c.edict:
            for v in P.opps(): s.force_sac(v, src=P, why='edict')
            if getattr(c, 'edict_self', False): s.force_sac(P, src=None)
        if c.removal and c.is_creature:
            s.use_removal(P, c, c.removal)
        if c.wipe and c.is_creature:
            s.do_wipe(P, c, c.wipe)
        if c.tutor and c.is_creature: s.tutor(P)
        if c.name == 'Light-Paws, Emperor\'s Voice': pass

    def fetch_lands(s, P, c):
        n = c.ramp_lands
        if c.name in ('Cultivate', "Kodama's Reach"): n = 1
        for _ in range(n):
            P.lands += 1; s.landfall(P)
        if c.name in ('Cultivate', "Kodama's Reach"): P.extra_land_cards = getattr(P, 'extra_land_cards', 0) + 1

    def spell_effect(s, P, c, copy=False):
        s.log(f'{P.label} {"copies" if copy else "casts"} {c.name}')
        if c.ritual: P.pool += c.ritual + (c.cmc if c.ritual else 0) - 0
        sp = getattr(c, 'special', None); opps = P.opps()
        if sp == 'hymn': P.pool += len(P.creatures())
        if sp == 'jeska': P.pool += min(7, max([len(q.hand) for q in opps] or [0]))
        if sp == 'brass': P.treasure += P.lands
        if sp == 'charm4' and opps: s.lose_life(min(opps, key=lambda q: q.life), 4, P, 'burn')
        if getattr(c, 'mob', False) and opps: s.lose_life(min(opps, key=lambda q: q.life), len(P.creatures()), P, 'burn')
        if getattr(c, 'treasure_now', 0): P.treasure += c.treasure_now
        if sp == 'warrens': s.make_tokens(P, 2 if copy else 2 * max(1, P.spells_turn), 1, 1, set(), name='Goblin')
        if c.draw_now:
            if getattr(c, 'wheel', False):
                for q in s.players:
                    if q.alive: q.gy += q.hand; q.hand = []; q.draw(7)
            else: P.draw(c.draw_now)
        if c.ramp_lands: s.fetch_lands(P, c)
        if c.tokens_now and sp != 'warrens':
            n, pw, tg, kw = c.tokens_now
            if c.name in ('March of the Multitudes', 'Elvish Promenade', 'Elven Ambush'):
                n = max(2, len(P.creatures()))
            if getattr(c, 'x_tokens', False): n = getattr(P, 'cur_x', 0)
            if n == 'oppmax': n = max([len(q.creatures()) for q in opps] or [0])
            if n == 'own': n = len(P.creatures())
            if n: s.make_tokens(P, n, pw, tg, kw)
        if c.name in NONTOKEN_EDICT_SPELLS:
            for v in P.opps(): s.force_sac(v, nontoken=True, src=P, why='edict')
        elif c.name in FLYER_EDICT_SPELLS:
            for v in P.opps(): s.force_sac(v, flying=True, src=P, why='edict')
        elif c.removal and not c.wipe: s.use_removal(P, c, c.removal)
        if c.wipe: s.do_wipe(P, c, c.wipe)
        if c.edict and c.name not in NONTOKEN_EDICT_SPELLS:
            for v in P.opps(): s.force_sac(v, src=P, why='edict')
            if getattr(c, 'edict_self', False): s.force_sac(P)
        if c.drain_now:
            d = c.drain_now; opps = P.opps()
            if d == 'X':
                if copy: x = getattr(P, 'last_x', 0)
                else: x = max(0, s.avail(P)); s.pay(P, x); P.last_x = x
                [s.lose_life(v, x, P, 'drain') for v in opps]; s.gain(P, x * len(opps))
            elif d == 'X2': x = max(0, s.avail(P) // 2); s.pay(P, x * 2); [s.lose_life(v, x * 2, P, 'drain') for v in opps]
            elif d == 'TORMENT': s.torment(P)
            elif d == 'STORM':
                v = min(opps, key=lambda q: q.life) if opps else None
                if v: s.lose_life(v, 1 if copy else P.spells_turn, P, 'storm')
            else:
                for v in opps: s.lose_life(v, d, P, 'drain')
        if c.life_now and c.name != 'Approach of the Second Sun': s.gain(P, c.life_now)
        if c.tutor: s.tutor(P)
        if c.overrun: s.apply_overrun(P, c)
        if c.name == 'Approach of the Second Sun':
            if P.approach:
                s.win_all(P, 'Approach of the Second Sun'); return
            P.approach = 1; s.gain(P, 7); P.lib.insert(max(0, len(P.lib) - 7), c)
        if c.name == 'Living Death':
            for q in s.players:
                if not q.alive: continue
                back = [x for x in q.gy if x.is_creature]
                for p in list(q.creatures()): s.kill(p, 'sac', sac=True)
                for x in back[:8]:
                    q.gy.remove(x); np_ = Perm(q, x); q.bf.append(np_)
        if c.name in ('Underworld Breach', 'Past in Flames', "Mizzix's Mastery"):
            P.flashback = True
            if c.name == "Mizzix's Mastery" and s.avail(P) >= 3:
                for x in [x for x in P.gy if (x.is_instant or x.is_sorcery) and x.name != c.name][:10]:
                    s.spell_triggers(P, x); s.spell_effect(P, x)
        if c.name == 'Beacon of Immortality': s.gain(P, max(5, P.life))
        if sp == 'reanimate':
            if c.name == 'Bind to Life':
                milled = [P.lib.pop() for _ in range(min(7, len(P.lib)))]; P.gy += milled
                pool = [(P, x) for x in milled if x.is_creature]
            elif c.name == 'Reanimate': pool = [(q, x) for q in s.players for x in q.gy if x.is_creature]
            else: pool = [(P, x) for x in P.gy if x.is_creature or x.is_artifact]
            if pool:
                q, x = max(pool, key=lambda t: t[1].cmc); q.gy.remove(x)
                if c.name == 'Reanimate': s.lose_life(P, x.cmc)
                s.log(f'{P.label} {c.name} returns {x.name}'); s.resolve(P, x)
        if sp == 'regrowth':
            back = [x for x in P.gy if not x.is_land and x is not c]
            if back: x = max(back, key=lambda x: x.cmc); P.gy.remove(x); P.hand.append(x)

    def torment(s, P):
        x = max(0, s.avail(P)); s.pay(P, x)
        for v in P.opps():
            res = len(v.hand) + sum(1 for p in v.bf if not p.creature and p.card) // 2
            take = min(x, res + len(v.creatures()))
            lose_c = max(0, min(len(v.creatures()), (x - res)))
            for _ in range(lose_c): s.force_sac(v, src=P, why='torment')
            life = 3 * max(0, x - take)
            if life: s.lose_life(v, life, P, 'torment')
            v.hand = v.hand[:max(0, len(v.hand) - x)]

    def tutor(s, P):
        want = None
        for cb in P.combo_names:
            miss = [n for n in cb if not P.has(n) and not any(h.name == n for h in P.hand) and n != P.cmd_card.name]
            if len(miss) == 1: want = miss[0]; break
        if P.is_me:
            for n in P.pilot.get('tutor_targets', []):
                if not P.has(n) and not any(h.name == n for h in P.hand): want = n; break
        if want is None:
            pool = [c for c in P.lib if c.overrun or c.alt_win or c.wipe or c.draw_engine >= 1 or c.cmc >= 6]
            if pool: want = max(pool, key=lambda c: (c.overrun is not None) * 5 + c.draw_engine * 2 + c.cmc).name
        for c in P.lib:
            if c.name == want: P.lib.remove(c); P.hand.append(c); return

    def aura_target(s, P, c):
        cr = [p for p in P.creatures() if not p.token]
        if not cr:
            return None
        cm = [p for p in cr if p.is_cmd]
        return cm[0] if cm else max(cr, key=lambda p: s.power(p))

    def attach(s, P, c, tgt):
        b = c.aura_bonus or dict(p=1, t=1, kw=set())
        tgt.auras += 1; tgt.aura_p += b['p']; tgt.aura_t += b['t']; tgt.aura_kw |= b['kw']
        if c.removal and c.removal.get('how') == 'neutralize': pass
        if tgt.is_cmd and P.cmd_card.name == 'Light-Paws, Emperor\'s Voice' and not getattr(s, '_lp', False):
            pool = [x for x in P.lib if x.is_aura and x.cmc <= tgt.auras and x.name != c.name]
            if pool:
                x = max(pool, key=lambda a: (a.aura_bonus or {'p': 0})['p'] + len((a.aura_bonus or {'kw': set()})['kw']) * 2)
                P.lib.remove(x); s._lp = True; s.attach(P, x, tgt); P.bf.append(Perm(P, x)); P.bf[-1].creature = False; s._lp = False
        if P.has('Sram, Senior Edificer') or P.has('Mesa Enchantress') or P.has('Kor Spiritdancer'): P.draw(1)

    # ---------------------------------------------------------------- removal & wipes
    def use_removal(s, P, c, rem, target=None):
        if c.name in BITE and not P.creatures(): return False
        t = target or s.pick_removal_target(P, c, rem)
        if t is None: return False
        P.stats['removal_used'] += 1
        if t.owner.is_me: t.owner.stats['removed_' + t.name] += 1; t.owner.stats['removal_taken'] += 1
        if P.is_me: P.stats['my_removal_on_' + t.name] += 1
        how = rem.get('how')
        s.log(f'{P.label} {c.name} -> {t.owner.label}\'s {t.name}')
        if t.owner.is_me and s.protect_response(t.owner, single=True): return True
        if how == 'bounce':
            o = t.owner; o.bf.remove(t)
            if t.is_cmd: o.cmd_zone = True
            elif t.card: o.hand.append(t.card)
        elif how == 'neutralize':
            t.neutral = True
        elif how == 'exile':
            o = t.owner; o.bf.remove(t)
            if t.is_cmd: o.cmd_zone = True; o.cmd_tax += 2
        else:
            s.kill(t, 'destroy')
        if c.name in ('Pongify', 'Rapid Hybridization'): s.make_tokens(t.owner, 1, 3, 3, set())
        if c.name == 'Feed the Swarm' and t.card: s.lose_life(P, t.card.cmc)
        return True

    def pick_removal_target(s, P, c, rem, only_from=None):
        best = None; bv = 2.0
        for V in (only_from or P.opps()):
            for p in V.bf:
                if p.card is None and not p.creature: continue
                if p.neutral: continue
                k = rem['kind']
                if k == 'creature' and not p.creature: continue
                if k == 'noncreature' and p.creature: continue
                if k == 'enchantment' and not p.is_ench(): continue
                if k == 'creature_ench' and not (p.creature or p.is_ench()): continue
                if p.card and p.card.is_land: continue
                if not s.targetable(p, P, c): continue
                if rem.get('how') in ('damage', 'minus') and s.tough(p) > rem.get('amt', 99) and not (c.name in BITE): continue
                if c.name in BITE and not any(s.has_dt(x) or s.power(x) >= s.tough(p) for x in P.creatures()): continue
                mv = rem.get('mv')
                if mv and p.card:
                    if mv[1] == 'greater' and p.card.cmc < mv[0]: continue
                    if mv[1] == 'less' and p.card.cmc > mv[0]: continue
                v = s.value(P, p) + 0.2 * s.threat(P, V)
                if v > bv: best, bv = p, v
        return best

    def wipe_hits(s, P, w, p):
        if not p.card and not p.creature: return False
        if p.card and p.card.is_land: return False
        if w.get('asym') and p.owner is P: return False
        scope = w['scope']
        hit = (p.creature and 'creature' in scope) or (p.is_art() and 'artifact' in scope) or (p.is_ench() and 'enchantment' in scope)
        if not hit: return False
        if w.get('mvmax') is not None and p.card and p.card.cmc > w['mvmax']: return False
        if w.get('mvmax') is not None and p.token and p.owner is P: pass
        if w.get('spare_enchanted') and p.auras: return False
        if w.get('spare_type') and p.owner is P: return False
        if w.get('minus') is not None and p.creature and s.tough(p) > w['minus']: return False
        return True

    def do_wipe(s, P, c, w):
        s.log(f'{P.label} WIPE {c.name}')
        P.stats['wipes_cast'] += 1
        protected = set()
        for q in s.players:
            if q.alive and q is not P:
                hits = [p for p in q.bf if s.wipe_hits(P, w, p)]
                if len(hits) >= 3 and s.protect_response(q, single=False, exile=w.get('bounce') or 'exile' in c.oracle):
                    protected.add(q)
                if q.is_me and hits: q.stats['wiped_by_' + c.name] += 1; q.stats['wipes_suffered'] += 1
        victims = [p for q in s.players if q.alive and q not in protected for p in list(q.bf) if s.wipe_hits(P, w, p)]
        victims.sort(key=lambda p: p.is_cmd)
        for p in victims:
            if w.get('bounce'):
                o = p.owner
                if p in o.bf:
                    o.bf.remove(p)
                    if p.is_cmd: o.cmd_zone = True
                    elif p.card: o.hand.append(p.card)
            elif 'exile all' in c.oracle:
                o = p.owner
                if p in o.bf:
                    o.bf.remove(p)
                    if p.is_cmd: o.cmd_zone = True; o.cmd_tax += 2
            else:
                s.kill(p, 'destroy' if not w.get('minus') else 'sac', sac=bool(w.get('minus')))
        if c.name == 'Martial Coup': s.make_tokens(P, 5, 1, 1, set())

    def protect_response(s, Q, single=False, exile=False):
        for name, cost in (('Heroic Intervention', 2), ("Teferi's Protection", 3)):
            if exile and name == 'Heroic Intervention': continue
            for x in Q.hand:
                if x.name == name and Q.reserve >= cost and (not single or s.rng.random() < .3):
                    Q.reserve -= cost; Q.hand.remove(x); Q.gy.append(x)
                    s.log(f'{Q.label} protects with {name}'); Q.stats['protected'] += 1
                    return True
        return False

    # ---------------------------------------------------------------- overrun & landfall
    def apply_overrun(s, P, c):
        o = c.overrun
        if o.get('min_mana') and s.avail(P) < 0: return
        cr = P.creatures()
        pump = o['pump']
        if pump == 'count': pump = len(cr)
        if pump == 'maxpow': pump = max([s.power(p) for p in cr] or [0])
        for p in cr:
            p.pump += pump; p.pumpt += pump
            if o.get('trample'): p.tmpkw.add('trample')
            if o.get('infect'): p.infect_turn = True
            if c.name == 'Craterhoof Behemoth' or o.get('haste'): p.tmpkw.add('haste'); p.sick = False
            p.tmpkw |= set(o.get('kw', ()))
        P.stats['overrun'] += 1
        s.log(f'{P.label} OVERRUN {c.name} (+{pump})')

    def landfall(s, P):
        for p in list(P.bf):
            if p.neutral: continue
            c = p.card
            if c is None: continue
            if c.landfall:
                e = c.landfall
                if 'token' in e:
                    n, pw, tg, kw = e['token']
                    if c.name == 'Scute Swarm':
                        n = 1 + (P.count('Scute Swarm') if P.lands >= 6 else 0)
                    s.make_tokens(P, n if n != 'each' else 1, pw, tg, kw)
                s.apply_effect(P, {k: v for k, v in e.items() if k != 'token'}, why='landfall')
            if c.name == 'Avenger of Zendikar':
                for q in P.creatures():
                    if q.name == 'Plant': q.counters += 1
            if c.name == 'Field of the Dead' and P.lands >= 7: s.make_tokens(P, 1, 2, 2, set())
            if c.name == 'Lotus Cobra': P.pool += 1
        if P.cmd_card.name == 'Tatyova, Benthic Druid' and P.cmd_on_bf():
            s.gain(P, 1); P.draw(1)

    # ---------------------------------------------------------------- combos & alt wins
    def check_combo(s, P):
        lp = s.loop_combo(P)
        cands = list(P.combo_names) + ([tuple(lp[1])] if lp else [])
        for cb in cands:
            if all(P.has(n) for n in cb):
                # opponents may respond with instant removal on a piece
                pieces = [p for p in P.bf if p.name in cb and not p.neutral]
                if len(pieces) < len(cb): continue
                broken = False
                for Q in P.opps():
                    if any(p.name == 'Grand Abolisher' for p in P.bf): break
                    for x in list(Q.hand):
                        if x.removal and x.removal.get('instant') and not (x.name in BITE and not Q.creatures()):
                            cost = s.cost(Q, x)
                            if Q.reserve < cost: continue
                            kd = x.removal['kind']
                            tg = [p for p in pieces if s.targetable(p, Q, x) and (kd == 'any' or (kd == 'creature' and p.creature) or (kd == 'noncreature' and not p.creature)
                                  or (kd == 'enchantment' and p.is_ench()) or (kd == 'creature_ench' and (p.creature or p.is_ench())))]
                            if tg:
                                Q.reserve -= cost; Q.hand.remove(x); Q.gy.append(x)
                                s.log(f'{Q.label} breaks {P.label} combo: {x.name} on {tg[0].name}')
                                Q.stats['combo_stops'] += 1
                                if tg[0].name in [p.name for p in P.bf]:
                                    if x.removal.get('how') == 'bounce':
                                        P.bf.remove(tg[0]); (P.hand.append(tg[0].card) if tg[0].card and not tg[0].is_cmd else None)
                                        if tg[0].is_cmd: P.cmd_zone = True
                                    else: s.kill(tg[0], 'destroy')
                                broken = True; break
                    if broken: break
                if not broken:
                    s.win_all(P, 'combo: ' + (lp[0] if lp and tuple(lp[1]) == cb else ' + '.join(cb))); return True
        return False

    def upkeep_altwins(s, P):
        for p in P.bf:
            if p.neutral or not p.card: continue
            a = p.card.alt_win
            if a == 'felidar' and P.life >= 40 and getattr(p, 'seen', False): s.win_all(P, 'Felidar Sovereign'); return
            if a == 'test' and P.life >= 50 and getattr(p, 'seen', False): s.win_all(P, 'Test of Endurance'); return
            p.seen = True

    # ---------------------------------------------------------------- combat
    def blockers_for(s, D, att, used):
        k = s.kw(att)
        out = []
        for b in D.creatures():
            if b in used or b.tapped or b.neutral: continue
            if 'flying' in k and not ({'flying', 'reach'} & s.kw(b)): continue
            if 'pro_bg' in k and b.card is not None and (b.card.colors & {'B', 'G'}) or ('pro_bg' in k and b.token and (D.cmd_card.colors & {'B', 'G'})): continue
            if "can't be blocked" in (att.card.oracle if att.card else '') or 'unblockable' in k: continue
            out.append(b)
        return out

    def assign_blocks(s, D, attackers, A, simulate=False):
        incoming = sum(s.power(a) * (2 if 'double strike' in s.kw(a) else 1) for a in attackers)
        infect = sum(s.power(a) for a in attackers if a.infect_turn)
        must_chump = incoming >= D.life * 0.7 or D.poison + infect >= 10
        used = set(); blocks = {}
        for a in sorted(attackers, key=lambda a: -s.power(a)):
            cands = s.blockers_for(D, a, used)
            if not cands: continue
            ap, at = s.power(a), s.tough(a); adt = s.has_dt(a)
            best = None; bscore = -9
            for b in cands:
                bp, bt = s.power(b), s.tough(b); bdt = s.has_dt(b)
                kills = (bdt and bp >= 1) or bp >= at
                dies = (adt and ap >= 1) or ap >= bt
                if 'indestructible' in s.kw(b): dies = False
                if 'indestructible' in s.kw(a): kills = False
                sc = 0
                if kills and not dies: sc = 6
                elif kills and dies: sc = 3 + s.value(D, a) - s.value(D, b) + (2 if b.token else 0) + (3 if D.cmd_card.name == ME and bdt and D.cmd_on_bf() else 0)
                elif not kills and not dies: sc = 1 if ap >= 3 else -1
                else: sc = (5 if must_chump else -5) - s.value(D, b) * 0.3 + (1 if b.token else 0)
                if D.is_me and b.name in s.eng(D) and not b.token and not must_chump and not b.is_cmd: sc -= 3
                if b.name == 'Hornet Nest': sc = 8
                if b.is_cmd and dies: sc -= 6
                if sc > bscore: best, bscore = b, sc
            if best is not None and bscore > 0:
                blocks[a] = best; used.add(best)
        return blocks

    def evaluate_attack(s, A, D, attackers):
        blocks = s.assign_blocks(D, attackers, A, simulate=True)
        dmg = 0; losses = 0; kills = 0; poison = 0
        for a in attackers:
            ap = s.power(a) * (2 if 'double strike' in s.kw(a) else 1)
            if a in blocks:
                b = blocks[a]; bp = s.power(b); bdt = s.has_dt(b)
                if (bdt and bp >= 1) or bp >= s.tough(a): losses += s.value(A, a)
                if s.has_dt(a) or ap >= s.tough(b): kills += s.value(A, b)
                if 'trample' in s.kw(a): dmg += max(0, ap - (1 if s.has_dt(a) else s.tough(b)))
            else:
                if a.infect_turn: poison += ap
                else: dmg += ap
        return dmg, poison, losses, kills, blocks

    def attack_tax(s, A, D):
        t = 0
        for p in D.bf:
            if p.card and p.card.stax.get('attack_tax') and not p.neutral: t += p.card.stax['attack_tax']
        return t

    def can_attack(s, p):
        if p.tapped or p.neutral or s.power(p) <= 0: return False
        if p.sick and 'haste' not in s.kw(p): return False
        if 'defender' in p.kw: return False
        return True

    def plan_attack(s, A):
        cand = [p for p in A.creatures() if s.can_attack(p)]
        if not cand: return None, []
        if not A.is_me:
            cand = [p for p in cand if not (p.card and p.card.rock and s.power(p) <= 1)]
        else:
            keep = set(A.pilot.get('keep_home', [])) | ({A.cmd_card.name} if A.pilot.get('keep_commander_home', True) else set())
            lethal_mode = any(p.infect_turn for p in cand)
            if not lethal_mode: cand = [p for p in cand if p.name not in keep]
        best = None
        for D in A.opps():
            atk = list(cand)
            tax = s.attack_tax(A, D)
            if tax:
                n = int(s.avail(A) // tax) if tax else len(atk)
                atk = sorted(atk, key=lambda p: -s.power(p))[:n]
            if not atk: continue
            for _ in range(2):
                dmg, poison, losses, kills, blocks = s.evaluate_attack(A, D, atk)
                # drop attackers that die for nothing (unless deathtouch: trading is the point for me)
                bad = [a for a, b in blocks.items() if not (s.has_dt(a) or s.power(a) >= s.tough(b)) and ((s.has_dt(b) and s.power(b) >= 1) or s.power(b) >= s.tough(a))]
                if not bad: break
                atk = [a for a in atk if a not in bad]
            if not atk: continue
            dmg, poison, losses, kills, blocks = s.evaluate_attack(A, D, atk)
            lethal = dmg >= D.life or D.poison + poison >= 10
            score = (dmg / max(5, D.life)) * 10 + poison * 1.2 + kills * 0.5 - losses * 0.6 + (50 if lethal else 0)
            if A.cmd_card.name == ME and A.cmd_on_bf():
                dt_deaths = sum(1 for a, b in blocks.items() if s.has_dt(a) and ((s.has_dt(b) and s.power(b) >= 1) or s.power(b) >= s.tough(a)))
                score += dt_deaths * 1.5 * len(A.opps()) + losses * 0.5
            score += 0.15 * s.threat(A, D)
            if A.is_me and D.cmd_on_bf() and False: pass
            if score > 1.0 and (best is None or score > best[0]): best = (score, D, atk, tax)
        if best is None: return None, []
        _, D, atk, tax = best
        # keep a couple of blockers home if under pressure
        if not A.is_me:
            pressure = max([sum(s.power(p) for p in q.creatures()) for q in A.opps()] or [0])
            if pressure >= A.life * 0.5 and len(atk) >= 3:
                atk = sorted(atk, key=lambda p: -s.power(p))[:max(1, len(atk) - 2)]
        if tax: s.pay(A, tax * len(atk))
        return D, atk

    def combat(s, A):
        D, atk = s.plan_attack(A)
        if not D or not atk: return
        # attack triggers
        for p in atk:
            if 'vigilance' not in s.kw(p): p.tapped = True
        extra = []
        for p in list(A.bf):
            if p.neutral or not p.card: continue
            n = ATTACK_TOKENS.get(p.name)
            if n is not None:
                n = len(A.opps()) if n == 'opps' else (len(atk) if n == 'attackers' else n)
                extra += s.make_tokens(A, n, 1, 1, set(), tapped=True)
            elif p.card.attack_trig and p.name != 'Hooded Blightfang':
                e = p.card.attack_trig
                if 'token' in e:
                    n, pw, tg, kw = e['token']; extra += s.make_tokens(A, n if n != 'each' else 1, pw, tg, kw, tapped=True)
                s.apply_effect(A, {k: v for k, v in e.items() if k != 'token'}, why='attack')
            if p.name == 'Hooded Blightfang':
                for a in atk:
                    if s.has_dt(a) or A.has('Ohran Frostfang'):
                        for v in A.opps(): s.lose_life(v, 1, A, 'blightfang')
                        s.gain(A, 1)
        if A.has('Ohran Frostfang'):
            for a in atk: a.tmpkw.add('deathtouch')
        for a in atk:
            if a.name == 'Arabella, Abandoned Doll':
                x = sum(1 for p in A.creatures() if s.power(p) <= 2)
                for v in A.opps(): s.lose_life(v, x, A, 'arabella')
                s.gain(A, x)
        if A.has('Beastmaster Ascension'):
            A.quest += len(atk)
            if A.quest >= 7:
                for a in atk: a.pump += 5; a.pumpt += 5
        atk = atk + [e for e in extra if e.creature]
        A.stats['attacks'] += 1
        s.log(f'{A.label} attacks {D.label} with {len(atk)} ({sum(s.power(a) for a in atk)} power)')
        if D.is_me: D.stats['attacked'] += 1
        # fog
        inc = sum(s.power(a) for a in atk)
        for x in list(D.hand):
            if x.fog and D.reserve >= s.cost(D, x) and inc >= D.life * 0.3:
                D.reserve -= s.cost(D, x); D.hand.remove(x); D.gy.append(x)
                s.log(f'{D.label} {x.name} vs {A.label}')
                for a in atk:
                    if a in A.bf:
                        A.bf.remove(a)
                        if a.is_cmd: A.cmd_zone = True
                        elif a.card: A.hand.append(a.card)
                return
        blocks = s.assign_blocks(D, atk, A)
        dead = []
        for a in atk:
            if a not in A.bf: continue
            ap = s.power(a); ds = 'double strike' in s.kw(a)
            if a in blocks:
                b = blocks[a]
                bp = s.power(b); adt = s.has_dt(a); bdt = s.has_dt(b)
                b_dies = (adt and ap >= 1) or ap >= s.tough(b)
                a_dies = (bdt and bp >= 1) or bp >= s.tough(a)
                if ds and b_dies: a_dies = False
                if b.name == 'Hornet Nest': s.make_tokens(D, ap, 1, 1, {'flying', 'deathtouch'}, name='Insect')
                if 'trample' in s.kw(a):
                    over = ap * (2 if ds else 1) - (1 if adt else s.tough(b))
                    if over > 0: s.combat_hit(A, D, a, over)
                if b_dies: dead.append((b, 'deathtouch' if adt else 'damage'))
                if a_dies: dead.append((a, 'deathtouch' if bdt else 'damage'))
                if 'lifelink' in s.kw(a): s.gain(A, ap)
                if 'lifelink' in s.kw(b): s.gain(D, bp)
            else:
                s.combat_hit(A, D, a, ap * (2 if ds else 1))
        for p, why in dead:
            if p in p.owner.bf:
                if p.owner.is_me and p.owner is D: D.stats['my_blockers_died'] += 1
                s.kill(p, why)
                if p.owner is not A: A.stats['combat_kills'] += 1
                else: D.stats['combat_kills'] += 1
        s.check_deaths(A, 'combat')

    def combat_hit(s, A, D, a, n):
        if n <= 0 or not D.alive: return
        if a.infect_turn:
            D.poison += n; A.stats['poison_dealt'] += n
        else:
            s.lose_life(D, n, A, 'combat')
            if a.is_cmd: D.cmd_dmg[A.label] += n
            if 'lifelink' in s.kw(a): s.gain(A, n)
        if a.name == 'Rankle, Master of Pranks' and not a.rankled:
            a.rankled = True; s.rankle(A, a)
        if A.has('Fynn, the Fangbearer') and s.has_dt(a):
            D.poison += 2; A.stats['poison_dealt'] += 2
        if A.cmd_card.name == 'Lathril, Blade of the Elves' and a.is_cmd: s.make_tokens(A, n, 1, 1, set())
        if any(A.has(x) for x in COMBAT_DRAW_ALL): A.draw(1)
        if a.name in ('Ragavan, Nimble Pilferer', 'Professional Face-Breaker'): A.treasure += 1

    # ---------------------------------------------------------------- turn
    def take_turn(s, P):
        s.active = P
        s.update_static()
        for p in P.bf: p.rankled = False
        P.spells_turn = 0; P.noncre_turn = 0; P.stats['cre_cast_turn'] = 0; P.flashback = False
        P.nonhand_turn = 0; P.codie_acts = 0; P.asc_mana = 0
        P.reserve = 0
        for p in P.bf:
            if s.stax_on(P, 'winter_orb') and p.card and p.card.is_land: continue
            p.tapped = False; p.sick = False
        # upkeep (own)
        s.upkeep_altwins(P)
        if s.over or not P.alive: return
        for p in list(P.bf):
            c = p.card
            if c is None or p.neutral: continue
            if c.tokens_rec and c.tokens_rec[0] == 'upkeep' and 'each upkeep' not in c.oracle:
                _, n, pw, tg, kw = c.tokens_rec
                s.make_tokens(P, n if n != 'each' else max(1, len(P.creatures()) // 3), pw, tg, kw)
            if c.upkeep:
                if c.upkeep.get('lose'): s.lose_life(P, c.upkeep['lose'])
                s.apply_effect(P, {k: v for k, v in c.upkeep.items() if k not in ('lose', 'token')}, why='upkeep')
        if P.cmd_card.name == 'Oloro, Ageless Ascetic': s.gain(P, 2)
        s.prep_upkeep(P)
        s.each_upkeep(P)
        s.check_deaths(None, 'life')
        if s.over or not P.alive: return
        # draw
        P.draw(1)
        eng = sum(p.card.draw_engine for p in P.bf if p.card and not p.neutral)
        if P.cmd_card.name in ('Birgi, God of Storytelling',) and P.cmd_on_bf(): eng += 1
        lim = s.stax_on(P, 'draw_limit')
        if lim: eng = min(eng, 0)
        P.draw(int(eng) + (1 if s.rng.random() < eng - int(eng) else 0))
        if not P.alive: return
        P.pool = s.mana_avail(P)
        # land drops
        drops = 1 + sum(p.card.extra_lands for p in P.bf if p.card and not p.neutral)
        for _ in range(drops):
            l = next((c for c in P.hand if c.is_land), None)
            if l is None and getattr(P, 'extra_land_cards', 0) > 0:
                P.extra_land_cards -= 1; P.lands += 1; P.pool += 1; s.landfall(P); continue
            if l is None: break
            P.hand.remove(l); P.lands += 1; P.pool += l.mana_land
            if l.name in ('Phyrexian Tower',): P.bf.append(Perm(P, l))
            if l.name == 'Bojuka Bog' and P.opps():
                v = max(P.opps(), key=lambda q: sum(1 for x in q.gy if x.is_creature)); P.pool -= 1
                if v.gy: s.log(f'{P.label} Bojuka Bog exiles {v.label} graveyard ({len(v.gy)})'); v.gy = []
            if l.name in ("Gaea's Cradle", 'Field of the Dead', 'Rest in Peace'): P.bf.append(Perm(P, l))
            s.landfall(P)
        if P.is_me: s.my_main(P)
        else: s.ai_main(P)
        if s.over or not P.alive: return
        if s.check_combo(P): return
        s.combat(P)
        if s.over or not P.alive: return
        if P.is_me: s.my_main(P, post=True)
        else: s.ai_main(P, post=True)
        if s.check_combo(P): return
        s.end_step(P)
        P.reserve = s.avail(P)  # untapped mana stays available for instants on others' turns
        for q in s.players:
            for p in q.bf: p.pump = 0; p.pumpt = 0; p.tmpkw = set(); p.infect_turn = False
        s.check_deaths(None, 'life')

    def each_upkeep(s, P):
        """'At the beginning of each upkeep' triggers for all players (incl. my Ophiomancer + instant sac)."""
        for q in s.players:
            if not q.alive: continue
            for p in list(q.bf):
                c = p.card
                if c is None or p.neutral or not c.tokens_rec: continue
                if 'each upkeep' in c.oracle:
                    if c.name == 'Ophiomancer' and any(x.name == 'Snake' for x in q.bf): continue
                    _, n, pw, tg, kw = c.tokens_rec
                    s.make_tokens(q, n if n != 'each' else 1, pw, tg, kw, name='Snake' if c.name == 'Ophiomancer' else 'Token')
            if q.is_me and q is not P: s.my_instant_sac(q)

    def end_step(s, P):
        s.update_static(); s.toxrill_end_step()
        if any(q is P for q in s.tox_owners) and not s.stax_on(P, 'no_creature_abilities'):
            slugs = [p for p in P.creatures() if p.name == 'Slug']
            while len(slugs) > 1 and s.avail(P) >= 2:
                s.pay(P, 2); s.kill(slugs.pop(), 'sac', sac=True); P.draw(1)
        if P.cmd_card.name == 'Meren of Clan Nel Toth' and P.cmd_on_bf():
            cr = [c for c in P.gy if c.is_creature]
            if cr:
                c = max(cr, key=lambda x: x.cmc if x.cmc <= P.exp else -1)
                P.gy.remove(c)
                if c.cmc <= P.exp: s.resolve(P, c)
                else: P.hand.append(c)
        if P.cmd_card.name == 'Lathril, Blade of the Elves' and P.cmd_on_bf():
            un = [p for p in P.creatures() if not p.tapped and not p.is_cmd]
            if len(un) >= 10:
                for p in un[:10]: p.tapped = True
                for v in P.opps(): s.lose_life(v, 10, P, 'lathril')
                s.gain(P, 10); s.log(f'{P.label} Lathril drains 10')
        # aristocrats: sacrifice tokens to payoffs (non-me players with a free outlet)
        if not P.is_me: s.ai_sac(P)
        if any(p.name == 'Song of Creation' and not p.neutral for p in P.bf): P.gy += P.hand; P.hand = []
        while len(P.hand) > 8: P.gy.append(P.hand.pop(0))

    def ai_sac(s, P):
        outlets = [p for p in P.bf if p.card and p.card.free_outlet and not p.neutral]
        if not outlets: return
        pay = sum(1 for q in P.bf if q.card and q.card.death_trig and q.card.death_trig.get('scope') in ('own', 'any'))
        if not pay: return
        for t in [p for p in P.creatures() if p.token][:6]:
            s.kill(t, 'sac', sac=True)
        s.check_deaths(P, 'drain')

    # ---------------------------------------------------------------- generic AI main phase
    def ai_main(s, P, post=False):
        turn = s.round
        reserve = 0
        if any(x.counter for x in P.hand):
            reserve = min((s.cost(P, x) if x.counter['cost'] else 0) for x in P.hand if x.counter)
        if any(x.removal and x.removal.get('instant') for x in P.hand) and any(p.combo_names for p in P.opps()):
            reserve = max(reserve, 2)
        for _ in range(12):
            if s.over or not P.alive: return
            opts = []
            if P.cmd_zone and s.can_cast_now(P, P.cmd_card, True):
                opts.append((95 if not post else 80, P.cmd_card, True))
            for c in P.hand:
                if c.is_land or c.counter or c.fog or c.protect: continue
                if not s.can_cast_now(P, c): continue
                sc = s.ai_score(P, c, turn, post)
                if sc > 0: opts.append((sc, c, False))
            if P.flashback:
                for c in P.gy:
                    if (c.is_instant or c.is_sorcery) and (c.ritual or c.draw_now or c.drain_now) and not c.counter:
                        opts.append((60, c, 'gy'))
            if P.cmd_card.name == CODIE: s.codie_activate(P)
            s.prep_tap2(P)
            opts += s.prep_options(P, lambda c: s.ai_score(P, c, turn, post))
            opts.sort(key=lambda x: -x[0])
            done = False
            for sc, c, src in opts:
                cost = s.cost(P, c, src is True) + (3 if src == 'gy' and P.has('Underworld Breach') else 0)
                budget = s.avail(P) - (reserve if sc < 100 and not c.ritual else 0)
                if cost <= budget:
                    if isinstance(src, tuple): s.cast_prep(P, src[1])
                    else: s.cast(P, c, from_cmd=(src is True), from_gy=(src == 'gy'))
                    done = True
                    if s.check_combo(P): return
                    break
            if not done: break
        # use leftover mana on activated token makers / Kinnan
        if post and P.cmd_card.name == 'Kinnan, Bonder Prodigy' and P.cmd_on_bf() and s.avail(P) >= 7:
            top = P.lib[-5:]; cr = [c for c in top if c.is_creature]
            if cr:
                c = max(cr, key=lambda x: x.cmc); s.pay(P, 7); P.lib.remove(c); s.resolve(P, c)
        if post:
            for p in list(P.bf):
                if p.card and p.card.tokens_rec and p.card.tokens_rec[0] == 'activated' and s.avail(P) >= 3 and not s.stax_on(P, 'no_creature_abilities'):
                    _, n, pw, tg, kw = p.card.tokens_rec
                    if p.name == 'Krenko, Mob Boss': n = max(1, len(P.creatures()))
                    s.pay(P, 2); s.make_tokens(P, n if n != 'each' else 1, pw, tg, kw)
            # Ezuri overrun
            if P.has('Ezuri, Renegade Leader') and s.avail(P) >= 5:
                pass

    def ai_score(s, P, c, turn, post):
        opps = P.opps()
        if c.overrun:
            # only if it makes an attack lethal (precombat)
            if post: return 0
            cr = [p for p in P.creatures() if s.can_attack(p) or (c.name == 'Craterhoof Behemoth')]
            if len(cr) < 3: return 0
            pump = c.overrun['pump']
            pump = len(P.creatures()) + 1 if pump == 'count' else (max([s.power(p) for p in cr] or [0]) if pump == 'maxpow' else pump)
            total = sum(s.power(p) + pump for p in cr) * (2 if 'double strike' in c.overrun.get('kw', ()) else 1)
            if any(total * 0.6 >= v.life for v in opps): return 150
            return 0 if not c.is_creature else 30
        if c.wipe:
            w = c.wipe
            if s.avail(P) < w.get('cost', c.cmc): return 0
            mine = sum(s.value(P, p) for p in P.bf if s.wipe_hits(P, w, p))
            theirs = sum(s.value(P, p) for q in opps for p in q.bf if s.wipe_hits(P, w, p))
            n_their = sum(1 for q in opps for p in q.creatures() if s.wipe_hits(P, w, p))
            if theirs - 1.5 * mine >= 16 and n_their >= 5: return 120
            if any(sum(s.power(p) for p in q.creatures()) >= P.life for q in opps) and theirs > mine: return 115
            return 0
        if any(c.name in cb for cb in P.combo_names):
            done = [cb for cb in P.combo_names if c.name in cb and all(P.has(n) or n == c.name for n in cb)]
            return 200 if done else 78
        if c.alt_win: return 85
        if c.drain_now in ('X', 'X2'):
            x = s.avail(P) - c.cmc
            return 140 if any(v.life <= x * (2 if c.drain_now == 'X2' else 1) for v in opps) or x >= 10 else 0
        if c.drain_now == 'STORM': return 140 if P.spells_turn >= 8 or any(v.life <= P.spells_turn + 1 for v in opps) else 0
        if c.ritual:
            follow = sum(1 for x in P.hand if (x.is_instant or x.is_sorcery) and x is not c) + len(s.prep_perms(P, True))
            return 70 if follow >= 2 or s.avail(P) + c.ritual >= 6 else 0
        if c.rock or c.ramp_lands or c.extra_lands: return 92 if turn <= 5 else 45
        if c.stax: return 88
        if c.draw_engine: return 86
        if c.token_double: return 74
        if c.tokens_rec or (c.tokens_now and not c.is_instant): return 72
        if c.anthem: return 70 if len(P.creatures()) >= 3 else 40
        if c.is_aura:
            if not P.creatures(): return 0
            return 82 if c.aura_bonus else 30
        if c.removal:
            if c.removal.get('instant') and not post and not c.is_creature: return 0
            t = s.pick_removal_target(P, c, c.removal)
            if t is None: return 0 if not c.is_creature else 50
            return 60 + s.value(P, t) * 2
        if c.edict:
            return 60 if any(q.creatures() for q in opps) else 0
        if c.tutor: return 64
        if c.drain_now and isinstance(c.drain_now, int): return 62
        if c.draw_now: return 55
        if c.is_creature: return 50 + s.power_of_card(c) * 2
        if c.is_artifact or c.is_enchantment or c.is_planeswalker: return 40 + c.cmc
        if c.name in ('Underworld Breach', 'Past in Flames', "Mizzix's Mastery"):
            return 100 if s.avail(P) >= 5 and len([x for x in P.gy if x.is_instant or x.is_sorcery]) >= 4 else 0
        return 20

    def power_of_card(s, c): return c.power

    # ---------------------------------------------------------------- pilot AI
    # The deck under test is driven by its pilot file (pilots/<deck>.yaml): engine pieces, cards to keep home,
    # fodder rules, tutor targets and cast priorities. Card-level knowledge stays in this engine.
    COSTED_OUTLETS = {'Evolutionary Leap', 'Phyrexian Tower', 'Cauldron of Essence'}
    OUTLET_MANA = {"Ashnod's Altar": 2, 'Phyrexian Altar': 1}

    def eng(s, P): return set(P.pilot.get('engine', [])) | {P.cmd_card.name}

    def my_free_outlet(s, P):
        totem = s.stax_on(P, 'no_creature_abilities'); ouphe = s.stax_on(P, 'no_artifact_abilities')
        for p in P.bf:
            if p.neutral or not p.card or not p.card.free_outlet or p.name in s.COSTED_OUTLETS: continue
            if p.creature and totem: continue
            if p.card.is_artifact and ouphe: continue
            return True
        return False

    def my_worthwhile(s, P):
        if s.no_dies() or s.no_triggers(): return False
        opps = P.opps()
        if P.cmd_card.name == ME and P.cmd_on_bf() and any(any(not x.token for x in q.creatures()) for q in opps): return True
        for p in P.bf:
            dt = p.card.death_trig if p.card else None
            if not dt or p.neutral or dt.get('scope') not in ('own', 'any') or p.name == ME: continue
            if dt.get('edict') and not any(q.creatures() for q in opps): continue
            return True
        return False

    def fodder_ok(s, P, p):
        if p.token: return True
        if not p.card or p.name in s.eng(P) or p.is_cmd: return False
        if p.card.cmc > P.pilot.get('fodder_max_cmc', 3): return False
        rule = P.pilot.get('fodder', 'any')
        if rule == 'deathtouch': return s.has_dt(p)
        if rule == 'tokens': return False
        return True

    def my_fodder(s, P, nontoken_ok=True):
        toks = [p for p in P.creatures() if p.token]
        if toks: return min(toks, key=lambda p: (0 if s.has_dt(p) else 1, s.power(p)))
        if not nontoken_ok: return None
        exp = [p for p in P.creatures() if not p.token and s.fodder_ok(P, p)]
        return min(exp, key=lambda p: p.card.cmc) if exp else None

    def nontoken_sac_ok(s, P):
        if P.cmd_card.name == ME: return sum(1 for q in P.opps() if any(not x.token for x in q.creatures())) >= 2
        return P.pilot.get('sac_nontoken', False)

    def my_instant_sac(s, P):
        names = set(P.pilot.get('instant_sac_tokens', []))
        if not names or not s.my_free_outlet(P) or not s.my_worthwhile(P): return
        for p in [p for p in P.creatures() if p.token and p.name in names]:
            s.kill(p, 'sac', sac=True)
            for n, m in s.OUTLET_MANA.items():
                if P.has(n): P.reserve += m; break
        s.check_deaths(P, 'drain')

    def bombard_lethal(s, P):
        if not any(p.name == 'Goblin Bombardment' and not p.neutral for p in P.bf): return
        for v in sorted(P.opps(), key=lambda q: q.life):
            fod = [p for p in P.creatures() if p.token or (p.card and p.name not in s.eng(P) and not p.is_cmd)]
            if v.alive and v.life <= len(fod):
                for p in fod[:v.life]: s.kill(p, 'sac', sac=True); s.lose_life(v, 1, P, 'bombardment')
                s.check_deaths(P, 'bombardment')

    def my_sac_phase(s, P):
        s.bombard_lethal(P)
        if not s.my_worthwhile(P): return
        nt = s.nontoken_sac_ok(P)
        ouphe = s.stax_on(P, 'no_artifact_abilities')
        if P.has('Skullclamp') and not ouphe:
            while s.avail(P) >= 1:
                f = [p for p in P.creatures() if s.tough(p) <= 1 and s.fodder_ok(P, p)]
                if not f: break
                s.pay(P, 1); s.kill(f[0], 'sac', sac=True); P.draw(2); P.stats['clamp_draws'] += 2
        if s.my_free_outlet(P):
            for _ in range(P.pilot.get('max_sacs_per_phase', 30)):   # cap: token loops would otherwise never end
                f = s.my_fodder(P, nontoken_ok=nt)
                if not f: break
                s.kill(f, 'sac', sac=True)
                if not ouphe:
                    for n, m in s.OUTLET_MANA.items():
                        if P.has(n): P.pool += m; break
                if s.over: return
        if P.has('Evolutionary Leap'):
            while s.avail(P) >= 1 and nt:
                f = s.my_fodder(P)
                if not f: break
                s.pay(P, 1); s.kill(f, 'sac', sac=True)
                cr = [x for x in reversed(P.lib) if x.is_creature]
                if cr: P.lib.remove(cr[0]); P.hand.append(cr[0])
        if P.has('Phyrexian Tower') and not getattr(P, 'tower_used', False):
            f = s.my_fodder(P, nontoken_ok=nt)
            if f: s.kill(f, 'sac', sac=True); P.pool += 1; P.tower_used = True
        if P.has('Cauldron of Essence') and s.avail(P) >= 3:
            kw = P.pilot.get('recursion_keyword')
            back = [g for g in P.gy if g.is_creature and (not kw or kw in g.kw)]
            f = s.my_fodder(P)
            if back and f:
                s.pay(P, 3); s.kill(f, 'sac', sac=True); b = max(back, key=lambda g: g.cmc); P.gy.remove(b); s.resolve(P, b)
        if P.has('Phyrexian Reclamation') and s.avail(P) >= 2 and any(g.is_creature for g in P.gy):
            b = max([g for g in P.gy if g.is_creature], key=lambda g: g.cmc); s.pay(P, 2); s.lose_life(P, 2); P.gy.remove(b); P.hand.append(b)
        s.check_deaths(P, 'drain')

    def my_score(s, P, c, turn, post):
        opps = P.opps(); n = c.name; pr = P.pilot.get('priorities', {}); o = c.oracle
        stax_bad = [p for q in opps for p in q.bf if p.card and p.card.stax and set(p.card.stax) & {'no_triggers', 'no_dies', 'no_creature_abilities', 'no_artifact_abilities', 'no_cmd_cast', 'opp_minus'} and not p.neutral]
        if getattr(c, 'charm_wipe', False):
            small = sum(1 for q in opps for p in q.creatures() if s.tough(p) <= 1 and not p.neutral)
            mine_bad = sum(1 for p in P.creatures() if s.tough(p) <= 1 and not s.has_dt(p) and p.name in s.eng(P))
            if small >= 4 and small >= mine_bad + 3: return 125
        if c.edict and not c.removal and not c.wipe:
            vic = [q for q in opps if q.creatures()]
            lone = [q for q in opps if len(q.creatures()) == 1 and s.value(P, q.creatures()[0]) >= 6]
            return 95 if lone else (64 if len(vic) >= 2 else 0)
        if c.removal or n in NONTOKEN_EDICT_SPELLS or n in FLYER_EDICT_SPELLS:
            if stax_bad and c.removal:
                t = [p for p in stax_bad if s.targetable(p, P, c) and (c.removal['kind'] == 'any' or (c.removal['kind'] == 'creature') == p.creature)]
                if t and not (n in BITE and not P.creatures()): return 140
            if n in NONTOKEN_EDICT_SPELLS or n in FLYER_EDICT_SPELLS:
                vic = [q for q in opps if any((not p.token) for p in q.creatures())]
                return 66 if len(vic) >= 2 else 0
            hold = P.pilot.get('hold_removal_vs_combo', True) and any(q.combo_names for q in opps) and turn >= 4 and c.removal.get('instant')
            t = s.pick_removal_target(P, c, c.removal)
            if t is None: return 0
            v = s.value(P, t)
            if v < 4.5: return 0
            if hold and v < 9 and not post: return 0
            if hold and post and sum(1 for x in P.hand if x.removal) <= 1: return 0
            return 55 + v * 2
        if c.protect or c.counter or c.fog: return 0
        sp = getattr(c, 'special', None)
        copy = any(p.name == 'Aziza, Mage Tower Captain' for p in P.bf) and len(s.untapped(P)) >= 3
        if getattr(c, 'mob', False) or sp == 'charm4':
            dmg = (len(P.creatures()) if c.mob else 4) * (2 if copy else 1)
            if any(v.life <= dmg for v in opps): return 130
            return 55 if c.mob and dmg >= 10 and not post else 0
        if sp == 'warrens': return 120 if P.spells_turn >= 4 else 0
        if sp == 'hymn': return 72 if len(P.creatures()) >= 4 and any((x.is_instant or x.is_sorcery) and x is not c for x in P.hand) else 0
        if sp == 'jeska': return 76
        if sp == 'brass': return 62 if P.lands >= 6 else 0
        if getattr(c, 'x_tokens', False): return 25 if s.avail(P) - s.cost(P, c) >= 3 else 0
        if (c.is_instant or c.is_sorcery) and c.tokens_now and n not in pr: return 58
        if c.overrun:
            if c.overrun.get('infect'): return 150 if (not post and s.triumph_lethal(P)) else 0
            return s.ai_score(P, c, turn, post)
        if c.drain_now == 'TORMENT':
            x = s.avail(P) - 2
            return 130 if x >= 9 or any(v.life <= 3 * max(0, x - 6) for v in opps) else 0
        if c.wipe and not c.wipe.get('asym'):
            mine = sum(1 for p in P.bf if s.wipe_hits(P, c.wipe, p) and not p.token)
            theirs = sum(1 for q in opps for p in q.bf if s.wipe_hits(P, c.wipe, p))
            if theirs >= 5 and theirs >= mine + 3: return 90
            if not P.pilot.get('desperation_wipes', False): return 0
        if c.wipe or c.drain_now in ('X', 'X2', 'STORM') or c.ritual or any(c.name in cb for cb in P.combo_names):
            return s.ai_score(P, c, turn, post)
        if n in pr: return pr[n]
        if c.rock or c.ramp_lands:
            if P.cmd_zone and P.pilot.get('commander_first', True) and s.cost(P, P.cmd_card, True) <= s.avail(P) \
               and s.cost(P, c) + s.cost(P, P.cmd_card, True) > s.avail(P) and n != 'Sol Ring':
                return 80   # don't let ramp delay a castable commander
            return 110 if n == 'Sol Ring' else (100 if turn <= 5 else 30)
        if c.free_outlet and not c.is_land: return 90 if not s.my_free_outlet(P) and not P.has('Evolutionary Leap') else 35
        if c.is_creature: return 65 - c.cmc + (5 if any(k in c.kw for k in P.pilot.get('bonus_keywords', [])) else 0)
        if 'as an additional cost to cast this spell, sacrifice' in o:
            return 55 if s.my_fodder(P) and s.my_worthwhile(P) else 0
        if n == 'Phyrexian Reclamation': return 52 if any(g.is_creature for g in P.gy) else 20
        if (c.is_instant or c.is_sorcery) and re.search(r'return [^.]*creature cards? from your graveyard to your hand', o):
            return 45 if sum(1 for g in P.gy if g.is_creature) >= 2 else 0
        if c.draw_engine or c.death_trig or c.anthem or c.tokens_rec: return 74
        if c.is_aura: return s.ai_score(P, c, turn, post)
        if c.draw_now: return 50
        if c.tutor: return 64
        return 30

    def triumph_lethal(s, P):
        cr = [p for p in P.creatures() if s.can_attack(p)]
        if len(cr) < 2: return False
        kills = 0; pool = sorted(cr, key=lambda p: -(s.power(p) + 1))
        for v in sorted(P.opps(), key=lambda q: (10 - q.poison) + len(q.creatures())):
            need = 10 - v.poison; blk = len([b for b in v.creatures() if not b.tapped])
            use = []; tot = 0
            for p in list(pool):
                use.append(p); tot += s.power(p) + 1
                if tot - min(blk, len(use)) >= need: break
            if tot - min(blk, len(use)) >= need:
                kills += 1; [pool.remove(p) for p in use]
        return kills >= 1 and (kills >= len(P.opps()) - 1 or len(P.opps()) <= 2 or kills >= 2)

    def my_main(s, P, post=False):
        turn = s.round
        P.tower_used = False if not post else getattr(P, 'tower_used', False)
        prot = [x for x in P.hand if x.protect]
        hold_hi = min((x.cmc for x in prot), default=0) if prot and len(P.creatures()) >= 3 and turn >= 4 else 0
        ctr = [x for x in P.hand if x.counter]
        if ctr and P.pilot.get('hold_counters', True):
            hold_hi = max(hold_hi, min((s.cost(P, x) if x.counter['cost'] else 0) for x in ctr))
        for _ in range(14):
            if s.over or not P.alive: return
            opts = []
            if P.cmd_zone and s.can_cast_now(P, P.cmd_card, True) and turn >= 2: opts.append((96, P.cmd_card, True))
            for c in P.hand:
                if c.is_land or not s.can_cast_now(P, c): continue
                sc = s.my_score(P, c, turn, post)
                if sc > 0: opts.append((sc, c, False))
            s.codie_activate(P); s.prep_tap2(P)
            if s.check_combo(P): return
            opts += s.prep_options(P, lambda c: s.my_score(P, c, turn, post) if s.can_cast_now(P, c) else 0)
            opts.sort(key=lambda x: -x[0])
            done = False
            for sc, c, src in opts:
                cost = s.cost(P, c, src is True)
                res = hold_hi if sc < 100 else 0
                if c.removal and c.removal.get('instant'): pass
                if cost <= s.avail(P) - res:
                    if c.overrun and c.overrun.get('infect'):
                        s.cast(P, c); s.my_triumph_attack(P); done = True; break
                    if getattr(c, 'charm_wipe', False) and sc == 125:
                        s.pay(P, cost); P.hand.remove(c); P.gy.append(c); s.spell_triggers(P, c)
                        if not s.try_counter(P, c):
                            s.log(f'{P.label} Golgari Charm: all creatures -1/-1')
                            for p in [p for q in s.players if q.alive for p in q.creatures() if s.tough(p) <= 1]:
                                s.kill(p, 'sac', sac=True)
                            s.check_deaths(P, 'drain')
                        done = True; break
                    if isinstance(src, tuple): s.cast_prep(P, src[1]); done = True; break
                    s.cast(P, c, from_cmd=(src is True)); done = True; break
            s.my_sac_phase(P)
            if not done: break
        # Varragoth boast tutor at end of main 2
        if post:
            for p in P.bf:
                if p.name == 'Varragoth, Bloodsky Sire' and not p.sick and s.avail(P) >= 2:
                    want = None
                    for n in P.pilot.get('tutor_targets', []):
                        if not P.has(n) and not any(h.name == n for h in P.hand) and any(c.name == n for c in P.lib): want = n; break
                    if want:
                        c = next(c for c in P.lib if c.name == want); P.lib.remove(c); P.lib.append(c); s.pay(P, 2)

    def my_triumph_attack(s, P):
        for p in P.creatures(): p.pump += 1; p.pumpt += 1; p.infect_turn = True; p.tmpkw.add('trample')
        s.log(f'{P.label} INFECT ALPHA STRIKE')
        P.stats['triumph'] += 1
        # attack each opponent with enough creatures to kill (greedy), then let combat resolve for each
        pool = sorted([p for p in P.creatures() if s.can_attack(p)], key=lambda p: -s.power(p))
        for v in sorted(P.opps(), key=lambda q: (10 - q.poison) + len(q.creatures())):
            if not pool: break
            need = 10 - v.poison; blk = len([b for b in v.creatures() if not b.tapped]); use = []; tot = 0
            for p in list(pool):
                use.append(p); tot += s.power(p)
                if tot - min(blk, len(use)) >= need: break
            for p in use: pool.remove(p)
            s.forced_attack(P, v, use)
            if s.over: return

    def forced_attack(s, A, D, atk):
        for p in atk: p.tapped = True
        blocks = s.assign_blocks(D, atk, A)
        dead = []
        for a in atk:
            ap = s.power(a)
            if a in blocks:
                b = blocks[a]
                if 'trample' in s.kw(a): s.combat_hit(A, D, a, ap - 1)
                dead.append(b)
                if s.has_dt(b) or s.power(b) >= s.tough(a): dead.append(a)
            else: s.combat_hit(A, D, a, ap)
        for p in dead:
            if p in p.owner.bf: s.kill(p, 'damage')
        s.check_deaths(A, 'poison')

    # ---------------------------------------------------------------- game loop
    def snapshot(s):
        for P in s.players:
            if not P.alive: continue
            cr = P.creatures()
            s.log(f'   [{P.label}] life {P.life} poison {P.poison} lands {P.lands} hand {len(P.hand)} creatures {len(cr)} '
                  f'(tokens {sum(1 for p in cr if p.token)}, power {sum(s.power(p) for p in cr)}) '
                  f'key: {", ".join(p.name for p in P.bf if p.card and not p.card.is_land and (p.is_cmd or p.card.stax or p.card.death_trig or p.card.draw_engine or p.card.anthem))[:160]}')

    def play(s):
        while not s.over and s.round < s.max_rounds:
            if s.logging and s.round: s.snapshot()
            s.round += 1
            for P in list(s.players):
                if s.over: break
                if not P.alive: continue
                s.take_turn(P)
                s.check_deaths(None, 'life')
                # end-of-turn instant removal from others on the biggest threat (uses leftover reserve)
                for Q in s.players:
                    if Q is P or not Q.alive or s.over: continue
                    for x in list(Q.hand):
                        if x.removal and x.removal.get('instant') and not x.counter and Q.reserve >= s.cost(Q, x) + (2 if Q.is_me else 0):
                            if x.name in BITE and not Q.creatures(): continue
                            t = s.pick_removal_target(Q, x, x.removal)
                            if t is not None and s.value(Q, t) >= 7:
                                Q.reserve -= s.cost(Q, x); Q.hand.remove(x); s.use_removal(Q, x, x.removal, target=t); Q.gy.append(x)
                                break
                s.check_deaths(None, 'life')
        return s.winner
