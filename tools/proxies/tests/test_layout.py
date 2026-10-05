import os, sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from tools.proxies import layout
from tools.proxies.profiles import PROFILE
from tools.proxies.tests import refgeom


@pytest.fixture(scope='module')
def reference():
    return refgeom.load()


def test_page_size(reference):
    w, h = layout.page_rect(PROFILE)[2:]
    want = reference['page_size_pt']
    assert refgeom._close_pt(w, want[0]) and refgeom._close_pt(h, want[1])


def test_slot_rects(reference):
    refgeom.close_rects(layout.slot_rects(), reference['full_page']['images'])


def test_guide_segments(reference):
    segs = layout.guide_segments()
    assert len(segs) == 88
    for name in ('full_page', 'partial_page_5_cards'):
        refgeom.close_segs(segs, reference[name]['lines'])


def test_corner_triangles(reference):
    tris = layout.corner_triangles()
    assert len(tris) == 32
    refgeom.close_tris(tris, reference['full_page']['triangles'])


def test_triangles_only_on_filled_slots(reference):
    """A partial page carries triangles for its filled slots only."""
    tris = [t for rect in layout.slot_rects()[:5] for t in layout.triangles_for_rect(PROFILE, rect)]
    assert len(tris) == 20
    refgeom.close_tris(tris, reference['partial_page_5_cards']['triangles'])


def test_slots_touch_without_a_gutter():
    rects = layout.slot_rects()
    sw = PROFILE.slot_pt[0]
    for left, right in zip(rects, rects[1:4]):
        assert refgeom._close_pt(right[0] - left[0], sw)
        assert refgeom._close_pt(left[2], right[0])


def test_cut_lines_inset_by_the_bleed():
    xs, ys = layout.cut_lines()
    b = PROFILE.bleed_pt
    rects = layout.slot_rects()
    assert len(xs) == 8 and len(ys) == 4
    assert refgeom._close_pt(xs[0], rects[0][0] + b)
    assert refgeom._close_pt(ys[0], rects[0][1] + b)
    assert refgeom._close_pt(ys[-1], rects[-1][3] - b)
    assert refgeom._close_pt(xs[-1], rects[3][2] - b)


def test_cut_size_is_slot_minus_bleed():
    sw, sh = PROFILE.slot_pt
    b = PROFILE.bleed_pt
    assert refgeom._close_pt(sw - 2 * b, PROFILE.cut_mm[0] * 72 / 25.4)
    assert refgeom._close_pt(sh - 2 * b, PROFILE.cut_mm[1] * 72 / 25.4)


def test_pages_for_and_slots_on_page():
    assert layout.pages_for(0) == 0
    assert layout.pages_for(1) == 1
    assert layout.pages_for(8) == 1
    assert layout.pages_for(9) == 2
    assert layout.pages_for(95) == 12
    assert layout.slots_on_page(9, 0) == list(range(8))
    assert layout.slots_on_page(9, 1) == [8]
    assert layout.slots_on_page(95, 11) == list(range(88, 95))
    assert layout.slots_on_page(95, 12) == []