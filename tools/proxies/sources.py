#!/usr/bin/env python3
"""Find the image for each card we are about to print.

Deck mode walks a decklist in list order (commander first) and resolves each name
through, in order:

  1. decks/<deck>/card_images.json, a name -> path map under mtg-cards.lab.kstevens.ca
  2. the local mtg-rules card cache, when it is on disk
  3. the Scryfall API, the last resort

Folder mode takes a directory of images, ordered by manifest if there is one and
by natural sort otherwise, so `2_x` lands before `10_x`.

Every download is cached under cache/proxy-images by the hash of its URL, so a
second run never touches the network and a render never depends on one.
"""
import hashlib, json, os, re, sqlite3, time, unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CARD_HOST = 'https://mtg-cards.lab.kstevens.ca/images/'
SCRYFALL = 'https://api.scryfall.com'
RULES_DB = os.environ.get('ORACLE_DB', '/mnt/expansion/mtg-data/cards.sqlite')
# The DB sits next to the image store it points into, so image_path is relative
# to that store: /mnt/expansion/mtg-data/cards.sqlite -> /mnt/expansion/mtg-data/images/<path>
RULES_IMAGES = os.environ.get(
    'ORACLE_IMAGES', os.path.join(os.path.dirname(RULES_DB), 'images'))
IMAGE_CACHE = 'cache/proxy-images'
SUFFIXES = ('.jpg', '.jpeg', '.png', '.webp')
RATE_LIMIT = 0.1                      # 10 requests a second
BASICS = ('Plains', 'Island', 'Swamp', 'Mountain', 'Forest', 'Wastes')
LINE = re.compile(r'^(\d+)\s+(.+?)\s*$')
NATURAL = re.compile(r'(\d+)')

_last_call = [0.0]


def norm(name):
    """Same folding collection.py uses, so names line up with cards.tsv."""
    name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', name.split(' // ')[0].strip().lower())


def natural_key(name):
    return [int(t) if t.isdigit() else t.lower() for t in NATURAL.split(name)]


class SourceError(Exception):
    """A card we could not find an image for."""


# ---------------------------------------------------------------- decklists
def deck_cards(deck):
    """[(name, qty)] in decklist order."""
    path = os.path.join(ROOT, 'decks', deck, 'list.txt')
    if not os.path.exists(path):
        raise SourceError(f'no decklist at decks/{deck}/list.txt')
    out = []
    for raw in open(path, encoding='utf-8'):
        line = raw.strip()
        if not line or line.startswith(('#', '//')):
            continue
        m = LINE.match(line)
        if not m:
            raise SourceError(f'cannot read decklist line: {line!r}')
        out.append((m.group(2).strip(), int(m.group(1))))
    return out


def expand(deck, copies=None, exclude_basics=False, dfc='front'):
    """The print order: one entry per physical card.

    `copies` overrides the quantities from the decklist, `exclude_basics` drops
    the basic lands, and `dfc='both'` puts the back face of a double-faced card
    straight after its front.
    """
    out = []
    for name, qty in deck_cards(deck):
        if exclude_basics and name in BASICS:
            continue
        qty = copies if copies else qty
        out.extend({'name': name, 'face': 'front'} for _ in range(qty))
        if dfc == 'both' and '//' in name:
            out.extend({'name': name, 'face': 'back'} for _ in range(qty))
    return out


def collection_counts(path=None):
    """name -> qty from collection/cards.tsv, or {} when there is no collection."""
    path = path or os.path.join(ROOT, 'collection', 'cards.tsv')
    counts = {}
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                parts = line.rstrip('\n').split('\t')
                if len(parts) == 2 and parts[1].strip().isdigit():
                    counts[norm(parts[0])] = int(parts[1])
    except FileNotFoundError:
        return {}
    return counts


def only_missing(entries, owned=None, copies=None):
    """Drop cards the collection already covers: the "still need to buy" sheet.

    Quantities are consumed in print order, so a deck asking for four of a card
    you own two of still prints two.
    """
    owned = dict(owned if owned is not None else collection_counts())
    out = []
    for entry in entries:
        have = owned.get(norm(entry['name']), 0)
        if have <= 0:
            out.append(entry)
        else:
            owned[norm(entry['name'])] = have - 1
    return out


# ---------------------------------------------------------------- folders
def folder_images(folder, manifest=None):
    """[(path, qty)] from a directory, ordered by manifest then natural sort."""
    if not os.path.isdir(folder):
        raise SourceError(f'no such directory: {folder}')
    files = sorted((f for f in os.listdir(folder) if f.lower().endswith(SUFFIXES)),
                   key=natural_key)
    if manifest:
        order = []
        for line in open(manifest, encoding='utf-8'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            m = LINE.match(line)
            if m:
                order.append((m.group(2).strip(), int(m.group(1))))
        have = set(files)
        missing = [f for f, _ in order if f not in have]
        if missing:
            raise SourceError(f'manifest names files that are not in {folder}: {missing[:5]}')
        return [(os.path.join(folder, f), q) for f, q in order]
    return [(os.path.join(folder, f), 1) for f in files]


# ---------------------------------------------------------------- resolvers
def _get(url, timeout=30):
    import requests
    wait = RATE_LIMIT - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.monotonic()
    r = requests.get(url, timeout=timeout, headers={'User-Agent': 'mtg-gauntlet proxy sheets'})
    r.raise_for_status()
    return r.content


def fetch(url, cache_root=None, ext='.jpg'):
    """The bytes behind a URL, from cache when we already have them."""
    root = os.path.join(ROOT, cache_root or IMAGE_CACHE)
    key = hashlib.sha256(url.encode()).hexdigest()
    for suffix in (ext, '.jpg', '.png', '.webp', '.bin'):
        path = os.path.join(root, key + suffix)
        if os.path.exists(path):
            with open(path, 'rb') as f:
                return f.read()
    data = _get(url)
    path = os.path.join(root, key + ext)
    os.makedirs(root, exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data)
    return data


def deck_map(deck):
    """name -> path on the homelab card host, from card_images.json."""
    path = os.path.join(ROOT, 'decks', deck, 'card_images.json')
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _rules_db():
    if not os.path.exists(RULES_DB):
        return None
    return sqlite3.connect(f'file:{RULES_DB}?mode=ro', uri=True)


def from_rules(name, db=None):
    """The local mtg-rules cache: image_path for a card, or None."""
    own = db is None
    db = db or _rules_db()
    if db is None:
        return None
    try:
        row = db.execute('select image_path, faces from cards where name_lower = ?',
                         (norm(name),)).fetchone()
    finally:
        if own:
            db.close()
    if not row or not row[0]:
        return None
    return {'path': os.path.join(RULES_IMAGES, row[0]), 'faces': row[1]}


def back_face_url(name, db=None):
    """The Scryfall png of a double-faced card's back face."""
    info = from_rules(name, db)
    if not info or not info.get('faces'):
        return None
    try:
        faces = json.loads(info['faces'])
    except (TypeError, ValueError):
        return None
    if len(faces) < 2:
        return None
    return faces[1].get('image_uris', {}).get('png')


def scryfall(name):
    """The Scryfall png for a card, exact match first."""
    import requests
    from urllib.parse import quote
    wait = RATE_LIMIT - (time.monotonic() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.monotonic()
    headers = {'User-Agent': 'mtg-gauntlet proxy sheets'}
    for attempt in (f'{SCRYFALL}/cards/named?exact={quote(name)}', f'{SCRYFALL}/cards/named?fuzzy={quote(name)}'):
        r = requests.get(attempt, timeout=30, headers=headers)
        if r.status_code == 200:
            return r.json()
        time.sleep(0.2)
    return None


def resolve(name, deck=None, allow_network=True, db=None):
    """Bytes for one card, plus where they came from.

    Returns {'data', 'origin', 'url'}. Raises SourceError when nothing has it.
    """
    if deck:
        path = deck_map(deck).get(name)
        if path:
            url = path if path.startswith('http') else CARD_HOST + path
            return {'data': fetch(url), 'origin': 'card_images.json', 'url': url}
    info = from_rules(name, db)
    if info and os.path.exists(info['path']):
        with open(info['path'], 'rb') as f:
            return {'data': f.read(), 'origin': 'mtg-rules', 'url': info['path']}
    if not allow_network:
        raise SourceError(f'no local image for {name!r} and no network allowed')
    card = scryfall(name)
    if not card:
        raise SourceError(f'Scryfall has no card called {name!r}')
    # Double-faced cards (transform, modal_dfc) carry no top-level image_uris;
    # the front face's image lives on card_faces[0] instead.
    uris = card.get('image_uris') or (card.get('card_faces') or [{}])[0].get('image_uris', {})
    url = uris.get('png') or uris.get('large') or uris.get('normal')
    if not url:
        raise SourceError(f'Scryfall has no image for {name!r}')
    return {'data': fetch(url, ext='.png'), 'origin': 'scryfall', 'url': url}
