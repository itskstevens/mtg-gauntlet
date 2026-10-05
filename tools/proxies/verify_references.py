"""Check tools/proxies layout against real mtgprint exports.

Usage: python3 tools/proxies/verify_references.py <dir-of-pdfs> [more-dirs...]

Every PDF found is read with PyMuPDF and compared page by page against what
layout.py says should be there: page size, image boxes, the 88 grey guide
segments and the corner triangles. Exits non-zero if anything is off.
"""
import glob, os, sys

import pymupdf

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tools.proxies import layout
from tools.proxies.profiles import PROFILE

TOL = 0.02


def page_lines(page):
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
    tris = []
    for d in page.get_drawings():
        if d['type'] != 'fs':
            continue
        tris.append([(i[1].x, i[1].y) for i in d['items'] if i[0] == 'l'])
    return tris


def close_seg(got, exp):
    a, b = (got[0], got[1]), (got[2], got[3])
    c, d = (exp[0], exp[1]), (exp[2], exp[3])
    return (all(abs(x - u) <= TOL and abs(y - v) <= TOL for (x, y), (u, v) in zip((a, b), (c, d)))
            or all(abs(x - u) <= TOL and abs(y - v) <= TOL for (x, y), (u, v) in zip((a, b), (d, c))))


def close_pts(got, exp):
    return len(got) == len(exp) and all(abs(x - u) <= TOL and abs(y - v) <= TOL
                                        for (x, y), (u, v) in zip(got, exp))


def check(path):
    doc = pymupdf.open(path)
    problems = []
    r = doc[0].rect
    if abs(r.width - PROFILE.page_pt[0]) > 0.01 or abs(r.height - PROFILE.page_pt[1]) > 0.01:
        problems.append(f'page size {r.width:.3f}x{r.height:.3f} != '
                        f'{PROFILE.page_pt[0]:.3f}x{PROFILE.page_pt[1]:.3f}')
    want_guides = layout.guide_segments(PROFILE)
    all_rects = layout.slot_rects(PROFILE)
    total, per_page = 0, []
    for n, page in enumerate(doc):
        boxes = [tuple(i['bbox']) for i in page.get_image_info()]
        total += len(boxes)
        per_page.append(len(boxes))
        used = all_rects[:len(boxes)]
        for got, exp in zip(boxes, used):
            if not all(abs(a - b) <= TOL for a, b in zip(got, exp)):
                problems.append(f'p{n} image {[round(v,2) for v in got]} != '
                                f'{[round(v,2) for v in exp]}')
        segs = page_lines(page)
        if len(segs) != len(want_guides):
            problems.append(f'p{n} {len(segs)} guides, expected {len(want_guides)}')
        else:
            for got, exp in zip(segs, want_guides):
                if not close_seg(got, exp):
                    problems.append(f'p{n} guide {[round(v,2) for v in got]} != '
                                    f'{[round(v,2) for v in exp]}')
        tris = page_triangles(page)
        want_tris = [t for rect in used for t in layout.triangles_for_rect(PROFILE, rect)]
        if len(tris) != len(want_tris):
            problems.append(f'p{n} {len(tris)} triangles, expected {len(want_tris)}')
        for got, exp in zip(tris, want_tris):
            if not close_pts(got, exp):
                problems.append(f'p{n} triangle '
                                f'{[(round(a,2), round(b,2)) for a, b in got]} != '
                                f'{[(round(a,2), round(b,2)) for a, b in exp]}')
    doc.close()
    name = f'{os.path.basename(path):40}'
    shape = ' '.join(str(c) for c in per_page)
    head = f'{name} cards/page: {shape[:46]}'
    return head, (f'{total:4} cards' if not problems
                  else f'*** {len(problems)} PROBLEMS ***'), problems


def main(dirs):
    paths = []
    for d in dirs:
        paths.extend(sorted(glob.glob(os.path.join(d, '*.pdf'))))
    if not paths:
        print(f'no reference PDFs in {" ".join(dirs)}')
        return 1
    bad = 0
    for path in paths:
        head, verdict, problems = check(path)
        print(f'{head}  {verdict}')
        for p in problems[:5]:
            print(f'    {p}')
        bad += bool(problems)
    print(f'\n{len(paths) - bad}/{len(paths)} reference PDFs match the layout exactly')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:] or ['/tmp/opencode/refs']))