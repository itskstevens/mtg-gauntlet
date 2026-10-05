#!/usr/bin/env python3
"""Get a card image into a state the sheet can print.

What the reference actually does, measured on seven real mtgprint exports:

  * every card is a bare scan, no bleed added - the rounded corners are still
    white at the very corner of the image, and the card's own frame runs to the
    image edge, so nothing is padded
  * the scan is stretched to fill the whole 66 x 91 mm slot, which is 4.4% wider
    and 3.2% taller than the 63.2 x 88.2 mm you cut on
  * the corner triangles square off the rounded corners that trimming exposes

So this module's job is small: reject anything that is not a card-shaped scan,
flatten alpha, re-encode to JPEG deterministically and report the resolution.
Padding would be wrong here, so there is none.

The result depends only on the source bytes and the profile, so it is cached by
that hash and the same card always renders the same way.
"""
import hashlib, io, json, os

from PIL import Image

from .profiles import PROFILE

CARD_RATIO = 63 / 88                  # 0.7159, a standard card
RATIO_TOL = 0.03                      # scans crop a little either side of this
BORDER_BAND_PX = 6
CORNER_ZONE = 0.08
MIN_DPI = 180
JPEG_KWARGS = dict(quality=95, subsampling=0, optimize=False, progressive=False)
CACHE = 'cache/proxy-prepared'


class ImageError(Exception):
    """A source image we cannot print, with the file named in the message."""


def sha(data):
    return hashlib.sha256(data).hexdigest()


def classify(im, where='image'):
    """'card' if it looks like a card scan, or raise naming the file.

    Anything outside the band is a crop we cannot print: an art crop, a token,
    a landscape card. The tolerance is wide on purpose because Scryfall's border
    crops vary a little with the scan, and a wrong aspect is caught here rather
    than as a stretched printout.
    """
    w, h = im.size
    ratio = w / h
    if abs(ratio - CARD_RATIO) <= RATIO_TOL:
        return 'card'
    raise ImageError(f'{where}: {w}x{h} is not a card-shaped image '
                     f'(want about {CARD_RATIO:.3f}, got {ratio:.3f})')


def pixels(im):
    """Row-major pixel tuples, on Pillow 12 and on Pillow 11."""
    flat = getattr(im, 'get_flattened_data', None)
    return list(flat() if flat else im.getdata())


def border_colour(im, where='image'):
    """Median colour of a band along the edges, ignoring the rounded corners.

    The corners are white on a black-bordered card and would drag the median
    towards grey, so the first and last 8% of each edge is left out. The four
    bands are different shapes, so the median is taken over their pixels pooled
    rather than over a padded canvas, which would count its own filler. On an
    image with alpha only the opaque pixels of each band get a vote, so a
    transparent strip cannot be read as black.
    """
    w, h = im.size
    band = min(BORDER_BAND_PX, max(1, min(w, h) // 8))
    cx, cy = int(w * CORNER_ZONE), int(h * CORNER_ZONE)
    pieces = (im.crop((cx, 0, w - cx, band)),
              im.crop((cx, h - band, w - cx, h)),
              im.crop((0, cy, band, h - cy)),
              im.crop((w - band, cy, w, h - cy)))
    flat = []
    for piece in pieces:
        rgba = piece if piece.mode == 'RGBA' else piece.convert('RGB')
        flat.extend(px for px in pixels(rgba) if len(px) < 4 or px[3] > 127)
    if not flat:
        raise ImageError(f'{where}: no opaque pixels to read a border colour from')
    out = []
    for channel in range(3):
        values = sorted(px[channel] for px in flat)
        out.append(values[len(values) // 2])
    return tuple(out)


def encode(im):
    """JPEG bytes with no EXIF and no ICC profile, so the hash is stable."""
    buf = io.BytesIO()
    im.convert('RGB').save(buf, 'JPEG', **JPEG_KWARGS)
    return buf.getvalue()


def dpi(im, p=PROFILE):
    """Effective resolution once the image is stretched over the whole slot."""
    return round(im.size[0] / (p.slot_mm[0] / 25.4))


def flatten(im, where='image'):
    """Composite anything with alpha onto its own border colour, never onto white."""
    if im.mode not in ('RGBA', 'LA'):
        return im.convert('RGB') if im.mode != 'RGB' else im
    rgba = im.convert('RGBA')
    try:
        background = border_colour(rgba, where)
    except ImageError:
        background = (0, 0, 0)          # nothing opaque to learn a colour from
    base = Image.new('RGBA', rgba.size, background + (255,))
    return Image.alpha_composite(base, rgba).convert('RGB')


def prepare(data, p=PROFILE, where='image', cache_root=None):
    """Source bytes to printable JPEG bytes, with what was decided on the way.

    Returns {'jpeg', 'width', 'height', 'dpi', 'border', 'shape', 'low_res'}.
    Pixels are never added or removed: the scan keeps its own size and the slot
    does the stretching, exactly as the reference does.
    """
    key = sha(data + f'|{p.name}'.encode())
    root = cache_root or CACHE
    path = os.path.join(root, f'{key}.jpg')
    meta = os.path.join(root, f'{key}.json')
    try:
        with open(path, 'rb') as f:
            jpeg = f.read()
        with open(meta) as f:
            info = json.load(f)
        info['jpeg'], info['cached'] = jpeg, True
        return info
    except FileNotFoundError:
        pass

    with Image.open(io.BytesIO(data)) as src:
        im = flatten(src, where).copy()      # copy loads it: the file closes with the block
        im.info.clear()
    shape = classify(im, where)
    out = encode(im)
    info = {'jpeg': out, 'width': im.size[0], 'height': im.size[1], 'dpi': dpi(im, p),
            'border': border_colour(im), 'shape': shape, 'low_res': dpi(im, p) < MIN_DPI,
            'cached': False, 'sha256': key}
    os.makedirs(root, exist_ok=True)
    with open(path, 'wb') as f:
        f.write(out)
    with open(meta, 'w') as f:
        json.dump({k: v for k, v in info.items() if k != 'jpeg'}, f, sort_keys=True)
    return info


def prepare_file(path, p=PROFILE):
    with open(path, 'rb') as f:
        return prepare(f.read(), p, where=os.path.basename(path))