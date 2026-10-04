"""Parse Forge card scripts and tag each card with simulation roles."""
import re, os, unicodedata, functools

FORGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'cards')
NUM = {'a': 1, 'an': 1, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6,
       'seven': 7, 'eight': 8, 'ten': 10, 'x': 3, 'that many': 2}

def slug(n):
    n = unicodedata.normalize('NFKD', n).encode('ascii', 'ignore').decode().lower().replace(' // ', ' ')
    n = re.sub(r"[^a-z0-9 \-]", '', n).replace('-', '_')
    n = re.sub(r'\s+', '_', n.strip())
    return re.sub(r'_+', '_', n)

def num(s):
    s = s.strip().lower()
    if s.isdigit(): return int(s)
    return NUM.get(s, 1)

class Card:
    def __init__(self, name, text=None):
        self.name = name
        if text is None:
            text = open(os.path.join(FORGE_DIR, slug(name) + '.txt')).read()
        raw, _, alt = text.partition('\nALTERNATE')
        f = {}
        kws = []
        for line in raw.splitlines():
            if ':' not in line: continue
            k, v = line.split(':', 1)
            if k == 'K': kws.append(v.strip())
            elif k not in f: f[k] = v.strip()
        self.mana_cost = f.get('ManaCost', 'no cost')
        self.cmc, self.pips = self._cmc(self.mana_cost)
        self.types = f.get('Types', '').split()
        pt = f.get('PT', '')
        try: self.power, self.toughness = [int(x) if x.lstrip('-').isdigit() else 1 for x in pt.split('/')]
        except Exception: self.power, self.toughness = (0, 0)
        self.kw = set()
        for k in kws:
            base = k.split(':')[0].strip()
            self.kw.add(base.lower())
            if base.lower() == 'ward' and 'poison' in k.lower(): self.kw.add('ward_poison')
            if base.lower() == 'protection': self.kw.add('protection:' + k.lower())
        short = name.split(',')[0].split(' // ')[0]
        o = f.get('Oracle', '').replace('\\n', '\n')
        o = o.replace(name, '~').replace(short, '~').lower()
        self.oracle = o
        t = set(x.lower() for x in self.types)
        self.is_land = 'land' in t
        self.is_creature = 'creature' in t
        self.is_artifact = 'artifact' in t
        self.is_enchantment = 'enchantment' in t
        self.is_instant = 'instant' in t
        self.is_sorcery = 'sorcery' in t
        self.is_planeswalker = 'planeswalker' in t
        self.is_aura = 'aura' in t
        self.is_legendary = 'legendary' in t
        self.subtypes = t
        self.colors = set(c for c in 'WUBRG' if c in self.mana_cost)
        self.flash = 'flash' in self.kw or self.is_instant
        tag(self)
        prep_tags(self, raw, alt)

    @staticmethod
    def _cmc(mc):
        if not mc or mc == 'no cost': return 0, 0
        total = 0; pips = 0
        for tok in mc.split():
            if tok.isdigit(): total += int(tok)
            elif tok in ('X', 'Y'): pass
            else:
                total += 1
                if tok[0] in 'WUBRG': pips += 1
        return total, pips

    def __repr__(self): return self.name

@functools.lru_cache(maxsize=None)
def get(name): return Card(name)

# ---------------------------------------------------------------- curated data
DRAW_ENGINES = {'Rhystic Study': 1, 'Mystic Remora': 1, 'Phyrexian Arena': 1, 'Sylvan Library': 1,
    'Black Market Connections': 1, 'Esper Sentinel': .5, "Bolas's Citadel": 2, "Alhammarret's Archive": 1,
    "Teferi's Ageless Insight": 1, 'Consecrated Sphinx': 3, 'Archmage Emeritus': 1, 'Beast Whisperer': 1,
    'Guardian Project': 1, 'Skullclamp': 1, 'Trade Routes': .5, 'Sram, Senior Edificer': 1,
    'Mesa Enchantress': 1, 'Kor Spiritdancer': 1, 'Courser of Kruphix': .5, 'Toski, Bearer of Secrets': .5,
    'Niv-Mizzet, Visionary': 2, 'Faerie Mastermind': .5, 'Well of Lost Dreams': 1, 'Thrasios, Triton Hero': 1,
    'Midnight Reaper': .5, 'Grim Haruspex': .5, 'Harmonic Prodigy': .5, 'Tandem Lookout': .5, 'Curiosity': .5,
    'Ophidian Eye': .5, 'Druid Class': .5, 'Murmuring Mystic': 0, 'Telepathy': 0, 'Archmage of Runes': 1,
    'Sensei\'s Divining Top': .5, 'Birgi, God of Storytelling': 1, 'Tatyova, Benthic Druid': 0,
    'Smothering Tithe': 0, 'Elas il-Kor, Sadistic Pilgrim': 0, 'Enduring Vitality': 0, 'Liliana, Dreadhorde General': 1,
    'Tezzeret the Seeker': 0, 'Nissa, Who Shakes the World': 0, 'Oko, Thief of Crowns': 0, 'Elspeth, Storm Slayer': 0,
    'Tyvar Kell': .5, 'Jace, Wielder of Mysteries': 1, 'Narset, Parter of Veils': .5, 'Ajani, Strength of the Pride': 0,
    'Dovin, Hand of Control': 0, 'Teferi, Time Raveler': 1, 'Wrenn and Seven': 1}
MANA_ENGINES = {'Smothering Tithe': 1, 'Pitiless Plunderer': 0, 'Storm-Kiln Artist': 0, 'Kinnan, Bonder Prodigy': 0,
    'Mana Vault': 1, 'Basalt Monolith': 1, 'Gaea\'s Cradle': 0, 'Nykthos, Shrine to Nyx': 0, 'Sapphire Medallion': 1,
    'Ruby Medallion': 1, 'Pearl Medallion': 1, 'Thought Vessel': 1, 'Mind Stone': 1, 'Treasure Vault': 0,
    'Springleaf Drum': 1, 'Mox Amber': 1, 'Chrome Mox': 1, 'Cryptolith Rite': 1, 'Growing Rites of Itlimoc': 2,
    'Priest of Titania': 3, 'Elvish Archdruid': 3, 'Circle of Dreams Druid': 3, 'Wirewood Channeler': 3,
    'Marwyn, the Nurturer': 3, 'Bloom Tender': 2, 'Nyxbloom Ancient': 4, 'Incubation Druid': 1, 'Badgermole Cub': 1,
    'Ilysian Caryatid': 1, 'Delighted Halfling': 1, 'Elvish Spirit Guide': 0, 'Simian Spirit Guide': 0,
    'Lotus Petal': 0, 'Chromatic Sphere': 0, 'Chromatic Star': 0, "Conjurer's Bauble": 0, 'Halo Fountain': 0,
    'Ornithopter of Paradise': 1, 'Moonsilver Key': 0, 'Mirage Mirror': 0, 'Staff of Compleation': 1,
    'Shimmerwilds Growth': 1, 'Nightshade Dryad': 1, 'Noxious Newt': 1, 'Great Forest Druid': 1, 'Dryad Arbor': 0,
    'Deathrite Shaman': 1, 'Elves of Deep Shadow': 1, 'Avacyn\'s Pilgrim': 1, 'Paradise Druid': 1,
    'Birds of Paradise': 1, 'Llanowar Elves': 1, 'Elvish Mystic': 1, 'Fyndhorn Elves': 1, 'Starfield Mystic': 0,
    'The Wind Crystal': 0, 'Cosmos Elixir': 0, 'Commander\'s Sphere': 1, 'Decanter of Endless Water': 1,
    "Banner of Kinship": 0, "Coat of Arms": 0}
TUTORS = {'Demonic Tutor', 'Vampiric Tutor', 'Worldly Tutor', 'Enlightened Tutor', 'Mystical Tutor', 'Idyllic Tutor',
    'Diabolic Intent', 'Merchant Scroll', 'Chord of Calling', "Green Sun's Zenith", 'Finale of Devastation',
    'Eldritch Evolution', 'Fabricate', 'Trophy Mage', 'Imperial Recruiter', 'Gamble', 'Elvish Harbinger',
    'Fiend Artisan', 'Fauna Shaman', 'Survival of the Fittest', 'Birthing Pod', 'Natural Order', 'Pact of the Serpent',
    'Open the Armory', 'Idyllic Tutor', 'Light-Paws, Emperor\'s Voice', 'Flamekin Harbinger', 'Solve the Equation',
    'Worthy Cost', 'Varragoth, Bloodsky Sire', 'Tezzeret the Seeker', 'Allosaurus Shepherd'}
FREE_COUNTERS = {'Force of Will', 'Force of Negation', 'Fierce Guardianship', 'Pact of Negation'}
STAX = {
    'Thalia, Guardian of Thraben': {'tax_noncreature': 1}, 'Thalia, Heretic Cathar': {'opp_enter_tapped': 1},
    'Grand Arbiter Augustin IV': {'tax_all': 1}, 'Sphere of Resistance': {'tax_all': 1},
    'Archon of Emeria': {'one_spell': 1}, 'Drannith Magistrate': {'no_cmd_cast': 1},
    'Hushbringer': {'no_triggers': 1}, 'Rest in Peace': {'no_dies': 1},
    'Linvala, Keeper of Silence': {'no_creature_abilities': 1}, 'Cursed Totem': {'no_creature_abilities': 1},
    'Collector Ouphe': {'no_artifact_abilities': 1}, 'Winter Orb': {'winter_orb': 1},
    'Aura of Silence': {'tax_artench': 2}, 'Ghostly Prison': {'attack_tax': 2}, 'Propaganda': {'attack_tax': 2},
    'Windborn Muse': {'attack_tax': 2}, 'Sphere of Safety': {'attack_tax': 3},
    'Authority of the Consuls': {'opp_enter_tapped': 1}, 'Blind Obedience': {'opp_enter_tapped': 1},
    'Elesh Norn, Grand Cenobite': {'opp_minus': 2}, 'Void Winnower': {'no_even': 1},
    'Grand Abolisher': {'abolisher': 1}, 'Deafening Silence': {'one_noncreature': 1},
    'Narset, Parter of Veils': {'draw_limit': 1}, 'Spelltithe Enforcer': {'tax_all': 1},
    'Kambal, Consul of Allocation': {'spell_ping': 2}, 'Teferi, Time Raveler': {'sorcery_speed': 1},
    'Dovin, Hand of Control': {'tax_noncreature': 1}, 'Jin-Gitaxias, Progress Tyrant': {'jin': 1},
    'Esper Sentinel': {}, 'Aven Mindcensor': {}, 'Hokori, Dust Drinker': {},
}
ALT_WINS = {'Felidar Sovereign': 'felidar', 'Test of Endurance': 'test', 'Approach of the Second Sun': 'approach',
            'Aetherflux Reservoir': 'aetherflux'}
TOKEN_DOUBLERS = {'Anointed Procession', 'Parallel Lives', 'Doubling Season', 'Mondrak, Glory Dominus',
                  'Elspeth, Storm Slayer'}
# Combos: all pieces on battlefield (or castable from hand this turn) => that player wins.
COMBOS = [
    ('Kinnan, Bonder Prodigy', 'Basalt Monolith'),
    ('Bloom Tender', 'Freed from the Real'), ('Bloom Tender', "Pemmin's Aura"),
    ('Hullbreaker Horror', 'Sol Ring'), ('Hullbreaker Horror', 'Mana Vault'),
    ('Niv-Mizzet, Parun', 'Curiosity'), ('Niv-Mizzet, Parun', 'Ophidian Eye'), ('Niv-Mizzet, Parun', 'Tandem Lookout'),
    ('Niv-Mizzet, the Firemind', 'Curiosity'), ('Niv-Mizzet, the Firemind', 'Ophidian Eye'),
    ('Niv-Mizzet, the Firemind', 'Tandem Lookout'),
    ('Sanguine Bond', 'Exquisite Blood'), ('Vito, Thorn of the Dusk Rose', 'Exquisite Blood'),
    ('Yawgmoth, Thran Physician', 'Mikaeus, the Unhallowed', 'Zulaport Cutthroat'),
    ('Yawgmoth, Thran Physician', 'Mikaeus, the Unhallowed', 'Blood Artist'),
    ('Yawgmoth, Thran Physician', 'Mikaeus, the Unhallowed', 'Syr Konrad, the Grim'),
    ('Isochron Scepter', 'Dramatic Reversal'),
    ('Exquisite Blood', 'Marauding Blight-Priest'), ('Exquisite Blood', 'Bloodthirsty Conqueror'),
    ('Sanguine Bond', 'Bloodthirsty Conqueror'),
]
FOGS = {'Aetherize'}
# Reanimation and self-mill. Reanimate / Animate Dead / Necromancy take from any graveyard, Persist only nonlegendary.
REANIMATE_SPELLS = {'Reanimate', 'Bind to Life', 'Restore Relic', 'Animate Dead', 'Necromancy', 'Persist',
                    'Unburial Rites', 'Dread Return'}
REANIMATE_ANY_GY = {'Reanimate', 'Animate Dead', 'Necromancy'}
SELF_MILL = {'Entomb': 'entomb', 'Buried Alive': 'buried', 'Omit Variables': 'mill3', 'Faithless Looting': 'loot'}
PROTECT = {'Heroic Intervention', "Teferi's Protection", 'Flawless Maneuver', 'Clever Concealment'}

# --------------------------------------------------------------------- tagging
def first_add(o):
    m = re.search(r'add ([^.\n]*)', o)
    if not m: return 0
    s = m.group(1)
    if 'for each' in s: return 2
    n = s.count('{')
    if n: return n
    for w, v in (('three mana', 3), ('two mana', 2), ('one mana', 1)):
        if w in s: return v
    return 1

def tag(c):
    o = c.oracle; n = c.name
    c.mana_land = 0; c.rock = 0; c.dork = False; c.ritual = 0; c.ramp_lands = 0; c.extra_lands = 0
    c.draw_now = 0; c.draw_engine = DRAW_ENGINES.get(n, 0); c.tutor = n in TUTORS
    c.counter = None; c.removal = None; c.wipe = None; c.edict = 0
    c.tokens_now = None; c.tokens_rec = None; c.token_double = n in TOKEN_DOUBLERS
    c.anthem = 0; c.overrun = None; c.death_trig = None; c.spell_trig = None; c.etb_trig = None
    c.life_trig = None; c.landfall = None; c.upkeep = None; c.attack_trig = None
    c.alt_win = ALT_WINS.get(n); c.stax = STAX.get(n, {}); c.drain_now = 0; c.life_now = 0
    c.fog = n in FOGS; c.protect = n in PROTECT; c.aura_bonus = None; c.mill_win = False
    c.free_outlet = bool(re.search(r'sacrifice (a|another) (creature|artifact or creature)[^:]*:', o)) and not c.is_land
    c.evasive = 'flying' in c.kw or 'unblockable' in o or "can't be blocked" in o
    # --- mana
    if c.is_land:
        c.mana_land = 2 if re.search(r'add \{c\}\{c\}', o) else 1
    elif n in MANA_ENGINES:
        c.rock = MANA_ENGINES[n]; c.dork = c.is_creature and c.rock > 0
    elif re.search(r'\{t\}(?:, [^:]*)?: add', o) and not (c.is_instant or c.is_sorcery):
        oneshot = re.search(r'\{t\}, sacrifice ~: add', o)
        c.rock = 0 if oneshot else min(first_add(o), 3)
        c.dork = c.is_creature and c.rock > 0
    if (c.is_instant or c.is_sorcery) and re.search(r'\badd \{', o):
        c.ritual = max(0, first_add(o) - c.cmc + (1 if 'for each' in o else 0))
    if n == 'Mana Geyser': c.ritual = 5
    if n == "Jeska's Will": c.ritual = 3; c.draw_now = 2
    # --- land ramp
    if 'search your library for' in o and 'land' in o and 'onto the battlefield' in o and not c.is_land:
        c.ramp_lands = 2 if re.search(r'(up to two|two basic land|two land|four basic)', o) else 1
    if n in ('Explore', 'Growth Spiral'): c.ramp_lands = 1
    if n == 'Harrow': c.ramp_lands = 1
    if n == 'Planar Engineering': c.ramp_lands = 2
    if n == 'Splendid Reclamation': c.ramp_lands = 2
    m = re.search(r'play (an|two|three) additional lands?', o)
    if m and not (c.is_instant or c.is_sorcery):
        c.extra_lands = {'an': 1, 'two': 2, 'three': 3}[m.group(1)]
    if n == 'Burgeoning': c.extra_lands = 1
    # --- draw now
    if c.is_instant or c.is_sorcery or re.search(r'when ~ enters', o):
        m = re.search(r'draws? (a|one|two|three|four|x|seven) cards?', o)
        if m:
            c.draw_now = num(m.group(1))
            if re.search(r'then (put|discard) (two|that many)', o) or 'then discard two' in o: c.draw_now = max(0, c.draw_now - 2)
            if 'discards their hand' in o or 'discard your hand' in o: c.draw_now = 7
        if 'draw cards equal' in o or 'draws cards equal' in o: c.draw_now = 3
        if 'discards their hand' in o and 'draw' in o: c.draw_now = 7; c.wheel = True
    if n in ('Brainstorm',): c.draw_now = 1
    if n in ('Windfall', 'Wheel of Fortune', 'Wheel of Misfortune'): c.draw_now = 7
    c.wheel = n in ('Windfall', 'Wheel of Fortune', 'Wheel of Misfortune', 'Winds of Rath') and n != 'Winds of Rath'
    if c.is_creature and re.search(r'when ~ enters[^.]*return target (creature )?card', o): c.draw_now = max(c.draw_now, 1)
    if c.is_planeswalker and not c.draw_engine and 'draw' in o: c.draw_engine = .5
    # --- counters
    m = re.search(r'counter target ([a-z, ]*?)spell', o)
    if m and c.is_instant:
        s = m.group(1)
        scope = 'any'
        if 'noncreature' in s or 'enchantment, instant, or sorcery' in s or 'instant or sorcery' in s: scope = 'noncreature'
        elif 'creature' in s: scope = 'creature'
        soft = 0
        mm = re.search(r'unless its controller pays \{(\d)\}', o)
        if mm: soft = int(mm.group(1))
        if 'unless its controller pays {x}' in o or 'pays {3}' in o: soft = soft or 3
        mvmin = 4 if 'mana value 4 or greater' in o else 0
        c.counter = dict(scope=scope, cost=0 if n in FREE_COUNTERS else c.cmc, soft=soft, mvmin=mvmin)
    if n in ('Sink into Stupor',): c.counter = dict(scope='any', cost=3, soft=0, mvmin=0)
    # --- targeted removal
    rem = None
    m = re.search(r'(destroy|exile) target (nonland permanent|permanent)', o)
    if m: rem = dict(kind='any', how=m.group(1))
    if not rem:
        m = re.search(r'(destroy|exile) target ((?:artifact|creature|planeswalker|enchantment|nontoken|tapped|attacking|nonblack|nonartifact)(?:,? (?:or|and)? ?(?:artifact|creature|planeswalker|enchantment))*)', o)
        if m:
            s = m.group(2)
            kinds = set(k for k in ('artifact', 'creature', 'enchantment', 'planeswalker') if k in s)
            if 'creature' in kinds and len(kinds - {'planeswalker'}) > 1: kind = 'any'
            elif 'creature' in kinds: kind = 'creature'
            else: kind = 'noncreature'
            rem = dict(kind=kind, how=m.group(1))
    if not rem and ('shuffles it into' in o or 'owner shuffles' in o) and 'target permanent' in o: rem = dict(kind='any', how='exile')
    if not rem:
        m = re.search(r'deals? (\d+|x) damage to (any target|target creature|target creature or planeswalker)', o)
        if m: rem = dict(kind='creature', how='damage', amt=num(m.group(1)) if m.group(1) != 'x' else 4,
                         face=m.group(2) == 'any target')
    if not rem:
        m = re.search(r'target creature (?:an opponent controls )?gets -(\d+|x)/-(\d+|x)', o)
        if m: rem = dict(kind='creature', how='minus', amt=num(m.group(1)) if m.group(1) != 'x' else 3)
    if not rem and re.search(r"return target (creature|nonland permanent)[^.]*to (its|their) owner'?s'? hand", o) and not c.is_aura:
        rem = dict(kind='creature' if 'creature' in o.split('return target')[1][:20] else 'any', how='bounce')
    if not rem and ('target creature' in o and ('loses all abilities' in o or 'becomes a' in o) and (c.is_aura or c.is_instant or c.is_sorcery)):
        rem = dict(kind='creature', how='neutralize')
    if n in ('Pongify', 'Rapid Hybridization', 'Reality Shift', 'Swords to Plowshares', 'Path to Exile', 'Infernal Grasp',
             'Go for the Throat', 'Ravenous Chupacabra', 'Shriekmaw', 'Ossification', 'Darksteel Mutation',
             'Reprobation', 'Pick Your Poison', "Sheoldred's Edict", 'Devouring Tendrils', 'Wolf Strike',
             'Punishing Punch', 'Broken Wings', 'Witherbloom Charm', 'Damn'):
        rem = rem or dict(kind='creature', how='destroy')
        if n in ('Broken Wings', 'Witherbloom Charm'): rem = dict(kind='any', how='destroy')
    if n == 'Feed the Swarm': rem = dict(kind='creature_ench', how='destroy')
    if n in ('Chains of Custody', 'Anguished Unmaking', 'Void Rend', 'Despark', "Assassin's Trophy", 'Beast Within',
             'Chaos Warp', 'Casualties of War', 'Abrupt Decay', 'Putrefy', 'Golgari Charm', 'Artifact Mutation',
             'Aura Mutation', 'Reclamation Sage', 'Haywire Mite', 'Cankerbloom', 'Abrade', 'Flame of Anor',
             'Prismari Command', 'Vandalblast'):
        rem = rem or dict(kind='any', how='destroy')
        if n in ('Artifact Mutation', 'Aura Mutation', 'Reclamation Sage', 'Haywire Mite', 'Cankerbloom', 'Vandalblast'):
            rem = dict(kind='noncreature', how='destroy')
    if rem:
        rem.setdefault('amt', 99)
        mv = re.search(r'mana value (\d) or (greater|less)', o)
        if mv: rem['mv'] = (int(mv.group(1)), mv.group(2))
        rem['instant'] = c.flash
        rem['etb'] = c.is_creature
        if c.is_aura and rem['how'] in ('destroy',) and 'enchant' in o and 'exile' not in o: rem['how'] = 'neutralize'
        c.removal = rem
    # --- edicts
    m = re.search(r'(each opponent|target player|target opponent|each player|each other player) sacrifices (a|an|one|two|three)? ?(nontoken )?creature', o)
    if m and not c.free_outlet and 'whenever' not in o.split(m.group(0))[0][-60:]:
        c.edict = num(m.group(2) or 'a'); c.edict_self = m.group(1) == 'each player'
    if n == 'Liliana, Dreadhorde General': c.edict = 2; c.edict_self = True
    # --- wipes
    w = None
    if re.search(r'(destroy|exile) all (creatures|other creatures|nonland permanents|artifacts, creatures)', o) or 'destroy all creatures' in o:
        w = dict(scope={'creature'})
        if 'nonland permanents' in o: w['scope'] = {'creature', 'artifact', 'enchantment'}
    if re.search(r'exile all artifacts', o): w = w or dict(scope=set()); w['scope'] |= {'artifact'}
    if re.search(r'exile all enchantments', o): w = w or dict(scope=set()); w['scope'] |= {'enchantment'}
    if re.search(r'exile all creatures', o): w = w or dict(scope=set()); w['scope'] |= {'creature'}
    m = re.search(r'all creatures get -(\d+|x)/-(\d+|x)', o)
    if m and not w: w = dict(scope={'creature'}, minus=num(m.group(1)) if m.group(1) != 'x' else 4)
    m = re.search(r'deals? (\d+) damage to each creature', o)
    if m and not w: w = dict(scope={'creature'}, minus=int(m.group(1)))
    if n == 'Cyclonic Rift': w = dict(scope={'creature', 'artifact', 'enchantment'}, asym=True, bounce=True, cost=7)
    if n == 'Massacre Wurm': w = dict(scope={'creature'}, asym=True, minus=2, drain_each_death=2)
    if n == 'Vandalblast': w = dict(scope={'artifact'}, asym=True, cost=5)
    if n == 'Winds of Rath': w = dict(scope={'creature'}, spare_enchanted=True)
    if n == 'Kindred Dominance': w = dict(scope={'creature'}, spare_type='elf')
    if n == 'Martial Coup': w = dict(scope={'creature'}, cost=7); c.tokens_now = (5, 1, 1, set())
    if n == 'Culling Ritual': w = dict(scope={'creature', 'artifact', 'enchantment'}, mvmax=2)
    if n == 'Living Death': w = dict(scope={'creature'}, living_death=True)
    if n == 'Damn': w = dict(scope={'creature'}, cost=4)
    if n == 'The Meathook Massacre': w = dict(scope={'creature'}, minus=2, cost=5)
    if n == 'Time Wipe': w = dict(scope={'creature'})
    if n == 'Golgari Charm': w = None; c.removal = dict(kind='enchantment', how='destroy', amt=99, instant=True, etb=False); c.charm_wipe = True
    if n == 'Toxic Deluge': w = dict(scope={'creature'}, minus=5)
    if n == 'Withering Curse': w = dict(scope={'creature'}, minus=2)
    if n == 'Elesh Norn, Grand Cenobite': w = None
    if w:
        w.setdefault('cost', c.cmc); w.setdefault('asym', False); w.setdefault('minus', None)
        c.wipe = w
        if n not in ('Martial Coup',): c.removal = c.removal if n in ('Damn', 'Cyclonic Rift') else None
    # --- tokens
    def parse_tok(s):
        m = re.search(r'create (a|an|one|two|three|four|five|six|x|that many|\d+) (?:tapped )?(?:[a-z\- ,]+? )?(\d+|x)/(\d+|x)([^.]*)', s)
        if not m: return None
        cnt = num(m.group(1)); pw = num(m.group(2)) if m.group(2) != 'x' else 2; tg = num(m.group(3)) if m.group(3) != 'x' else 2
        rest = m.group(4); kw = set()
        for k in ('flying', 'deathtouch', 'lifelink', 'haste', 'vigilance', 'trample'):
            if k in rest[:80] or k in s[max(0, m.start() - 10):m.start() + 120]: kw.add(k)
        if 'for each' in s[m.start():m.end() + 60] or 'equal to the number' in s[m.start():m.end() + 60]: cnt = 'each'
        return (cnt, pw, tg, kw)
    for sent in re.split(r'(?<=[.\n])', o):
        if 'create' not in sent or 'token' not in sent: continue
        tk = parse_tok(sent)
        if not tk: continue
        if 'at the beginning of' in sent: c.tokens_rec = c.tokens_rec or ('upkeep',) + tk
        elif 'whenever you cast' in sent:
            c.spell_trig = (c.spell_trig or {}); c.spell_trig['token'] = tk; c.spell_trig['who'] = 'self'
            c.spell_trig['noncreature'] = 'creature spell' not in sent
        elif re.search(r'whenever (a|one or more) lands?', sent) or 'landfall' in sent: c.landfall = (c.landfall or {}); c.landfall['token'] = tk
        elif re.search(r'whenever [^.]*attacks', sent) or 'whenever you attack' in sent: c.attack_trig = (c.attack_trig or {}); c.attack_trig['token'] = tk
        elif 'dies' in sent and 'whenever' in sent: c.death_trig = c.death_trig or {}; c.death_trig['token'] = tk
        elif re.search(r'\}[^.:]*: create', sent) and not (c.is_instant or c.is_sorcery):
            c.tokens_rec = c.tokens_rec or ('activated',) + tk
        elif 'whenever' in sent:
            pass
        else:
            c.tokens_now = c.tokens_now or tk
    # --- anthem / overrun
    m = re.search(r'(?:other )?(?:[a-z]+ )?creatures you control get \+(\d+|x)/\+(\d+|x)(?! until end of turn)([^.]*)', o)
    if m and 'until end of turn' not in m.group(3)[:30] and not c.is_instant and not c.is_sorcery and 'enchanted' not in o[:m.start()][-30:]:
        c.anthem = num(m.group(1)) if m.group(1) != 'x' else 1
    m = re.search(r'other ([a-z]+) creatures (?:you control )?get \+(\d)/\+(\d)', o)
    if m and not c.anthem: c.anthem = int(m.group(2))
    if n == 'Coat of Arms': c.anthem = 3
    if n in ('Elvish Champion',): c.anthem = 1
    m = re.search(r'creatures you control (?:gain trample and )?get \+(\d+|x)/\+(\d+|x)[^.]*until end of turn', o)
    if m:
        pump = 'count' if ('number of creatures' in o or 'x is the number' in o) else (num(m.group(1)) if m.group(1) != 'x' else 3)
        c.overrun = dict(pump=pump, trample='trample' in o)
    if n == 'Craterhoof Behemoth': c.overrun = dict(pump='count', trample=True)
    if n == 'Finale of Devastation': c.overrun = dict(pump=10, trample=False, min_mana=12)
    if n == 'Beastmaster Ascension': c.overrun = dict(pump=5, trample=False, static=True)
    if n == 'Ezuri, Renegade Leader': c.overrun = dict(pump=3, trample=True, activated=5)
    if n == 'Triumph of the Hordes': c.overrun = dict(pump=1, trample=True, infect=True)
    if n == 'Overwhelming Stampede': c.overrun = dict(pump='maxpow', trample=True)
    # --- death / spell / etb / life / landfall / upkeep triggers
    def effect(s):
        e = {}
        m = re.search(r'each opponent loses (\d+|x) life', s) or re.search(r'deals? (\d+) damage to each opponent', s)
        if m: e['drain_each'] = num(m.group(1))
        m = re.search(r'(target player|target opponent) loses (\d+) life', s)
        if m: e['drain_one'] = int(m.group(2))
        if 'loses that much life' in s or 'loses life equal to the' in s: e['drain_equal'] = True
        m = re.search(r'you gain (\d+) life', s)
        if m: e['life'] = int(m.group(1))
        if re.search(r'\bdraws? (a|one) card', s): e['draw'] = 1
        if re.search(r'(each opponent|each other player) sacrifices', s): e['edict'] = 1
        if 'create a treasure' in s or 'add {' in s: e['mana'] = 1
        return e
    for sent in re.split(r'(?<=[.\n])', o):
        if 'whenever' not in sent: continue
        if 'dies' in sent or 'put into a graveyard from the battlefield' in sent:
            e = effect(sent)
            if e:
                scope = 'own' if re.search(r'(you control|your) (dies|creature)', sent) or 'creature you control' in sent else 'any'
                if "you don't control" in sent or 'an opponent controls' in sent or 'opponents control' in sent: scope = 'opp'
                if 'whenever ~ dies' in sent or 'when ~ dies' in sent: scope = 'self'
                if 'nontoken' in sent: e['nontoken'] = True
                d = c.death_trig or {}; d.update(e); d['scope'] = scope; c.death_trig = d
        elif re.search(r'whenever (you cast|a player casts|an opponent casts) (an instant or sorcery|a noncreature|an instant|a spell)', sent):
            e = effect(sent)
            if e:
                d = c.spell_trig or {}; d.update(e); d['who'] = 'opp' if 'an opponent casts' in sent else ('any' if 'a player casts' in sent else 'self')
                d['noncreature'] = 'creature spell' not in sent; c.spell_trig = d
        elif 'whenever you cast or copy an instant or sorcery' in sent:
            e = effect(sent)
            if 'create a treasure' in sent: e['mana'] = 1
            if e:
                d = c.spell_trig or {}; d.update(e); d['who'] = 'self'; d['noncreature'] = True; d['magecraft'] = True; c.spell_trig = d
        elif re.search(r'whenever (a|another|one or more) (nontoken )?(creatures?|[a-z]+) (you control )?enters?', sent):
            e = effect(sent)
            if e: d = c.etb_trig or {}; d.update(e); d['own'] = 'you control' in sent or 'your control' in sent; c.etb_trig = d
        elif 'whenever you gain life' in sent:
            e = effect(sent)
            if e: d = c.life_trig or {}; d.update(e); c.life_trig = d
        elif re.search(r'whenever (a|one or more) lands?', sent):
            e = effect(sent)
            if e: d = c.landfall or {}; d.update(e); c.landfall = d
        elif re.search(r'whenever [^.]*attacks|whenever you attack', sent):
            e = effect(sent)
            if e: d = c.attack_trig or {}; d.update(e); c.attack_trig = d
    for sent in re.split(r'(?<=[.\n])', o):
        if 'at the beginning of your upkeep' in sent or 'at the beginning of your end step' in sent:
            e = effect(sent)
            if 'you lose' in sent:
                mm = re.search(r'you lose (\d+) life', sent)
                if mm: e['lose'] = int(mm.group(1))
            if e: d = c.upkeep or {}; d.update(e); c.upkeep = d
    # one-shot drains / life on cast or ETB
    if c.is_instant or c.is_sorcery or re.search(r'when ~ enters', o):
        m = re.search(r'each opponent loses (\d+|x) life', o)
        if m and not c.death_trig: c.drain_now = num(m.group(1)) if m.group(1) != 'x' else 4
        m = re.search(r'deals? (\d+|x) damage to each opponent', o)
        if m: c.drain_now = num(m.group(1)) if m.group(1) != 'x' else 4
        m = re.search(r'you gain (\d+) life', o)
        if m: c.life_now = int(m.group(1))
    if n == 'Gray Merchant of Asphodel': c.drain_now = 5
    if n == 'The Meathook Massacre': c.death_trig = dict(drain_each=1, scope='own')   # second trigger (gain 1 on opponents' deaths) dropped
    if n == 'Toxrill, the Corrosive': c.death_trig = None
    if n == 'Balmor, Battlemage Captain': c.anthem = 0; c.overrun = None   # handled in engine (pump on instant/sorcery)
    if n == 'Harnesser of Storms': c.draw_engine = .7
    # --- go-wide / spell-copy archetype (Aziza) ---
    c.x_tokens = 'X' in c.mana_cost.split() and bool(c.tokens_now) and (c.is_instant or c.is_sorcery)
    c.treasure_now = 0; c.mob = False; c.draw_once = None; c.special = None
    if n in ('Big Score', 'Unexpected Windfall', 'Pirate\'s Pillage'): c.treasure_now = 2
    if n == 'Seize the Spoils': c.treasure_now = 1
    if n == "Brass's Bounty": c.special = 'brass'
    if n == 'Battle Hymn': c.ritual = 0; c.special = 'hymn'
    if n == "Jeska's Will": c.ritual = 0; c.special = 'jeska'; c.draw_now = 2
    if n in ('Mob Justice', 'Massive Raid'): c.mob = True; c.removal = None
    if n == 'Boros Charm': c.special = 'charm4'
    if n == 'Empty the Warrens': c.special = 'warrens'
    if n in ('Will of the Mardu', 'Call the Coppercoats'): c.tokens_now = ('oppmax', 1, 1, set()); c.x_tokens = False
    if n == "Moogles' Valor": c.tokens_now = ('own', 1, 2, {'lifelink'})
    if n == 'Tempt with Bunnies': c.tokens_now = (2, 1, 1, set())
    if n == 'Glimpse the Impossible': c.tokens_rec = None; c.draw_now = 2
    if n == 'Reckless Impulse': c.draw_now = 2
    if n in ('Valakut Awakening', 'Flashback', 'Pinnacle Monk'): c.draw_now = 1
    if n == 'Purphoros, God of the Forge': c.overrun = None
    if n == 'Weftstalker Ardent': c.etb_trig = dict(drain_each=1, own=True)
    if n == 'Caretaker\'s Talent': c.etb_trig = None; c.draw_once = 'token'
    if n in ('Welcoming Vampire', 'Enduring Innocence'): c.draw_once = 'small'
    if n == "Tocasia's Welcome": c.draw_once = 'mv3'
    if n == 'Belladonna Took': c.etb_trig = None; c.draw_once = 'token'
    if n == 'Intangible Virtue': c.anthem = 1
    if n == 'Heroic Reinforcements': c.overrun = dict(pump=1, trample=False, haste=True)
    if n == 'Trumpet Blast': c.overrun = dict(pump=2, trample=False)
    if n == "Akroma's Will": c.overrun = dict(pump=0, trample=False, kw={'flying', 'double strike', 'vigilance', 'lifelink', 'indestructible'})
    if n == 'Moonshaker Cavalry': c.overrun = dict(pump='count', trample=False, kw={'flying'})
    if n == 'Arabella, Abandoned Doll': c.special = 'arabella'
    if n == 'Twinning Staff': c.special = 'twinning'
    if n == 'Clever Concealment': c.protect = True   # handled in engine (slime counters, Slugs)
    if n == 'Exsanguinate': c.drain_now = 'X'
    if n == 'Debt to the Deathless': c.drain_now = 'X2'
    if n == 'Torment of Hailfire': c.drain_now = 'TORMENT'
    if n == 'Grapeshot': c.drain_now = 'STORM'
    if n == 'Approach of the Second Sun': c.life_now = 7
    if n in REANIMATE_SPELLS: c.special = 'reanimate'; c.removal = None
    if n in SELF_MILL: c.special = SELF_MILL[n]
    if n == 'Regrowth': c.special = 'regrowth'
    if n == 'Craft with Pride': c.treasure_now = 1
    if n == 'Arc of Fortune': c.wheel = True; c.draw_now = 7
    if n == 'Seething Song': c.ritual = 2
    if n == 'Song of Creation': c.spell_trig = None   # draws two per spell; handled in engine
    # auras: enchanted creature bonuses
    if c.is_aura:
        m = re.search(r'enchanted creature gets \+(\d+)/\+(\d+)', o)
        b = dict(p=int(m.group(1)) if m else 0, t=int(m.group(2)) if m else 0, kw=set())
        for k in ('flying', 'first strike', 'double strike', 'lifelink', 'vigilance', 'trample', 'hexproof', 'indestructible', 'shroud'):
            if re.search(r'enchanted creature[^.]*' + k, o) or re.search(r'(has|gains?) [^.]*' + k, o): b['kw'].add(k)
        if re.search(r'protection from (black|green|each color|creatures|everything)', o): b['kw'].add('pro_bg')
        if 'protection from' in o and ('black' in o or 'green' in o): b['kw'].add('pro_bg')
        if 'for each aura' in o: b['p'] += 2; b['t'] += 2
        if b['p'] or b['kw']: c.aura_bonus = b

# ---------------------------------------------------------------- prepare (Secrets of Strixhaven)
def prep_target(raw, alt):
    """Name of the prepare spell, or None. Forge stores it as `CopyFaceFrom:<card>` or as an inline face."""
    if 'AlternateMode:Prepare' not in raw: return None
    m = re.search(r'CopyFaceFrom:(.+)', alt)
    if m: return m.group(1).strip()
    m = re.search(r'Name:(.+)', alt)
    return m.group(1).strip() if m else None

def prep_tags(c, raw, alt):
    """A creature with a prepare spell gets c.prep_card (the spell, tagged like any instant or sorcery) and the ways
    it becomes prepared on its own. Codie, Ravenous Codex, flicker effects and the engine handle the rest."""
    c.prep_card = None; c.prep_enter = False; c.prep_upkeep = None; c.prep_tap2 = False; c.prep_third = False
    tgt = prep_target(raw, alt)
    if not tgt: return
    if re.search(r'CopyFaceFrom:', alt): c.prep_card = get(tgt)
    else: c.prep_card = Card(tgt, text=alt.strip())
    o = c.oracle
    c.prep_enter = 'enters prepared' in o or bool(re.search(r'when (this creature|~) enters[^.]*?(and [^.]*)?this creature becomes prepared', o)) and 'then if' not in o
    if 'at the beginning of your upkeep' in o and 'becomes prepared' in o:
        c.prep_upkeep = 'always' if "isn't prepared, it becomes prepared" in o else 'gy3'
    c.prep_tap2 = 'tap two untapped creatures you control: this creature becomes prepared' in o
    c.prep_third = 'third spell each turn' in o

def summarize(c):
    keys = ['mana_land', 'rock', 'ritual', 'ramp_lands', 'extra_lands', 'draw_now', 'draw_engine', 'tutor', 'counter',
            'removal', 'wipe', 'edict', 'tokens_now', 'tokens_rec', 'anthem', 'overrun', 'death_trig', 'spell_trig',
            'etb_trig', 'life_trig', 'landfall', 'upkeep', 'attack_trig', 'alt_win', 'stax', 'drain_now', 'free_outlet',
            'aura_bonus', 'token_double']
    return {k: getattr(c, k) for k in keys if getattr(c, k)}
