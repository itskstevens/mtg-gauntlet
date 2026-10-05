"""Builds the published Lae'zel report page (both brackets) with hover card images."""
import sys, os, json, re, base64, io, html, glob
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from engine import cards as CD
from PIL import Image
IMGDIR = sys.argv[1]; OUT = sys.argv[2]
IMAP = json.load(open(os.path.join(ROOT, 'decks/laezel-counters/card_images.json')))
def rd(d): return os.path.join(ROOT, sorted(glob.glob(os.path.join(ROOT, 'results', d, '*lgs*')))[-1])
S4 = json.load(open(rd('laezel-counters') + '/summary.json')); S3 = json.load(open(rd('laezel-counters-b3') + '/summary.json'))
I4 = json.load(open(rd('laezel-counters') + '/insights.json')); I3 = json.load(open(rd('laezel-counters-b3') + '/insights.json'))
def lst(d): return [l.strip().split(' ', 1) for l in open(os.path.join(ROOT, 'decks', d, 'list.txt')) if l.strip()]
L4, L3 = lst('laezel-counters'), lst('laezel-counters-b3')
esc = html.escape

# ---- images
names = sorted(set(n for _, n in L4 + L3))
idx = {n: i for i, n in enumerate(names)}
uris = []
for n in names:
    im = Image.open(os.path.join(IMGDIR, os.path.basename(IMAP[n]))).convert('RGB')
    w = 260; im = im.resize((w, round(im.height * w / im.width)), Image.LANCZOS)
    b = io.BytesIO(); im.save(b, 'JPEG', quality=76, optimize=True)
    uris.append('data:image/jpeg;base64,' + base64.b64encode(b.getvalue()).decode())
def cn(n, label=None):
    return f'<span class="cn" tabindex="0" data-c="{idx[n]}">{esc(label or n)}</span>'
def img(n, cls='cimg'):
    return f'<img class="{cls}" src="{uris[idx[n]]}" alt="{esc(n)}" width="260" height="363">'

# ---- card text
def forge(n):
    t = open(os.path.join(CD.FORGE_DIR, CD.slug(n) + '.txt')).read().split('ALTERNATE')[0]
    g = lambda k: (re.search(rf'^{k}:(.*)', t, re.M) or [None, ''])[1].strip()
    mc = g('ManaCost'); mc = '' if mc in ('no cost', '') else ''.join('{%s}' % x for x in mc.split())
    return dict(cost=mc, type=g('Types'), oracle=g('Oracle').replace('\\n', '\n'), pt=g('PT'), loy=g('Loyalty'))
def oracle_html(n):
    return ''.join(f'<p>{esc(l)}</p>' for l in forge(n)['oracle'].split('\n') if l.strip())

# ---- results
def G(S): return {g['name']: g for g in S['groups']}
g4, g3 = G(S4), G(S3); ALL = 'All tables (random LGS pods)'
a4, a3 = g4[ALL], g3[ALL]
imp4 = {r[0]: r[1:] for r in a4['impact']}; imp3 = {r[0]: r[1:] for r in a3['impact']}

def kpi(v, lab, cls=''):
    return f'<div class="kpi {cls}"><b class="num">{v}</b><span>{lab}</span></div>'

# ---- decklist
ORDER = ['Commanders', 'Creatures', 'Planeswalkers', 'Instants', 'Sorceries', 'Artifacts', 'Enchantments', 'Lands']
def groups(L):
    out = {k: [] for k in ORDER}
    for i, (q, n) in enumerate(L):
        c = CD.get(n)
        k = 'Commanders' if n in ("Lae'zel, Vlaakith's Champion", 'Guild Artisan') else 'Lands' if c.is_land else 'Creatures' if c.is_creature \
            else 'Planeswalkers' if c.is_planeswalker else 'Instants' if c.is_instant else 'Sorceries' if c.is_sorcery \
            else 'Artifacts' if c.is_artifact else 'Enchantments'
        out[k].append((int(q), n))
    return [(k, sorted(v, key=lambda x: x[1])) for k, v in out.items() if v]
GC = {'Smothering Tithe', 'Enlightened Tutor', "Teferi's Protection", "Jeska's Will", 'Ancient Tomb', 'The One Ring'}
SW = {'Enlightened Tutor': 'Idyllic Tutor', "Jeska's Will": 'Inspiring Overseer', 'Ancient Tomb': 'Plains', 'Heliod, Sun-Crowned': "Ajani's Pridemate"}
def decklist(L, tag):
    cols = []
    for k, v in groups(L):
        lis = ''.join(f'<li><span class="q num">{q}</span> {cn(n)}{" <i class=gc>GC</i>" if n in GC else ""}</li>' for q, n in v)
        cols.append(f'<div class="dg"><h4>{k} <span class="num">{sum(q for q, _ in v)}</span></h4><ul>{lis}</ul></div>')
    mox = '\n'.join(f'{q} {n}' for q, n in L)
    return f'<div class="dl" id="dl-{tag}"{" hidden" if tag == "b3" else ""}>{"".join(cols)}<textarea id="mox-{tag}" class="mox" readonly aria-label="Moxfield import text">{esc(mox)}</textarea></div>'

# ---- sections
core = [("Lae'zel, Vlaakith's Champion", 'Adds one to every counter you put on a creature or planeswalker, including the ones they enter with.'),
        ('Guild Artisan', 'Background: two Treasures each time Lae’zel attacks the player with the most life.'),
        ("Cathars' Crusade", 'Every creature that enters grows the whole team, and Lae’zel makes each trigger +2.'),
        ('Felidar Retreat', 'Each land drop is a 2/2 Cat or a counter on everything.'),
        ('Luminarch Aspirant', 'Two counters every combat with Lae’zel out.'),
        ('Ajani Steadfast', 'The −2 puts counters on every creature and loyalty on every other walker.'),
        ('Basri Ket', '+1 is +2 counters with Lae’zel, and walkers start one loyalty higher.'),
        ('Mikaeus, the Lunarch', 'Taps to spread a counter to every other creature each turn.')]
wins = ["Elspeth, Sun's Champion", 'Ajani Unrelenting', 'Basri Ket', 'Felidar Retreat', 'Heliod, Sun-Crowned']
winnote = {"Elspeth, Sun's Champion": 'Three Soldiers a turn into Cathars’ Crusade, then the +2/+2 flying emblem. With Lae’zel she enters on 5 loyalty, one turn closer to −7.',
           'Ajani Unrelenting': 'Every activation makes a Cadet. The +1 gives the team +1/+0 and haste, so a turn-6 Ajani usually means a lethal swing on turn 7.',
           'Basri Ket': 'With Lae’zel each +1 is +2, so the −6 emblem (a Soldier and a counter on everything every combat) comes online in two turns.',
           'Felidar Retreat': 'The engine that keeps working after a wipe: every land is a new body or a counter on the whole board.',
           'Heliod, Sun-Crowned': 'Bracket 4 only. Heliod gives Walking Ballista lifelink; each ping gains life, Heliod adds a counter back, and it loops for infinite damage.'}
def perf(n):
    out = []
    for lab, imp in (('B4', imp4), ('B3', imp3)):
        if n in imp: g, w, nw = imp[n]; out.append(f'{lab}: cast in {g:,} games, won {w}% (vs {nw}% without)')
    return ' · '.join(out) or 'Not in the top-impact list for this run.'
core_html = ''.join(f'<figure class="cf">{img(n)}<figcaption><b>{cn(n)}</b>{esc(t)}</figcaption></figure>' for n, t in core)
win_html = ''
for n in wins:
    f = forge(n); extra = f' · Loyalty {f["loy"]}' if f['loy'] else (f' · {f["pt"]}' if f['pt'] else '')
    win_html += (f'<article class="wc">{img(n, "wc-img")}<div class="wc-b"><div class="wc-h"><b>{cn(n)}</b><span class="wc-c">{esc(f["cost"])}</span></div>'
                 f'<div class="wc-t">{esc(f["type"])}{esc(extra)}</div><div class="wc-o">{oracle_html(n)}</div>'
                 f'<p class="wc-why">{esc(winnote[n])}</p><div class="wc-n num">{esc(perf(n))}</div></div></article>')

rulings = [
 ('Lae’zel and cards that enter with counters', '122.6', 'Some spells and abilities refer to counters being put on an object. This refers to putting counters on that object while it\'s on the battlefield and also to an object that\'s given counters as it enters the battlefield.',
  'Walking Ballista, Stonecoil Serpent, Mikaeus and Graft-style creatures all enter with one extra counter.'),
 ('Planeswalkers enter with an extra loyalty', '306.5b', 'A planeswalker has the intrinsic ability "This permanent enters with a number of loyalty counters on it equal to its printed loyalty number." This ability creates a replacement effect (see rule 614.1c).',
  'Because entering loyalty counters are "put" on the walker (122.6), Lae’zel applies: Elspeth, Sun’s Champion starts on 5, Gideon on 5, Ajani Resolute on 3.'),
 ('A Walking Ballista for X=0 still dies', '704.5f', 'If a creature has toughness 0 or less, it\'s put into its owner\'s graveyard. Regeneration can\'t replace this event.',
  'With X=0 no counters are being put on Ballista, so Lae’zel has nothing to add to. Cast it for at least X=1 (it then enters with 2).'),
 ('Cathars’ Crusade with several creatures entering at once', '603.2c', 'An ability triggers only once each time its trigger event occurs. However, it can trigger repeatedly if one event contains multiple occurrences.',
  'Three Soldiers from Elspeth is three Crusade triggers, each putting two counters (with Lae’zel) on every creature.'),
 ('Guild Artisan as your second commander', '702.124k', '"Choose a Background" means "You may designate two cards as your commander rather than one if one of them is this card and the other is a legendary Background enchantment card."',
  'Guild Artisan starts in the command zone and only grants its ability to commander creatures, so it does nothing without Lae’zel on the battlefield.')]
rule_html = ''.join(f'<details class="rule"><summary>{esc(t)} <span class="cite">CR {r}</span></summary><blockquote>{esc(q)}</blockquote><p>{esc(w)}</p></details>' for t, r, q, w in rulings)

swap_rows = ''.join(f'<tr><td>{cn(a)}{" <i class=gc>GC</i>" if a in GC else ""}</td><td>{cn(b)}</td><td class="l">{esc(w)}</td></tr>' for a, b, w in [
    ('Enlightened Tutor', 'Idyllic Tutor', 'Still finds Cathars’ Crusade, Felidar Retreat or Anointed Procession'),
    ("Jeska's Will", 'Inspiring Overseer', 'Card draw on a small flyer that also triggers Welcoming Vampire and Mentor of the Meek'),
    ('Ancient Tomb', 'Plains', 'Mana base only'),
    ('Heliod, Sun-Crowned', "Ajani's Pridemate", 'Removes the Heliod + Walking Ballista infinite')])

# comparison table
cats = [g['name'] for g in S4['groups']]
def cls(d): return 'up' if d >= 3 else 'down' if d <= -3 else ''
crow = ''
for c in cats:
    x, y = g4[c], g3[c]; d = round(x['game_win'] - y['game_win'], 1)
    lab = 'All tables' if c == ALL else c
    crow += (f'<tr{" class=tot" if c == ALL else ""}><td>{esc(lab)}</td><td class="num">{x["game_win"]}%</td><td class="num">{x["series_win"]}%</td>'
             f'<td class="num">{y["game_win"]}%</td><td class="num">{y["series_win"]}%</td><td class="num {cls(d)}">{"+" if d > 0 else ""}{d}</td>'
             f'<td class="num">{x["first_out"]}%</td></tr>')
# bars (B4 game win)
mx = 60
bars = ''
for c in cats[1:]:
    x, y = g4[c]['game_win'], g3[c]['game_win']
    bars += (f'<div class="row"><div class="lab">{esc(c)}</div><div class="track"><div class="bar b4" style="width:{x/mx*100:.1f}%"></div>'
             f'<div class="bar b3" style="width:{y/mx*100:.1f}%"></div><div class="base" style="left:{25/mx*100:.1f}%"></div></div>'
             f'<div class="num v">{x}<small>{y}</small></div></div>')
def opps(a):
    op = sorted([o for o in a['opps'] if o['games'] >= 15], key=lambda o: -o['killed_me'])[:6]
    return ''.join(f'<tr><td>{esc(o["cmd"])}</td><td>{esc(o["arch"])}</td><td class="num">{o["games"]}</td><td class="num">{o["win_share"]}%</td><td class="num">{o["killed_me"]}%</td></tr>' for o in op)
def hits(lst_, unit):
    return ''.join(f'<li>{cn(n) if n in idx else esc(n)} <span class="num muted">{v:,}{unit}</span></li>' for n, v in lst_)
impact_rows = ''
for n in sorted(set(imp4) | set(imp3), key=lambda n: -(imp4.get(n, imp3.get(n))[1])):
    r4 = imp4.get(n); r3 = imp3.get(n)
    f = lambda r: f'<td class="num">{r[1]}%</td><td class="num muted">{r[2]}%</td>' if r else '<td>–</td><td>–</td>'
    impact_rows += f'<tr><td>{cn(n)}</td>{f(r4)}{f(r3)}</tr>'
ins4 = ''.join(f'<li>{esc(x)}</li>' for x in I4['all-tables-random-lgs-pods'])
ins3 = ''.join(f'<li>{esc(x)}</li>' for x in I3['all-tables-random-lgs-pods'])
preds = [('Board wipes and control would be the problem', 'Missed', 'Control was an average row (41.7% B4). Teferi’s Protection, Flawless Maneuver and Unbreakable Formation blunt wipes, and Felidar Retreat rebuilds.'),
         ('Weak to faster go-wide and aggro boards', 'Held', 'Tokens / go-wide (32.1%), Typal (34.9%) and Aggro (37.8%) are the bottom rows. You’re out first about 41% of the time in those pods.'),
         ('Bracket 4 edge comes from the Game Changers and the combo', 'Held', 'B4 is 2.0 points ahead overall (noise ±1.3). 54 of its kills came from Heliod + Ballista.')]
pred_html = ''.join(f'<tr><td class="l">{esc(a)}</td><td><span class="pill {"w" if b == "Held" else "l"}">{b}</span></td><td class="l">{esc(c)}</td></tr>' for a, b, c in preds)

tpl = open(os.path.join(os.path.dirname(__file__), 'page.html')).read()
rep = dict(CORE=core_html, WINS=win_html, RULES=rule_html, SWAPS=swap_rows, DECK4=decklist(L4, 'b4'), DECK3=decklist(L3, 'b3'),
           KPIS=kpi(f'{a4["game_win"]}%', 'Games won, bracket 4', 'good') + kpi(f'{a4["series_win"]}%', 'Series won, bracket 4') +
                kpi(f'{a3["game_win"]}%', 'Games won, bracket 3', 'good') + kpi(f'{a3["series_win"]}%', 'Series won, bracket 3') +
                kpi(f'{a4["first_out"]}%', 'Knocked out first (B4)', 'warn') + kpi(f'{a4["avg_rounds"]}', 'Average rounds per game'),
           CROWS=crow, BARS=bars, OPP4=opps(a4), OPP3=opps(a3), INS4=ins4, INS3=ins3, IMPACT=impact_rows, PREDS=pred_html,
           REMOVED=hits(a4['removed'], ''), COUNTERED=hits(a4['countered'], ''), WIPED=hits(a4['wiped'], ''),
           GAMES4=f'{a4["games"]:,}', GAMES3=f'{a3["games"]:,}', LZ=cn("Lae'zel, Vlaakith's Champion", "Lae’zel"),
           IMGS=json.dumps(uris))
for k, v in rep.items(): tpl = tpl.replace('{{' + k + '}}', v)
# any other card names written in the template as [[Name]]
tpl = re.sub(r'\[\[([^\]<>]+?)\]\]', lambda m: cn(m.group(1)) if m.group(1) in idx else m.group(0), tpl)
open(OUT, 'w').write(tpl); print('wrote', OUT, round(len(tpl) / 1e6, 2), 'MB')
