#!/usr/bin/env python3
"""Write the PDF. Geometry comes from layout.py, pixel data from images.py.

Nothing here decides where anything goes, and nothing here fetches anything, so
the same list of prepared JPEGs always produces the same file: no timestamps, no
random ids, empty metadata, `invariant=1`.

JPEG bytes are handed to ReportLab untouched, so each image keeps /DCTDecode and
is never re-encoded.
"""
import hashlib, io, os

from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas

from . import layout
from .profiles import PROFILE, mm_to_pt

RULER_MM = 100.0
RULER_TICKS_MM = 10.0
CALIBRATION_TEXT = f'Print at 100% / Actual size. Measure: box must be {PROFILE.cut_mm[0]} x {PROFILE.cut_mm[1]} mm'


def _reader(jpeg):
    return ImageReader(io.BytesIO(jpeg))


def _image(canvas, p, rect, jpeg):
    """Place one prepared JPEG to fill its slot exactly."""
    x0, y0, x1, y1 = rect
    canvas.drawImage(_reader(jpeg), x0, layout.flip(y1, p), width=x1 - x0, height=y1 - y0,
                     anchor='sw', mask=None)


def _triangles(canvas, p, tris):
    canvas.setLineWidth(p.line_width_pt)
    canvas.setStrokeColorRGB(*p.tri_rgb)
    canvas.setFillColorRGB(*p.tri_rgb)
    for tri in tris:
        path = canvas.beginPath()
        path.moveTo(tri[0][0], layout.flip(tri[0][1], p))
        for x, y in tri[1:]:
            path.lineTo(x, layout.flip(y, p))
        path.close()
        canvas.drawPath(path, fill=1, stroke=1)


def _guides(canvas, p):
    canvas.setLineWidth(p.line_width_pt)
    canvas.setStrokeColorRGB(*p.guide_rgb)
    for x0, y0, x1, y1 in layout.guide_segments(p):
        canvas.line(x0, layout.flip(y0, p), x1, layout.flip(y1, p))


def _ruler(canvas, p, x0, y0, length_mm, horizontal, label):
    """A ruler with 10 mm ticks and a length caption, for the calibration page."""
    length = mm_to_pt(length_mm)
    ticks = int(round(length_mm / RULER_TICKS_MM))
    canvas.setLineWidth(0.57)
    canvas.setStrokeColorRGB(0.0, 0.0, 0.0)
    canvas.setFillColorRGB(0.0, 0.0, 0.0)
    canvas.setFont('Helvetica', 7)
    along = (lambda t: (x0 + mm_to_pt(t), y0)) if horizontal else (lambda t: (x0, y0 + mm_to_pt(t)))
    end = along(length_mm)
    canvas.line(*along(0.0), *end)
    for i in range(ticks + 1):
        a, b = along(i * RULER_TICKS_MM), along(i * RULER_TICKS_MM + 1.2)
        canvas.line(a[0], a[1], b[0], b[1])
    canvas.drawString(along(length_mm / 2)[0] - 12, along(length_mm / 2)[1] - 9, label)


def _calibration_page(canvas, p):
    _guides(canvas, p)
    rect = layout.slot_rects(p)[0]
    b = p.bleed_pt
    box = (rect[0] + b, rect[1] + b, rect[2] - b, rect[3] - b)
    canvas.setLineWidth(0.57)
    canvas.setStrokeColorRGB(0.0, 0.0, 0.0)
    canvas.rect(box[0], layout.flip(box[3], p), box[2] - box[0], box[3] - box[1], stroke=1, fill=0)
    _ruler(canvas, p, mm_to_pt(9.0), mm_to_pt(8.0), RULER_MM, True, f'{RULER_MM:.0f} mm')
    _ruler(canvas, p, mm_to_pt(2.0), mm_to_pt(18.5), RULER_MM, False, f'{RULER_MM:.0f} mm')
    canvas.setFont('Helvetica', 11)
    canvas.drawString(mm_to_pt(9.0), layout.flip(mm_to_pt(6.0), p), CALIBRATION_TEXT)


def write_pdf(out, cards, p=PROFILE, calibration=False):
    """Write `cards` (dicts with a `jpeg` key, in order) to `out` as a print sheet.

    Returns a summary: pages, cards, and the SHA-256 of the file.
    """
    os.makedirs(os.path.dirname(os.path.abspath(out)) or '.', exist_ok=True)
    rects = layout.slot_rects(p)
    n_pages = layout.pages_for(len(cards), p)
    c = rl_canvas.Canvas(out, pagesize=p.page_pt, invariant=1, pageCompression=1)
    c.setTitle('')
    c.setAuthor('')
    c.setSubject('')
    if calibration:
        _calibration_page(c, p)
        c.showPage()
    for index in range(max(n_pages, 1)):
        slots = layout.slots_on_page(len(cards), index, p)
        for i in slots:
            rect = rects[i - index * p.per_page]
            _image(c, p, rect, cards[i]['jpeg'])
            _triangles(c, p, layout.triangles_for_rect(p, rect))
        _guides(c, p)
        c.showPage()
    c.save()
    with open(out, 'rb') as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    return {'path': os.path.abspath(out), 'pages': n_pages + (1 if calibration else 0),
            'card_pages': n_pages, 'cards': len(cards), 'sha256': digest}


def page_image(pdf_path, page=0, dpi=150, out=None):
    """Render one page to PNG for a look before printing."""
    import pymupdf
    doc = pymupdf.open(pdf_path)
    pix = doc[page].get_pixmap(dpi=dpi)
    data = pix.tobytes('png')
    if out:
        with open(out, 'wb') as f:
            f.write(data)
    doc.close()
    return data