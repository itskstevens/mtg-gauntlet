"""Render with synthetic images and read the result back with PyMuPDF.

This is the test that proves the PDF really carries the reference geometry:
nothing is taken on trust from layout.py, every rectangle, line and triangle is
extracted out of the written file.

PyMuPDF reports both `get_image_info()` boxes and `get_drawings()` items with a
top-left origin, which is the fixture convention, so nothing here flips y: if
these numbers match the reference, the PDF really does carry the geometry.
"""
import io, os, re, sys

import pymupdf
import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from tools.proxies import layout, render
from tools.proxies.profiles import PROFILE
from tools.proxies.tests import refgeom

W, H = 488, 680


def jpeg(rgb, size=(W, H)):
    buf = io.BytesIO()
    Image.new('RGB', size, rgb).save(buf, 'JPEG', quality=95, subsampling=0)
    return buf.getvalue()


def cards(n):
    return [{'name': f'card-{i}', 'jpeg': jpeg((30 + 12 * i, 60, 90))} for i in range(n)]


@pytest.fixture(scope='module')
def rendered(tmp_path_factory):
    out = tmp_path_factory.mktemp('render') / 'nine.pdf'
    summary = render.write_pdf(str(out), cards(13))
    doc = pymupdf.open(out)
    yield summary, doc
    doc.close()


def page_lines(page):
    """The stroked-only segments: the 88 grey cut guides."""
    segs = []
    for d in page.get_drawings():
        if d['type'] != 's':
            continue
        for item in d['items']:
            if item[0] == 'l':
                (x0, y0), (x1, y1) = item[1], item[2]
                segs.append((x0, y0, x1, y1))
    return segs


def page_triangles(page):
    """The filled-and-stroked 3-point paths: the corner triangles."""
    tris = []
    for d in page.get_drawings():
        if d['type'] != 'fs':
            continue
        pts = [item[1] for item in d['items'] if item[0] == 'l']
        assert len(pts) == 3, f'triangle path has {len(pts)} points'
        tris.append([(p.x, p.y) for p in pts])
    return tris


def content_ops(page):
    """The paint operations of a page in the order they were written.

    A `/Name Do` draws an image, `B`/`B*` fills and strokes (the corner
    triangles), `S` strokes only (the grey guides). String literals are dropped
    first so text cannot be mistaken for an operator, and operators are matched
    whole so `BT` is not read as a `B`.
    """
    raw = re.sub(r'\([^)]*\)', ' ', page.read_contents().decode('latin-1'))
    tokens = raw.split()
    ops = []
    for i, tok in enumerate(tokens):
        if tok == 'Do' and i and tokens[i - 1].startswith('/'):
            ops.append('image')
        elif tok in ('B', 'B*', 'b', 'b*'):
            ops.append('triangle')
        elif tok in ('S', 's'):
            ops.append('guide')
    return ops


def _same_seg(a, b):
    ae, be = (tuple(a[0:2]), tuple(a[2:4])), (tuple(b[0:2]), tuple(b[2:4]))
    return all(refgeom._close_point(x, y) for x, y in zip(ae, be)) or \
           all(refgeom._close_point(x, y) for x, y in zip(ae, be[::-1]))


def test_summary(rendered):
    summary, doc = rendered
    assert summary['cards'] == 13
    assert summary['card_pages'] == 2
    assert doc.page_count == 2
    assert len(summary['sha256']) == 64


def test_page_size(rendered):
    _, doc = rendered
    r = doc[0].rect
    assert abs(r.width - PROFILE.page_pt[0]) < 0.01
    assert abs(r.height - PROFILE.page_pt[1]) < 0.01


def test_image_bboxes_match_reference(rendered):
    _, doc = rendered
    got = [tuple(i['bbox']) for i in doc[0].get_image_info()]
    refgeom.close_rects(got, refgeom.load()['full_page']['images'])


def test_guides_match_reference(rendered):
    _, doc = rendered
    for page, name in ((0, 'full_page'), (1, 'partial_page_5_cards')):
        segs = page_lines(doc[page])
        assert len(segs) == 88
        refgeom.close_segs(segs, refgeom.load()[name]['lines'])


def test_triangles_match_reference(rendered):
    _, doc = rendered
    ref = refgeom.load()
    refgeom.close_tris(page_triangles(doc[0]), ref['full_page']['triangles'])
    refgeom.close_tris(page_triangles(doc[1]), ref['partial_page_5_cards']['triangles'])


def test_colours_and_line_widths(rendered):
    _, doc = rendered
    drawn = doc[0].get_drawings()
    tris = [d for d in drawn if d['type'] == 'fs']
    guides = [d for d in drawn if d['type'] == 's']
    assert len(tris) == 32 and len(guides) == 88
    for d in (tris[0], tris[-1]):
        for channel in range(3):
            assert refgeom._close_pt(d['fill'][channel], PROFILE.tri_rgb[channel], 0.002)
            assert refgeom._close_pt(d['color'][channel], PROFILE.tri_rgb[channel], 0.002)
    for channel in range(3):
        assert refgeom._close_pt(guides[0]['color'][channel], PROFILE.guide_rgb[channel], 0.002)
    assert abs(guides[0]['width'] - PROFILE.line_width_pt) < 0.001


def test_draw_order(rendered):
    """Each image, then its four triangles, then all 88 grey guides last."""
    _, doc = rendered
    for page, n_cards in ((0, 8), (1, 5)):
        ops = content_ops(doc[page])
        assert ops == (['image'] + ['triangle'] * 4) * n_cards + ['guide'] * 88


def test_images_keep_dctdecode(rendered):
    _, doc = rendered
    xrefs = {i[0] for i in doc[0].get_images(full=True)}
    assert len(xrefs) == 8
    for xref in xrefs:
        info = doc.extract_image(xref)
        assert info['ext'] == 'jpeg', f'image {xref} was re-encoded as {info["ext"]}'


def test_metadata_is_empty_and_undated(rendered):
    """invariant=1 pins the dates, so the file carries no real timestamp."""
    _, doc = rendered
    md = doc.metadata
    for key in ('title', 'author', 'subject', 'keywords'):
        assert md.get(key) == '', f'{key} is {md.get(key)!r}'
    assert md['creationDate'] == md['modDate'] == "D:20000101000000+00'00'"


def test_calibration_page_leads(tmp_path):
    out = tmp_path / 'cal.pdf'
    summary = render.write_pdf(str(out), cards(1), calibration=True)
    doc = pymupdf.open(out)
    try:
        assert summary['pages'] == 2 and summary['card_pages'] == 1
        assert doc.page_count == 2
        assert f'{PROFILE.cut_mm[0]} x {PROFILE.cut_mm[1]} mm' in doc[0].get_text()
        boxes = [d for d in doc[0].get_drawings()
                 if d['type'] == 's' and len(d['items']) == 1 and d['items'][0][0] == 're']
        assert len(boxes) == 1, 'the calibration box is missing'
        x0, y0, x1, y1 = boxes[0]['items'][0][1]
        assert abs((x1 - x0) - PROFILE.cut_mm[0] * 72 / 25.4) < 0.02
        assert abs((y1 - y0) - PROFILE.cut_mm[1] * 72 / 25.4) < 0.02
        guides = page_lines(doc[0])
        assert len(guides) == 88 + 24, '88 guides plus the two rulers'
        for want in refgeom.load()['full_page']['lines']:
            assert any(_same_seg(want, g) for g in guides), f'guide {want} is missing'
        assert len(doc[1].get_image_info()) == 1
    finally:
        doc.close()


def test_empty_deck_still_writes_a_readable_pdf(tmp_path):
    out = tmp_path / 'none.pdf'
    summary = render.write_pdf(str(out), [])
    assert summary['card_pages'] == 0
    doc = pymupdf.open(out)
    try:
        assert doc.page_count == 1 and len(doc[0].get_image_info()) == 0
    finally:
        doc.close()


def test_page_image_preview(tmp_path):
    out = tmp_path / 'p.pdf'
    render.write_pdf(str(out), cards(2))
    png = tmp_path / 'p1.png'
    render.page_image(str(out), 0, 150, str(png))
    assert Image.open(png).size[0] == round(150 * PROFILE.page_pt[0] / 72)