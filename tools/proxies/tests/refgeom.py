"""Compare what we drew against the measured reference fixture.

Every comparison is a set comparison at 0.02 pt: the reference numbers were
recorded to two decimals, and segment endpoints and triangle vertices have no
meaningful order.
"""
import json, os

TOL = 0.02
FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       '..', 'fixtures', 'mtgprint_reference_geometry.json')


def load():
    with open(FIXTURE) as f:
        return json.load(f)


def _close_pt(a, b, tol=TOL):
    return abs(a - b) <= tol


def _close_point(p, q, tol=TOL):
    return _close_pt(p[0], q[0], tol) and _close_pt(p[1], q[1], tol)


def _seg_ends(seg):
    return (tuple(seg[0:2]), tuple(seg[2:4]))


def _match(got, want, same, what):
    """Greedy one-to-one match of got against want; leftover on either side fails."""
    assert len(got) == len(want), f'{len(got)} {what}, reference has {len(want)}'
    pool = list(want)
    for g in got:
        for i, w in enumerate(pool):
            if same(g, w):
                pool.pop(i)
                break
        else:
            raise AssertionError(f'{what} {g} is not in the reference')


def close_rects(got, want):
    def same(g, w):
        return len(g) == len(w) and all(_close_pt(a, b) for a, b in zip(g, w))
    _match(got, want, same, 'rect')


def close_segs(got, want):
    def same(g, w):
        ge, we = _seg_ends(g), _seg_ends(w)
        return (_close_point(ge[0], we[0]) and _close_point(ge[1], we[1])) or \
               (_close_point(ge[0], we[1]) and _close_point(ge[1], we[0]))
    _match(got, want, same, 'segment')


def _tri_points(tri):
    return [tuple(p[0:2]) for p in tri]


def close_tris(got, want):
    def same(g, w):
        gp, wp = _tri_points(g), _tri_points(w)
        return len(gp) == len(wp) and any(
            all(_close_point(a, b) for a, b in zip(gp, perm))
            for perm in _permutations(wp))
    _match(got, want, same, 'triangle')


def _permutations(items):
    if len(items) <= 1:
        yield items
        return
    for i, rest in enumerate(items):
        for tail in _permutations(items[:i] + items[i + 1:]):
            yield [items[i]] + list(tail)