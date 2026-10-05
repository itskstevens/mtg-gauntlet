#!/usr/bin/env python3
"""The print profile: every number that decides where ink lands on paper.

One profile, `mtgprint-letter`, reproduces Kevin's mtgprint export `deck_5.pdf`.
Distances are millimetres, top-left origin, matching the fixture; `mm_to_pt`
converts. Values here are the reference measurement and must not be "improved":
the point is that the output prints at the size the reference printed.
"""
from dataclasses import dataclass, replace

MM_TO_PT = 72 / 25.4


def mm_to_pt(mm):
    return mm * MM_TO_PT


@dataclass(frozen=True)
class Profile:
    name: str
    page_mm: tuple          # (width, height) of the sheet
    columns: int
    rows: int
    slot_mm: tuple          # the card image fills this, no gutter: slots touch
    first_slot_mm: tuple    # top-left of slot 0
    bleed_mm: float         # border colour padding around the cut size
    cut_mm: tuple           # finished card size
    tri_leg_pt: float       # corner triangle leg length
    tri_inset_pt: float     # right angle, this far in from the cut corner
    line_width_pt: float
    crosshair_mm: float     # cut guide crosshair length
    guide_far_mm: float     # how far past the page the far edge guides run
    tri_rgb: tuple          # corner triangles: fill and stroke
    guide_rgb: tuple        # cut guides: stroke

    @property
    def per_page(self):
        return self.columns * self.rows

    @property
    def page_pt(self):
        w, h = self.page_mm
        return (mm_to_pt(w), mm_to_pt(h))

    @property
    def slot_pt(self):
        w, h = self.slot_mm
        return (mm_to_pt(w), mm_to_pt(h))

    @property
    def bleed_pt(self):
        return mm_to_pt(self.bleed_mm)

    @property
    def crosshair_pt(self):
        return mm_to_pt(self.crosshair_mm)

    @property
    def guide_far_pt(self):
        return mm_to_pt(self.guide_far_mm)

    def with_name(self, name):
        return replace(self, name=name)


# The reference guide lines do not stop at the page edge on the far side: the
# mtgprint export runs them out to 500 mm, and the fixture records that. Off the
# sheet is clipped away when the page is drawn or printed, so this is invisible
# on paper but has to match for the golden tests. The near side really does stop
# at 0, and both sides start at the crosshair's inner end.
PROFILE = Profile(
    name='mtgprint-letter',
    page_mm=(279.0, 216.0),
    columns=4,
    rows=2,
    slot_mm=(66.0, 91.0),
    first_slot_mm=(9.0, 18.5),
    bleed_mm=1.4,
    cut_mm=(63.2, 88.2),
    tri_leg_pt=8.5,
    tri_inset_pt=0.57,
    line_width_pt=0.57,
    crosshair_mm=10.0,
    guide_far_mm=500.0,
    tri_rgb=(0.090, 0.082, 0.067),
    guide_rgb=(0.863, 0.863, 0.863),
)

PROFILES = {PROFILE.name: PROFILE}