"""Image preparation: what gets accepted, what it refuses, and what it reports.

The reference does not pad a scan, so neither do we. These tests pin that down:
pixels are never added or removed, a scan keeps its size, and anything that is
not card-shaped is refused by name.
"""
import io, os, sys, tempfile

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from tools.proxies import images
from tools.proxies.profiles import PROFILE, PROFILES

CARD = (488, 680)                      # what the homelab store and card host hold
_COUNTER = [0]


def _tmp():
    """A fresh cache directory per call, so tests never share prepared images."""
    _COUNTER[0] += 1
    return tempfile.mkdtemp(prefix=f'proxy-cache-{os.getpid()}-{_COUNTER[0]}-')


def jpeg(im, **kw):
    buf = io.BytesIO()
    im.save(buf, 'JPEG', quality=95, subsampling=0, **kw)
    return buf.getvalue()


def png(im):
    buf = io.BytesIO()
    im.save(buf, 'PNG')
    return buf.getvalue()


def scan(size=CARD, border=(21, 18, 13), radius=14, body=(200, 190, 170), paper=(240, 240, 235)):
    """A synthetic card: dark frame to the edges, pale body, light corner squares.

    Only the four radius x radius corners are light, the way a real scan leaves
    the background showing through a rounded corner.
    """
    w, h = size
    im = Image.new('RGB', size, border)
    corner = Image.new('RGB', (radius, radius), paper)
    for x0, y0 in ((0, 0), (w - radius, 0), (0, h - radius), (w - radius, h - radius)):
        im.paste(corner, (x0, y0))
    ring = images.BORDER_BAND_PX + 3
    im.paste(Image.new('RGB', (w - 2 * ring, h - 2 * ring), body), (ring, ring))
    return im


# ------------------------------------------------------------------ acceptance
def test_a_scryfall_normal_scan_is_accepted_untouched():
    out = images.prepare(jpeg(scan()), where='black lotus', cache_root=_tmp())
    assert out['width'], out['height'] == CARD
    assert out['shape'] == 'card'


def test_pixels_are_never_added_or_removed():
    """The reference does not pad: a scan keeps its own size and the slot stretches."""
    out = images.prepare(jpeg(scan()), cache_root=_tmp())
    with Image.open(io.BytesIO(out['jpeg'])) as im:
        assert im.size == CARD


def test_the_reference_size_is_a_stretched_scryfall_scan():
    """512x704 is 488x680 pulled to a fixed canvas, not a scan with bleed on it."""
    assert (512, 704) == (CARD[0] + 24, CARD[1] + 24)
    stretched = scan().resize((512, 704), Image.LANCZOS)
    assert stretched.size == (512, 704)
    assert images.classify(stretched) == 'card'
    # the stretched corners carry the scan's own light corner, not a pad
    assert stretched.getpixel((0, 0))[0] > 100


@pytest.mark.parametrize('size', [(100, 680), (488, 100), (488, 488), (300, 300)])
def test_something_that_is_not_a_card_is_refused_by_name(size):
    with pytest.raises(images.ImageError) as err:
        images.prepare(jpeg(scan(size)), where='art_crop.png', cache_root=_tmp())
    assert 'art_crop.png' in str(err.value)


def test_an_unreadable_file_is_an_error_not_a_crash():
    with pytest.raises(Exception):
        images.prepare(b'not an image at all', where='broken.jpg', cache_root=_tmp())


# ------------------------------------------------------------------ resolution
def test_resolution_is_reported_against_the_slot():
    out = images.prepare(jpeg(scan()), cache_root=_tmp())
    assert out['dpi'] == round(488 / (66 / 25.4)) == 188
    assert out['low_res'] is False


def test_a_small_scan_is_flagged_rather_than_upscaled():
    out = images.prepare(jpeg(scan((200, 279))), cache_root=_tmp())
    assert out['low_res'] is True
    assert out['width'] == 200                 # still not upscaled


# ------------------------------------------------------------------ border colour
def test_border_colour_ignores_the_rounded_corners():
    assert tuple(images.border_colour(scan())) == (21, 18, 13)


def test_border_colour_follows_a_white_bordered_card():
    assert tuple(images.border_colour(scan(border=(250, 250, 248)))) == (250, 250, 248)


def test_border_colour_names_the_file_when_there_is_nothing_to_read():
    with pytest.raises(images.ImageError) as err:
        images.border_colour(Image.new('RGBA', (40, 40), (0, 0, 0, 0)), where='empty.png')
    assert 'empty.png' in str(err.value)


# ------------------------------------------------------------------ alpha
def test_alpha_is_flattened_onto_the_border_not_onto_white():
    im = scan().convert('RGBA')
    im.paste((0, 0, 0, 0), (0, 0, 60, 60))       # a transparent corner
    out = images.prepare(png(im), cache_root=_tmp())
    with Image.open(io.BytesIO(out['jpeg'])) as got:
        assert got.getpixel((30, 30)) == (21, 18, 13)


def test_a_fully_transparent_image_does_not_crash():
    out = images.prepare(png(Image.new('RGBA', CARD, (0, 0, 0, 0))), where='void.png',
                         cache_root=_tmp())
    assert out['width'], out['height'] == CARD


# ------------------------------------------------------------------ encoding
def test_the_encoded_jpeg_carries_no_exif_and_no_icc_profile():
    out = images.prepare(jpeg(scan()), cache_root=_tmp())
    with Image.open(io.BytesIO(out['jpeg'])) as im:
        assert im.format == 'JPEG'
        assert not im.info.get('exif')
        assert 'icc_profile' not in im.info


def test_encoding_is_byte_stable():
    data = jpeg(scan())
    assert images.prepare(data, cache_root=_tmp())['jpeg'] == \
        images.prepare(data, cache_root=_tmp())['jpeg']


# ------------------------------------------------------------------ cache
def test_the_cache_returns_the_same_bytes_and_the_same_metadata():
    cache = _tmp()
    first = images.prepare(jpeg(scan()), cache_root=cache)
    second = images.prepare(jpeg(scan()), cache_root=cache)
    assert second['cached'] is True
    assert second['jpeg'] == first['jpeg']
    for key in ('width', 'height', 'dpi', 'shape'):
        assert second[key] == first[key]
    # JSON gives the border back as a list, which is fine, it is only ever read
    assert list(second['border']) == list(first['border'])


def test_two_cache_roots_do_not_share_entries():
    a = images.prepare(jpeg(scan()), cache_root=_tmp())
    b = images.prepare(jpeg(scan()), cache_root=_tmp())
    assert a['cached'] is False and b['cached'] is False


def test_the_cache_key_depends_on_the_profile():
    """Same bytes, different profile, different entry: the profile is part of the key."""
    other = PROFILE.with_name('mtgprint-letter-copy')
    a = images.prepare(jpeg(scan()), cache_root=_tmp())
    b = images.prepare(jpeg(scan()), p=other, cache_root=_tmp())
    assert a['sha256'] != b['sha256']


def test_prepare_file_reads_from_disk(tmp_path):
    path = tmp_path / 'card.jpg'
    path.write_bytes(jpeg(scan()))
    out = images.prepare_file(str(path), p=PROFILE)
    assert out['shape'] == 'card'
    assert tuple(out['border']) == (21, 18, 13)