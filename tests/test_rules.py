"""Rules checks for the gauntlet engine (Comprehensive Rules numbers in each test).
Run: python3 -m pytest tests/test_rules.py -q"""
import os, sys, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import engine as E, cards as CD, counters as CT

def game(deck_a=None, deck_b=None, n=2):
    base = ['Plains'] * 99
    specs = [('A', ['Isamaru, Hound of Konda'] + (deck_a or base), True, 'x', 3, {}),
             ('B', ['Isamaru, Hound of Konda'] + (deck_b or base), False, 'y', 3, {})]
    specs += [('C', ['Isamaru, Hound of Konda'] + base, False, 'z', 3, {}) for _ in range(n - 2)]
    g = E.Game(specs, random.Random(1), on_play=0)
    for P in g.players: P.hand = []; P.bf = []
    g.active = g.players[0]
    return g, g.players[0], g.players[1]

def tok(P, name, p, t, kw=()):
    x = E.Perm(P, token=(name, p, t, set(kw))); x.sick = False; P.bf.append(x); return x

def test_first_strike_blocker_kills_first():   # CR 510.4, 702.7b
    g, A, D = game(); a = tok(A, 'Atk', 2, 2); b = tok(D, 'FS', 2, 2, {'first strike'})
    g.resolve_combat(A, D, None, [a], {a: [b]})
    assert a not in A.bf and b in D.bf

def test_double_strike_hits_twice():           # CR 702.4
    g, A, D = game(); a = tok(A, 'DS', 3, 3, {'double strike'}); life = D.life
    g.resolve_combat(A, D, None, [a], {})
    assert D.life == life - 6

def test_double_strike_kills_blocker_before_regular_damage():
    g, A, D = game(); a = tok(A, 'DS', 2, 2, {'double strike'}); b = tok(D, 'B', 2, 2)
    g.resolve_combat(A, D, None, [a], {a: [b]})
    assert a in A.bf and b not in D.bf

def test_menace_needs_two_blockers():          # CR 702.111b
    g, A, D = game(); a = tok(A, 'Men', 3, 3, {'menace'}); tok(D, 'B1', 4, 4)
    assert g.assign_blocks(D, [a], A) == {}

def test_gang_block_on_big_attacker():         # CR 509.1a
    g, A, D = game(); a = tok(A, 'Big', 5, 5); tok(D, 'B1', 3, 3); tok(D, 'B2', 3, 3)
    blocks = g.assign_blocks(D, [a], A)
    assert a in blocks and len(blocks[a]) == 2

def test_trample_deathtouch_assigns_one():     # CR 702.19c
    g, A, D = game(); a = tok(A, 'TD', 5, 5, {'trample', 'deathtouch'}); b = tok(D, 'Wall', 0, 8); life = D.life
    g.resolve_combat(A, D, None, [a], {a: [b]})
    assert D.life == life - 4 and b not in D.bf

def test_blocked_attacker_without_trample_deals_no_player_damage():  # CR 510.1c
    g, A, D = game(); a = tok(A, 'A', 5, 5); b = tok(D, 'B', 1, 1); life = D.life
    g.resolve_combat(A, D, None, [a], {a: [b]})
    assert D.life == life

def test_damage_to_planeswalker_removes_loyalty():  # CR 120.3c, 704.5i
    g, A, D = game(); a = tok(A, 'A', 3, 3)
    w = E.Perm(D, CD.get('Ajani Steadfast')); w.walker = True; w.loyalty = 3; D.bf.append(w)
    g.resolve_combat(A, D, w, [a], {})
    assert w not in D.bf

def test_hand_size_seven():                    # CR 402.2, 514.1
    g, A, D = game(); A.hand = [CD.get('Plains')] * 10
    g.end_step(A)
    assert len(A.hand) == 7

def test_tapland_makes_no_mana_turn_played():  # CR 614.1c
    g, A, D = game()
    assert g.land_untapped(A, CD.get('Frontier Bivouac'), 3) is False
    assert g.land_untapped(A, CD.get('Plains'), 0) is True
    assert g.land_untapped(A, CD.get('Inspiring Vantage'), 4) is False

def test_colours_needed():                     # CR 106.1, 202.1
    g, A, D = game(); A.lands = 3; A.land_cols = [frozenset('W')] * 3; A.identity = frozenset('RW')
    assert g.colors_ok(A, CD.get('Swords to Plowshares'))
    assert not g.colors_ok(A, CD.get('Lightning Bolt'))

def test_uncounterable():                      # "This spell can't be countered"
    g, A, D = game(); D.hand = [CD.get('Counterspell')]; D.reserve = 5
    assert g.try_counter(A, CD.get('Ruric Thar, Magecrusher')) is False

def test_ward_counters_removal_without_payment():  # CR 702.21a
    g, A, D = game(); A.pool = 0; A.treasure = 0
    t = E.Perm(D, CD.get('Adrix and Nev, Twincasters')); D.bf.append(t)
    assert g.pay_ward(A, t) is False and t in D.bf

def test_legend_rule():                        # CR 704.5j
    g, A, D = game()
    g.resolve(A, CD.get('Isamaru, Hound of Konda')); g.resolve(A, CD.get('Isamaru, Hound of Konda'))
    assert sum(1 for p in A.bf if p.name == 'Isamaru, Hound of Konda') == 1

def test_partner_starts_in_command_zone_and_tax_per_cast():  # CR 903.6, 702.124d, 903.8
    specs = [('A', ['Kraum, Ludevic\'s Opus', 'Tymna the Weaver'] + ['Plains'] * 98, True, 'x', 3, {}),
             ('B', ['Isamaru, Hound of Konda'] + ['Plains'] * 99, False, 'y', 3, {})]
    g = E.Game(specs, random.Random(2), on_play=0); A = g.players[0]
    assert A.cmd2 is not None and A.cmd2.name == 'Tymna the Weaver' and A.cmd2_zone
    assert all(c.name != 'Tymna the Weaver' for c in A.lib + A.hand)
    A.pool = 20; g.cast(A, A.cmd2, from_cmd=2)
    assert A.cmd2_tax == 2 and A.cmd_tax == 0

def test_commander_damage_counted_per_commander():  # CR 903.10a, 702.124d
    g, A, D = game(); a = tok(A, 'Cmd', 11, 11); a.is_cmd = True
    g.combat_hit(A, D, a, 11); g.combat_hit(A, D, a, 11); g.check_deaths(A)
    assert not D.alive

# ---------------------------------------------------------------- combos with spell pieces (roadmap 0.1)
def perm(P, name):
    x = E.Perm(P, CD.get(name)); x.sick = False; P.bf.append(x); return x

def test_combo_spell_piece_cast_from_hand_wins():   # CR 601.2: a combo's instant/sorcery piece is cast, not on the battlefield
    g, A, D = game(); A.combo_names = [('Xorn', 'Crackle with Power')]
    perm(A, 'Xorn'); A.hand = [CD.get('Crackle with Power')]; A.pool = 10; A.lands = 10; A.land_cols = [frozenset('R')] * 10
    assert g.check_combo(A)
    assert not D.alive and any(c.name == 'Crackle with Power' for c in A.gy)

def test_combo_spell_piece_needs_mana():
    g, A, D = game(); A.combo_names = [('Xorn', 'Crackle with Power')]
    perm(A, 'Xorn'); A.hand = [CD.get('Crackle with Power')]; A.pool = 1; A.lands = 1; A.land_cols = [frozenset('R')]
    assert not g.check_combo(A) and D.alive

def test_combo_spell_piece_can_be_countered():      # CR 701.6
    g, A, D = game(); A.combo_names = [('Xorn', 'Crackle with Power')]
    perm(A, 'Xorn'); A.hand = [CD.get('Crackle with Power')]; A.pool = 10; A.lands = 10; A.land_cols = [frozenset('R')] * 10
    D.hand = [CD.get('Counterspell')]; D.reserve = 2; D.lands = 2; D.land_cols = [frozenset('U')] * 2
    assert not g.check_combo(A) and D.alive
    assert any(c.name == 'Crackle with Power' for c in A.gy)

def test_pure_combo_spell_is_not_cast_as_filler():
    g, A, D = game(); A.combo_names = [('Isochron Scepter', 'Dramatic Reversal')]
    A.hand = [CD.get('Dramatic Reversal')]; A.pool = 5
    assert g.ai_score(A, A.hand[0], 5, False) == 0

# ---------------------------------------------------------------- Isochron Scepter imprint (roadmap 0.2)
def scepter_setup(rocks=('Sol Ring', 'Arcane Signet'), hand=('Grapeshot',)):
    g, A, D = game(); A.combo_names = [('Isochron Scepter', 'Dramatic Reversal')]
    for r in rocks: perm(A, r)
    A.hand = [CD.get('Dramatic Reversal'), CD.get('Opt')] + [CD.get(h) for h in hand]
    A.pool = 6; A.lands = 6; A.land_cols = [frozenset('UR')] * 6
    g.resolve(A, CD.get('Isochron Scepter'))
    return g, A, D

def test_scepter_imprints_combo_partner():     # CR 406.6, 607.2a: imprint happens as it enters
    g, A, D = scepter_setup()
    sc = next(p for p in A.bf if p.name == 'Isochron Scepter')
    assert sc.imprint.name == 'Dramatic Reversal' and not any(c.name == 'Dramatic Reversal' for c in A.hand)

def test_scepter_reversal_wins_with_rocks_and_outlet():
    g, A, D = scepter_setup()
    assert g.check_combo(A) and not D.alive

def test_scepter_reversal_needs_three_rock_mana():
    g, A, D = scepter_setup(rocks=('Arcane Signet',))
    assert not g.check_combo(A) and D.alive

def test_scepter_reversal_needs_an_outlet():
    g, A, D = scepter_setup(hand=())
    assert not g.check_combo(A) and D.alive

def test_reversal_in_hand_without_imprint_is_no_combo():
    g, A, D = game(); A.combo_names = [('Isochron Scepter', 'Dramatic Reversal')]
    perm(A, 'Isochron Scepter'); perm(A, 'Sol Ring'); perm(A, 'Arcane Signet')
    A.hand = [CD.get('Dramatic Reversal'), CD.get('Grapeshot')]; A.pool = 6
    assert not g.check_combo(A) and D.alive

def test_scepter_reversal_with_draw_engine_finds_finisher():
    g, A, D = scepter_setup(hand=())
    perm(A, 'Archmage Emeritus'); A.lib.append(CD.get('Grapeshot'))
    assert g.check_combo(A) and not D.alive

# ---------------------------------------------------------------- combo auras (roadmap 0.3)
SANAR_XORN = ('Sanar, Unfinished Genius', 'Freed from the Real', 'Xorn', 'Weftstalker Ardent')

def test_combo_aura_enchants_its_host():       # CR 303.4a: an Aura spell targets what it will enchant
    g, A, D = game(); A.combo_names = [SANAR_XORN]
    big = tok(A, 'Big', 6, 6); sanar = perm(A, 'Sanar, Unfinished Genius'); perm(A, 'Xorn')
    g.resolve(A, CD.get('Freed from the Real'))
    aura = next(p for p in A.bf if p.name == 'Freed from the Real')
    assert aura.attached is sanar

def test_combo_needs_aura_on_host():
    g, A, D = game(); A.combo_names = [SANAR_XORN]
    perm(A, 'Xorn'); perm(A, 'Weftstalker Ardent'); x = perm(A, 'Sanar, Unfinished Genius')
    a = E.Perm(A, CD.get('Freed from the Real')); a.creature = False; a.attached = next(p for p in A.bf if p.name == 'Xorn'); A.bf.append(a)
    assert not g.check_combo(A) and D.alive
    a.attached = x
    assert g.check_combo(A) and not D.alive

def test_aura_goes_to_graveyard_when_host_dies():   # CR 303.4c, 704.5m
    g, A, D = game(); A.combo_names = [SANAR_XORN]
    sanar = perm(A, 'Sanar, Unfinished Genius')
    g.resolve(A, CD.get('Freed from the Real'))
    g.kill(sanar)
    assert not A.has('Freed from the Real') and any(c.name == 'Freed from the Real' for c in A.gy)

def test_combo_aura_held_until_host_is_out():
    g, A, D = game(); A.combo_names = [SANAR_XORN]
    tok(A, 'Big', 6, 6); A.pool = 5
    assert g.ai_score(A, CD.get('Freed from the Real'), 5, False) == 0

# ---------------------------------------------------------------- Sanar's spells and generic tags (roadmap 0.4)
def test_spellseeker_tutor_respects_type_and_mana_value():   # CR 701.23
    g, A, D = game(); A.combo_names = []
    A.lib = [CD.get('Nexus of Fate'), CD.get('Xorn'), CD.get('Dramatic Reversal')]
    g.resolve(A, CD.get('Spellseeker'))
    assert [c.name for c in A.hand] == ['Dramatic Reversal']

def test_cost_reducer_applies_to_instants():   # CR 601.2f
    g, A, D = game(); perm(A, 'Goblin Electromancer')
    assert g.cost(A, CD.get('Frantic Search')) == 2 and g.cost(A, CD.get('Xorn')) == 3

def test_look_at_top_counts_as_draw():
    assert CD.get('Stock Up').draw_now == 2 and CD.get('Sleight of Hand').draw_now == 1
    assert CD.get('Strike It Rich').treasure_now == 1

def test_nexus_of_fate_extra_turn_and_shuffles_back():   # CR 500.7, 614.1a
    g, A, D = game(); A.lib = [CD.get('Plains')] * 10; A.pool = 7
    g.resolve(A, CD.get('Nexus of Fate'))
    assert A.extra_turns == 1 and any(c.name == 'Nexus of Fate' for c in A.lib) and not any(c.name == 'Nexus of Fate' for c in A.gy)

def test_brain_freeze_mills_three_per_storm_copy():   # CR 702.40a
    g, A, D = game(); D.lib = [CD.get('Plains')] * 20; A.spells_turn = 4
    g.special_effect(A, CD.get('Brain Freeze'), 'brainfreeze')
    assert len(D.lib) == 8

def test_crackle_with_power_kills_with_enough_mana():
    g, A, D = game(); A.pool = 12; D.life = 15
    assert g.special_score(A, CD.get('Crackle with Power'), 'crackle', False) == 140
    A.pool = 2; g.cost(A, CD.get('Crackle with Power'))
    assert g.special_score(A, CD.get('Crackle with Power'), 'crackle', False) == 0

# --- roadmap 0.5: top blank staples
def test_natures_lore_fetches_a_forest_onto_the_battlefield():   # CR 701.19b, 305.1
    g, A, D = game()
    c = CD.get("Nature's Lore")
    assert c.ramp_lands == 1 and c.ramp_col == 'g'    # it names its basic type and never says the word "land"
    A.lands = 0; A.land_cols = []
    g.spell_effect(A, c)
    assert A.lands == 1 and A.land_cols == [frozenset('g')]

def test_three_visits_fetches_a_land():   # CR 701.19b; this printing names one Forest
    g, A, D = game()
    c = CD.get('Three Visits')
    assert c.ramp_lands == 1 and c.ramp_col == 'g'
    A.lands = 0; A.land_cols = []
    g.spell_effect(A, c)
    assert A.lands == 1 and A.land_cols == [frozenset('g')]

def test_untyped_land_fetch_still_gives_any_colour():   # "up to two basic land cards": no colour named, any basic will do
    g, A, D = game()
    c = CD.get('Cultivate')
    assert c.ramp_lands == 2 and c.ramp_col is None
    A.lands = 0; A.land_cols = []
    g.spell_effect(A, c)
    # Cultivate's second land goes to hand, so only the first lands on the battlefield (CR 305.7)
    assert A.land_cols == [frozenset('*')]

def test_deflecting_swat_is_a_free_counter():   # CR 701.36a redirects; modelled as stopping a spell, free with a commander
    c = CD.get('Deflecting Swat')
    assert c.counter == dict(scope='any', cost=0, soft=0, mvmin=0)

def count_etb(g):
    """Count apply_effect calls, since individual ETB effects are probabilistic in the AI model."""
    n = [0]; real = g.apply_effect
    def spy(q, e, why=''):
        n[0] += 1; return real(q, e, why=why)
    g.apply_effect = spy
    return n

def test_panharmonicon_doubles_etb_triggers_of_artifact_creature_entry():   # CR 706.2a
    g, A, D = game()
    src = CD.get('Rook Turret')          # an artifact: when it enters, you draw a card
    assert src.is_artifact and src.etb_trig
    turret = E.Perm(A, src); turret.neutral = False; A.bf.append(turret)
    n = count_etb(g)
    g.etb_triggers(A, [turret])
    assert n[0] == 1
    ph = E.Perm(A, CD.get('Panharmonicon')); ph.neutral = False; A.bf.append(ph)
    g.etb_triggers(A, [turret])
    assert n[0] == 3                   # one before, then two more

def test_panharmonicon_leaves_etb_triggers_alone_when_its_controller_is_not_the_one_entering():   # CR 706.2a: "you control"
    g, A, D = game()
    ph = E.Perm(D, CD.get('Panharmonicon')); ph.neutral = False; D.bf.append(ph)
    turret = E.Perm(A, CD.get('Rook Turret')); turret.neutral = False; A.bf.append(turret)
    n = count_etb(g)
    g.etb_triggers(A, [turret])
    assert n[0] == 1                   # D's Panharmonicon does not double A's trigger

def test_panharmonicon_does_not_double_for_a_planeswalker_entry():   # CR 706.2a: only artifacts and creatures
    g, A, D = game()
    ph = E.Perm(A, CD.get('Panharmonicon')); ph.neutral = False; A.bf.append(ph)
    pw = CD.get('Nissa, Who Shakes the World')
    assert pw.is_planeswalker and not pw.is_artifact and not pw.is_creature
    henge = E.Perm(A, CD.get('The Great Henge')); henge.neutral = False; A.bf.append(henge)
    n = count_etb(g)
    g.etb_triggers(A, [E.Perm(A, pw)])
    assert n[0] == 1                   # the Henge's trigger fires once, not doubled: Nissa is a planeswalker

def test_victimize_sacrifices_a_creature_and_returns_two_tapped():   # CR 603.6b, 302.6 (enters tapped)
    g, A, D = game()
    big1, big2 = CD.get('Abzan Devotee'), CD.get('Abzan Falconer')   # both plain 2- and 3-mana bodies
    food = tok(A, 'Sacrifice me', 1, 1)
    A.gy += [big1, big2]; A.bf = [food]
    n = g.gy_rec_resolve(A, CD.get('Victimize'))
    assert n == 2 and food not in A.bf                       # paid with the cheapest body on the board
    out = [p for p in A.bf if p.card in (big1, big2)]
    assert len(out) == 2 and all(p.tapped for p in out)
    assert all(p.sick for p in out)                # they enter with summoning sickness

def test_victimize_needs_a_creature_to_sacrifice():   # CR 603.6b, "sacrifice a creature. If you do"
    g, A, D = game()
    A.gy.append(CD.get('Colossal Rattlewurm'))
    assert g.gy_rec_resolve(A, CD.get('Victimize')) == 0
    assert not A.bf

def test_sun_titan_recurs_a_permanent_with_mana_value_3_or_less():   # CR 603.6b
    g, A, D = game()
    titan = CD.get('Sun Titan')
    ok, big = CD.get('Abzan Falconer'), CD.get('Colossal Rattlewurm')
    assert ok.is_creature and ok.cmc <= 3 < big.cmc
    assert titan.gy_rec == dict(mv=3, kind=None)
    A.gy += [ok, big]
    assert g.gy_rec_resolve(A, titan) == 1
    assert any(p.card is ok for p in A.bf) and not any(p.card is big for p in A.bf)

# ---------------------------------------------------------------- roadmap 0.5 batch 3: last named blank staples
def test_wild_growth_aura_adds_mana_to_a_land():   # CR 305.7, 106.1: "enchanted land adds an additional {G}"
    g, A, D = game(); c = CD.get('Wild Growth')
    assert c.is_aura and c.land_aura == 1 and c.land_aura_col == frozenset('G')
    A.lands = 3; A.land_cols = [frozenset('U')] * 3
    g.resolve(A, c)
    assert any(x.name == 'Wild Growth' for x in A.bf)              # no creature to enchant: it just stays on the land
    assert g.mana_avail(A) == 4                                     # 3 lands + the aura's extra {G}
    assert g.colors_ok(A, CD.get('Giant Growth'))                   # the {G} pays the pip although only U lands
    assert g.ai_score(A, CD.get('Wild Growth'), 2, False) == 84     # the AI plays it as a mana producer
    A.lands = 0
    assert g.ai_score(A, CD.get('Wild Growth'), 2, False) == 0      # ... but not onto an enchanted land it doesn't have

def test_rhythm_of_the_wild_makes_creature_spells_uncounterable():  # CR 101.2, static: "creature spells you control can't be countered"
    g, A, D = game()
    D.hand = [CD.get('Counterspell')]; D.reserve = 5
    assert g.try_counter(A, CD.get('Rune-Scarred Demon')) is True and not D.hand   # D would counter it
    D.hand = [CD.get('Counterspell')]; D.reserve = 5
    perm(A, 'Rhythm of the Wild')
    assert g.try_counter(A, CD.get('Rune-Scarred Demon')) is False and len(D.hand) == 1   # ... now it can't

def test_rhythm_of_the_wild_riot_choice():   # CR 702.105: riot enters with a +1/+1 counter or haste
    g, A, D = game(); g.active = A
    perm(A, 'Rhythm of the Wild')
    g.resolve(A, CD.get('Colossal Rattlewurm'))   # 6/5: swings this turn, so it chooses haste
    adult = next(p for p in A.bf if p.name == 'Colossal Rattlewurm')
    assert not adult.sick and adult.counters == 0
    g.resolve(A, CD.get('Grizzly Bears'))         # 2/2: can't win a fight, so it takes the counter
    cub = next(p for p in A.bf if p.name == 'Grizzly Bears')
    assert cub.sick and cub.counters == 1

def test_seedborn_muse_untaps_your_permanents_on_other_turns():   # CR 502.1, 503.3: "during each other player's untap step"
    g, A, D = game()
    perm(A, 'Seedborn Muse'); atk = tok(A, 'Guard', 3, 3); atk.tapped = True
    g.take_turn(D)
    assert not atk.tapped                       # tapped after A's turn, untapped during D's untap step

def test_hardened_scales_adds_an_extra_counter():   # CR 122.1c: replacement effect "that many plus one"
    g, A, D = game()
    perm(A, 'Hardened Scales')
    a = tok(A, 'Sentry', 1, 1); CT.add(g, a, 1)
    assert a.counters == 2
    b = tok(A, 'Guard', 1, 1); CT.add(g, b, 3)
    assert b.counters == 4
    e = tok(D, 'Enemy', 1, 1); CT.add(g, e, 1)
    assert e.counters == 1                      # "a creature you control": only your own get the extra
    ap = perm(A, "Ajani's Pridemate"); g.gain(A, 1)
    assert ap.counters == 2                     # engine life-gain trigger routes through the same replacement

def test_phyrexian_metamorph_copies_a_creature():   # CR 707: "enters as a copy of any artifact or creature"
    g, A, D = game()
    big = perm(D, 'Rune-Scarred Demon')           # 6/6 flyer waiting on the board
    g.resolve(A, CD.get('Phyrexian Metamorph'))
    p = next(x for x in A.bf if x.name == 'Phyrexian Metamorph')
    assert p.creature and p.bp == 6 and p.bt == 6 and 'flying' in p.kw
    assert p.card is big.card                     # the copy inherits the card, so its tags follow
    g.resolve(A, CD.get('Phyrexian Metamorph'))   # with nothing new worth copying it copies the same 6/6
    q = [x for x in A.bf if x.name == 'Phyrexian Metamorph']
    assert len(q) == 2 and all(x.bp == 6 for x in q)

# ---------------------------------------------------------------- roadmap 0.6: basic equipment
def test_equipment_attaches_to_the_best_creature():   # CR 301.5c, 702.30: Equip attaches to a creature you control
    g, A, D = game()
    c = CD.get('Bone Saw')                            # Equipped creature gets +1/+0, Equip {1}
    assert c.equip == 1 and c.equip_bonus == {'p': 1, 't': 0, 'kw': set()}
    bear = tok(A, 'Bear', 2, 2); hog = tok(A, 'Hog', 3, 5)
    g.resolve(A, c)
    saw = next(x for x in A.bf if x.name == 'Bone Saw')
    assert saw.attached is hog and g.power(hog) == 4 and g.power(bear) == 2   # the strongest creature got the +1/+0
    assert g.tough(hog) == 5                                                  # the bonus is static, not just for combat
    assert g.ai_score(A, CD.get('Bone Saw'), 2, False) >= 60                  # the AI casts a useful sword

def test_equipment_prefers_commander_for_defensive_bonuses():   # CR 301.5c: hexproof/haste boots go on the commander
    g, A, D = game()
    hog = tok(A, 'Hog', 6, 6)
    cmd = tok(A, 'General', 2, 2); cmd.is_cmd = True
    g.resolve(A, CD.get('Swiftfoot Boots'))          # Equipped creature has hexproof and haste
    boots = next(x for x in A.bf if x.name == 'Swiftfoot Boots')
    assert boots.attached is cmd                     # prefers the commander, not the 6/6
    assert 'hexproof' in g.kw(cmd) and 'haste' in g.kw(cmd)

def test_equipment_survives_its_creature():   # CR 704.5n: an unattached Equipment stays on the battlefield
    g, A, D = game()
    hog = tok(A, 'Hog', 3, 3)
    g.resolve(A, CD.get('Bone Saw'))
    saw = next(x for x in A.bf if x.name == 'Bone Saw')
    g.kill(hog, 'combat')
    assert hog not in A.bf and saw in A.bf and saw.attached is None
    assert not any(x.name == 'Bone Saw' for x in A.gy)     # Equipment does not follow the creature to the graveyard

def test_sword_hit_triggers_draw_when_equipped_creature_attacks():   # "Whenever equipped creature deals combat damage ... draw a card"
    g, A, D = game(); g.active = A
    c = CD.get('Sword of Fire and Ice')               # +2/+2, "you draw a card" on combat damage (Sword of X and Y)
    assert c.equip == 2 and c.equip_hit == 'draw'
    bearer = tok(A, 'Bearer', 3, 3)
    g.resolve(A, c)
    sword = next(x for x in A.bf if x.name == 'Sword of Fire and Ice')
    assert sword.attached is bearer and g.power(bearer) == 5
    g.combat(A)                                       # the equipped creature deals combat damage, read as an attack trigger
    assert len(A.hand) == 1

# ---------------------------------------------------------------- roadmap 0.7: fairer removal targets
def test_removal_spares_the_commander_for_a_comparable_threat():   # CR 903: it recurs from the command zone
    g, A, D = game()
    cm = perm(D, 'Isamaru, Hound of Konda'); cm.is_cmd = True        # 2/1 commander (worth ~7.3 to remove)
    wolf = perm(D, 'Zada, Hedron Grinder')                         # 3/3 non-commander, within ~4 points of it
    assert g.pick_removal_target(A, CD.get('Murder'), {'kind': 'creature', 'how': 'destroy'}) is wolf
    assert cm in D.bf                                                # the commander survives to be cast again

def test_removal_still_targets_a_threatening_commander():   # CR 903: ... but not when it clearly outranks the board
    g, A, D = game()
    cm = perm(D, 'Isamaru, Hound of Konda'); cm.is_cmd = True        # 2/1 commander is the biggest threat here
    mite = tok(D, 'Mite', 4, 4)                                      # small token is not within ~4 points of it
    assert g.pick_removal_target(A, CD.get('Murder'), {'kind': 'creature', 'how': 'destroy'}) is cm

# ---------------------------------------------------------------- roadmap 0.5 batch 4: honest coverage + next-30 gaps
def test_cathars_crusade_pumps_every_creature_as_they_enter():   # CR 122.1a just checks counters; 604.2: "Whenever a creature you control enters..."
    g, A, D = game()
    perm(A, "Cathars' Crusade")                                  # "put a +1/+1 counter on each creature you control"
    soldier = tok(A, 'Soldier', 1, 1)
    g.resolve(A, CD.get('Grizzly Bears'))                        # the entering bear counts too
    bear = next(x for x in A.bf if x.name == 'Grizzly Bears')
    assert soldier.counters == 1 and bear.counters == 1
    g.resolve(A, CD.get('Runeclaw Bear'))                        # a second enter re-pumps everyone
    rune = next(x for x in A.bf if x.name == 'Runeclaw Bear')
    assert soldier.counters == 2 and bear.counters == 2 and rune.counters == 1

def test_fact_or_fiction_is_tagged_as_a_big_draw():             # CR 701.14: revealed piles into your hand — modelled as a deep draw
    g, A, D = game()
    c = CD.get('Fact or Fiction')
    assert c.draw_now == 3
    g.resolve(A, c)
    assert len(A.hand) == 3
    assert any('Fact or Fiction' in x.name for x in A.gy)

# ---------------------------------------------------------------- Pirates / Admiral Beckett Brass (theft + typal)
def pgame(n=2):
    """A game whose 'me' deck (player A) has the Pirate pilot (chosen_type: Pirate)."""
    base = ['Plains'] * 99
    specs = [('A', ['Isamaru, Hound of Konda'] + base, True, 'x', 3, {'chosen_type': 'Pirate'}),
             ('B', ['Isamaru, Hound of Konda'] + base, False, 'y', 3, {})]
    specs += [('C', ['Isamaru, Hound of Konda'] + base, False, 'z', 3, {}) for _ in range(n - 2)]
    g = E.Game(specs, random.Random(1), on_play=0)
    for P in g.players: P.hand = []; P.bf = []
    g.active = g.players[0]
    return g, g.players[0], g.players[1]

def test_steal_eot_returns_at_cleanup():          # CR 613: control-change until end of turn
    g, A, B = pgame(); t = perm(B, 'Llanowar Elves')
    assert g.steal(A, t, 'eot', untap=True, haste=True, pirate=True)
    assert t in A.bf and t.owner is A and 'pirate' in t.made_types
    g.return_eot_steals()
    assert t in B.bf and t.owner is B and t.made_types == set()

def test_stolen_permanent_dies_to_owners_graveyard():   # CR 400.3, 903.9a: a card goes to its owner's zones
    g, A, B = pgame(); t = perm(B, 'Llanowar Elves')
    g.steal(A, t, 'permanent'); assert t in A.bf
    g.kill(t, 'destroy')
    assert any(c.name == 'Llanowar Elves' for c in B.gy)
    assert not any(c.name == 'Llanowar Elves' for c in A.gy)

def test_stolen_commander_returns_to_owners_command_zone():   # CR 903.9: commander goes to the command zone
    g, A, B = pgame(); c = E.Perm(B, CD.get('Isamaru, Hound of Konda'), is_cmd=True); c.sick = False
    B.bf.append(c); B.cmd_zone = False
    g.steal(A, c, 'permanent'); assert c in A.bf
    g.kill(c, 'destroy')
    assert B.cmd_zone is True and not any(x.name == 'Isamaru, Hound of Konda' for x in A.gy)

def test_beckett_steals_from_a_three_pirate_player():   # Admiral Beckett Brass end-step trigger
    g, A, B = pgame(); g.round = 5
    bk = E.Perm(A, CD.get('Admiral Beckett Brass'), is_cmd=True); bk.sick = False; A.bf.append(bk)
    loot = perm(B, 'Llanowar Elves')
    pir = [tok(A, f'P{i}', 2, 2) for i in range(3)]
    for p in pir: p.made_types = {'pirate'}; g.combat_hit(A, B, p, 2)
    assert len(g.pirate_dmg[B.idx]) == 3
    g.end_step(A)
    assert loot in A.bf and loot.owner is A            # stolen permanently

def test_beckett_needs_three_pirates():
    g, A, B = pgame(); g.round = 5
    bk = E.Perm(A, CD.get('Admiral Beckett Brass'), is_cmd=True); bk.sick = False; A.bf.append(bk)
    loot = perm(B, 'Llanowar Elves')
    for i in range(2):
        p = tok(A, f'P{i}', 2, 2); p.made_types = {'pirate'}; g.combat_hit(A, B, p, 2)
    g.end_step(A)
    assert loot in B.bf                                # only two Pirates: no steal

def test_kindred_dominance_spares_chosen_type():   # CR 700.3: destroy creatures not of the chosen type
    g, A, B = pgame()
    pir = perm(A, 'Coercive Recruiter'); nonpir = perm(A, 'Llanowar Elves'); opp_pir = perm(B, 'Coercive Recruiter')
    kd = CD.get('Kindred Dominance'); g.do_wipe(A, kd, kd.wipe)
    assert pir in A.bf and opp_pir in B.bf and nonpir not in A.bf

def test_kindred_dominance_without_chosen_type_is_unchanged():   # legacy fallback: spares the caster's board
    g, A, D = game()                                   # plain game, no chosen_type
    mine = perm(A, 'Grizzly Bears'); theirs = perm(D, 'Grizzly Bears')
    kd = CD.get('Kindred Dominance'); g.do_wipe(A, kd, kd.wipe)
    assert mine in A.bf and theirs not in D.bf

def test_pirate_lord_buffs_other_pirates_only():   # Admiral Beckett Brass: other Pirates you control get +1/+1
    g, A, B = pgame()
    bk = E.Perm(A, CD.get('Admiral Beckett Brass'), is_cmd=True); bk.sick = False; A.bf.append(bk)
    other = perm(A, 'Coercive Recruiter')
    base = CD.get('Coercive Recruiter').power
    assert g.power(other) == base + 1                  # the other Pirate is buffed
    assert g.power(bk) == CD.get('Admiral Beckett Brass').power   # not itself

def test_lords_inert_without_chosen_type():        # opponents / decks without the key are unaffected
    g, A, D = game()
    bk = E.Perm(A, CD.get('Admiral Beckett Brass')); bk.sick = False; A.bf.append(bk)
    other = perm(A, 'Coercive Recruiter')
    assert g.power(other) == CD.get('Coercive Recruiter').power   # no chosen_type -> no buff

def test_cover_of_darkness_fear():                 # CR 702.36: blockable only by artifact and/or black creatures
    g, A, B = pgame(); perm(A, 'Cover of Darkness')
    att = tok(A, 'Pir', 3, 3); att.made_types = {'pirate'}
    tok(B, 'White', 3, 3)                              # colourless token: cannot block
    assert g.blockers_for(B, att, set()) == []

def test_coercive_recruiter_steals_on_pirate_etb():   # Coercive Recruiter ETB-of-a-Pirate trigger
    g, A, B = pgame()
    rec = perm(A, 'Coercive Recruiter'); target = perm(B, 'Llanowar Elves')
    g.etb_triggers(A, [rec])                           # a Pirate (the Recruiter) entered
    assert target in A.bf and 'pirate' in target.made_types and target.owner is A

def test_port_razer_extra_combat_is_bounded():     # CR 506/509: no infinite extra-combat loop
    g, A, B = pgame(3); g.round = 5
    pr = perm(A, 'Port Razer')
    for _ in range(10): g.combat_hit(A, B, pr, 3)
    assert A.razer_extra <= len(A.opps()) and B.idx in pr.razer_hit
