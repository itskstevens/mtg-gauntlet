#!/usr/bin/env python3
"""Where everything goes on a sheet. Pure geometry: no I/O, no PDF library.

Coordinates are points with a top-left origin, which is how PyMuPDF and the
reference fixture report them. `render.py` is the only place that flips to
ReportLab's bottom-left origin.

  slot_rects       the image rectangles, row by row
  cut_lines        the x and y the cards are trimmed on
  guide_segments   crosshairs plus the runs out to the page edge (88 per page)
  corner_triangles four per slot, covering the rounded corners of the scan
"""
from .profiles import PROFILE, mm_to_pt


def slot_rects(p=PROFILE):
    """(x0, y0, x1, y1) of every slot on a page, filled row by row."""
    sw, sh = p.slot_mm
    x0, y0 = p.first_slot_mm
    return [(mm_to_pt(x0 + c * sw), mm_to_pt(y0 + r * sh),
             mm_to_pt(x0 + (c + 1) * sw), mm_to_pt(y0 + (r + 1) * sh))
            for r in range(p.rows) for c in range(p.columns)]


def cut_lines(p=PROFILE):
    """Sorted (xs, ys) the cards are cut on: every slot edge inset by the trim margin."""
    b, sw, sh = p.bleed_mm, p.slot_mm[0], p.slot_mm[1]
    x0, y0 = p.first_slot_mm
    xs, ys = set(), set()
    for r in range(p.rows):
        for c in range(p.columns):
            left, top = x0 + c * sw, y0 + r * sh
            xs.update((left + b, left + sw - b))
            ys.update((top + b, top + sh - b))
    return sorted(mm_to_pt(v) for v in xs), sorted(mm_to_pt(v) for v in ys)


def crosshairs(p=PROFILE):
    """A horizontal and a vertical tick at every cut-line crossing."""
    half = p.crosshair_pt / 2
    xs, ys = cut_lines(p)
    segs = []
    for x in xs:
        for y in ys:
            segs.append((x - half, y, x + half, y))
            segs.append((x, y - half, x, y + half))
    return segs


def edge_extensions(p=PROFILE):
    """The runs that carry each cut line out past the outermost crosshair.

    The near side stops at 0 and the far side runs to `guide_far_mm`, both
    starting at the crosshair's inner end, exactly as the reference does.
    """
    half = p.crosshair_pt / 2
    far = p.guide_far_pt
    xs, ys = cut_lines(p)
    segs = []
    for y in ys:
        segs.append((0.0, y, xs[0] - half, y))
        segs.append((xs[-1] - half, y, far, y))
    for x in xs:
        segs.append((x, 0.0, x, ys[0] - half))
        segs.append((x, ys[-1] - half, x, far))
    return segs


def guide_segments(p=PROFILE):
    """Every grey line on a page: 88 segments, whatever the page holds."""
    return crosshairs(p) + edge_extensions(p)


def triangles_for_rect(p, rect):
    """The four corner triangles of one slot, as [(right angle, end, end)].

    The right angle sits `tri_inset_pt` in from the cut corner and the legs run
    along the two cut edges towards the middle of the card, so the fill hides the
    white rounded corner of the scan without covering the border.
    """
    x0, y0, x1, y1 = rect
    b = p.bleed_pt
    x0, y0, x1, y1 = x0 + b, y0 + b, x1 - b, y1 - b
    d, leg = p.tri_inset_pt, p.tri_leg_pt
    v = (x0 + d, y0 + d)
    corners = [
        (v, leg, leg),
        ((x1 - d, y0 + d), -leg, leg),
        ((x0 + d, y1 - d), leg, -leg),
        ((x1 - d, y1 - d), -leg, -leg),
    ]
    return [[(vx, vy), (vx + sx, vy), (vx, vy + sy)] for (vx, vy), sx, sy in corners]


def corner_triangles(p=PROFILE):
    return [t for rect in slot_rects(p) for t in triangles_for_rect(p, rect)]


def page_rect(p=PROFILE):
    w, h = p.page_pt
    return (0.0, 0.0, w, h)


def pages_for(n_cards, p=PROFILE):
    """How many pages a run of n cards needs."""
    return (n_cards + p.per_page - 1) // p.per_page


def slots_on_page(n_cards, index=0, p=PROFILE):
    """Which slot indices are filled on page `index` of a run of n cards."""
    first = index * p.per_page
    return list(range(first, min(first + p.per_page, n_cards)))


def flip(y, p=PROFILE):
    """Top-left y in points to ReportLab's bottom-left y."""
    return p.page_pt[1] - y