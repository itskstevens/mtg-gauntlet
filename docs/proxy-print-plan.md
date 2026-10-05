# Build plan: deterministic proxy print sheets

**For:** Claude on the homelab, working in `/home/kevin/mtg-gauntlet` (pull first).
**Goal:** a command that turns card images (a folder, or a decklist from this repo) into a print-ready PDF laid out
**exactly** like Kevin's mtgprint export `deck_5.pdf`, which is known to print at the right size on his printer.
The same input must always produce a byte-identical PDF.

The reference was measured on 2026-10-04. The numbers below reproduce every image, cut line and corner mark of the
reference to within 0.01 pt. The full measured geometry is in
`tools/proxies/fixtures/mtgprint_reference_geometry.json`; the tests in step 6 compare against it.

---

## 1. Reference spec (do not change these numbers)

All values in millimetres unless noted. 1 mm = 72 / 25.4 pt. Origin is the **top-left** corner of the page.

| Item | Value |
|---|---|
| Page | **279.0 × 216.0 mm** (790.87 × 612.28 pt), landscape, single-sided. Keep this exact size; it is US Letter for the printer's purposes. |
| Grid | 4 columns × 2 rows = 8 cards per page, filled row by row (top row left to right, then bottom row) |
| Card slot (the image fills this) | **66.0 × 91.0 mm** (187.09 × 257.95 pt). Slots touch: no gutter. |
| First slot top-left | x = **9.0**, y = **18.5** |
| Slot origins | x = 9.0, 75.0, 141.0, 207.0 · y = 18.5, 109.5 |
| Trim inset | **1.4 mm** on every side of every slot: the cut box is the slot inset by this |
| Cut size (trim) | 63.2 × 88.2 mm, i.e. slot inset by 1.4 mm |
| Cut-line coordinates | x = 10.4, 73.6, 76.4, 139.6, 142.4, 205.6, 208.4, 271.6 · y = 19.9, 108.1, 110.9, 199.1 |
| Image placement | Each image is stretched to exactly fill its 66 × 91 slot. |

### Marks

Two kinds of marks, drawn in this order on each page:

1. **Per card, straight after its image:** four **corner triangles** that hide the white rounded corners of the source scans.
   - Fill and stroke are both RGB (0.090, 0.082, 0.067), roughly #171511. Line width is 0.57 pt, using the PDF `b` operator (close, fill and stroke).
   - Each triangle is right-angled, with both legs **8.5 pt (3.0 mm)** long. Its right-angle vertex sits at the card's cut corner, moved **0.57 pt inward** in x and in y. The legs run along the two cut edges, toward the centre of the card.
   - Example: the top-left card has vertices (30.05, 56.97), (38.55, 56.97), (30.05, 65.48) pt.
   - Only filled slots get triangles. A partial last page has triangles on its filled slots only.
2. **After all images, once per page:** the **cut guides**.
   - They are stroked lines in light grey RGB (0.863, 0.863, 0.863), line width 0.57 pt.
   - **Crosshairs:** at every intersection of a cut-line x with a cut-line y (8 × 4 = 32 points), draw a horizontal and a vertical segment 10 mm long, centred on the point (±5 mm).
   - **Edge extensions:** extend every cut line from its outermost crosshair out to the page edge, on all four sides. For example, at y = 19.9 there is a segment from x = 0 to 5.4 and one from 266.6 to the right edge.
   - Draw the full set of guides on **every** page, including a partial last page, whatever the number of filled slots.
   - Expected count per page: **88 line segments**, **32 triangles** on a full page. The 5-card reference page has 20 triangles.

### Images in the reference

Re-measured on 2026-10-05 against three distinct real exports (eight files, 309 cards), which corrected an earlier reading of this plan:

- Every image in every export is **512 × 704 px** JPEG (DCTDecode, DeviceRGB, 8-bit), stretched over the whole
  66 × 91 mm slot, about 197 dpi.
- That is **not** a scan with bleed added. The sources are 488 × 680 Scryfall "normal" scans (verified byte-identical
  between the homelab store and the card host), and mtgprint simply pulls them to a fixed 512 × 704 canvas.
- Proof there is no bleed: the scan's own frame runs right to the image edge (top edge midpoint RGB ≈ (34, 33, 29))
  and the rounded corners are still light at the very corner of the image (255, 255, 255 on a black-bordered card).
  A border-coloured pad would be dark there, and a white pad would make the edge midpoints white. Neither.
- The consequence: the image is printed **4.4 % wider and 3.2 % taller** than the 63.2 × 88.2 mm you cut on, and the
  trim takes 1.4 mm off each edge. The corner triangles square off the rounded corners that trimming exposes.
- Consequence worth knowing: because a 512 × 704 canvas is not the 0.7176 aspect of a 488 × 680 scan, the printed
  art ends up about 1.3 % wider than a real card. This is inherited from the reference and reproduced deliberately.

---

## 2. What to build

Put everything in `tools/proxies/`, with no network access at render time:

```
tools/proxies/
  __init__.py
  profiles.py      # the spec above as a frozen dataclass: PROFILE "mtgprint-letter"
  layout.py        # pure functions: slot rects, cut lines, crosshair/extension segments, triangles (no I/O)
  images.py        # load, validate, normalise to JPEG bytes (deterministic)
  sources.py       # resolve a decklist to image files (local folder, card_images.json map, homelab host, Scryfall)
  render.py        # write the PDF from layout + prepared images
  cli.py           # argument parsing; `python3 -m tools.proxies ...`
  __main__.py
  fixtures/mtgprint_reference_geometry.json   # already committed
  tests/test_layout.py, test_render.py, test_images.py, test_determinism.py
```

### PDF library

Use **ReportLab** (`pip install reportlab`) with `Canvas(..., invariant=1, pageCompression=1)`. Set the page size to
`(790.87, 612.28)`. Use the `mm` unit for drawing and convert top-left coordinates to PDF bottom-left ones in one helper.

- Pass JPEG bytes straight through, so they keep `/DCTDecode` and are never re-encoded. Use `ImageReader` on a file or
  `BytesIO` of the prepared JPEG.
- Clear the metadata: empty title, author and subject; no creation date. `invariant=1` handles the dates.
- Draw the triangles with a path: `moveTo`, `lineTo` ×2, `close`, then `drawPath(fill=1, stroke=1)`.
- Use `setLineWidth(0.57)`, and set the stroke and fill colours exactly as in section 1.

If ReportLab can't reproduce something, fall back to **pikepdf** with a hand-written content stream modelled on the
reference. ReportLab should be enough.

### Inputs (CLI)

```
python3 -m tools.proxies --images DIR [--order manifest.txt]          # a folder of card images
python3 -m tools.proxies --deck laezel-counters [--only-missing]      # a deck in this repo
  common: --out proxies/<name>.pdf  --profile mtgprint-letter
          --exclude-basics  --copies N  --preview  --calibration  --dfc front|both  --no-network
```

- **Folder mode.** Accept JPEG, PNG and WebP. Order by the manifest if one is given, otherwise by filename (natural
  sort, so `2_x` comes before `10_x`). A manifest line looks like `<qty> <filename>`.
- **Deck mode.** Read `decks/<deck>/list.txt` (`<qty> <Card Name>`). Expand quantities in list order; the reference
  sheet follows decklist order with the commander first. Resolve each name to an image, in this order:
  1. `decks/<deck>/card_images.json`, a map from card name to a path on `https://mtg-cards.lab.kstevens.ca/images/`.
     The homelab can reach that host.
  2. The local mtg-rules card cache, if it is on disk.
  3. The Scryfall API as a fallback: `/cards/named?exact=`, then the `png` image (745 × 1040). Rate-limit to
     10 requests per second.
- **Image cache.** Cache every download under `cache/proxy-images/<sha256 of URL>.<ext>` (git-ignored). Renders only
  ever read from the cache.
- **`--only-missing`.** Skip cards whose quantity is already covered by `collection/cards.tsv`, matching names with the
  same `norm()` as `tools/collection.py`. This is the "print what I still need to buy" sheet.
- **Double-faced cards.** Print the front face by default. `--dfc both` prints the back face as its own card right
  after the front.
- **`--exclude-basics`.** Drop Plains, Island, Swamp, Mountain, Forest and Wastes.

### Image preparation (`images.py`)

Deliberately small, because the measurement above showed the reference adds nothing to the pixels:

1. Open with Pillow and convert to RGB. Flatten any alpha onto the image's own border colour, never onto white.
2. **Reject anything that is not a card-shaped scan.** Aspect must be within 0.03 of 63:88 (0.7159); anything else
   is an error that names the file. There is no bleed check, because nothing is ever padded.
3. **Keep the native pixels.** Never upscale and never pad: the scan keeps its own size and the slot does the
   stretching, which is what the reference does.
4. **Report the resolution** against the slot, about 488 px over 66 mm = 188 dpi, and warn below 180 dpi.
5. **Encode** JPEG with Pillow `quality=95, subsampling=0, optimize=False, progressive=False`, no EXIF, no ICC
   profile, so the bytes and the cache hash are stable.
6. Write the result to `cache/proxy-prepared/<sha256 of source bytes + profile>.jpg`, with a `.json` sidecar for
   the metadata so a cache hit returns everything a fresh run does.

## 3. Determinism rules

- No timestamps, random IDs or UUIDs in the PDF. Use `invariant=1` and empty metadata.
- Read input in a stable order (manifest, natural sort or decklist order). Never iterate over unsorted sets or dicts.
- Name cache entries by content hash. Prepared images depend only on the source bytes and the profile.
- Pin library versions in `tools/proxies/requirements.txt` (reportlab, Pillow, pymupdf, requests). Different Pillow
  JPEG encoders could change bytes, so note in the README that the hash depends on these pinned versions.

---

## 4. Tests (`pytest tools/proxies/tests`)

1. **Layout golden test** (`test_layout.py`). Build a full page and a 5-card page from `layout.py`, then compare them
   with `fixtures/mtgprint_reference_geometry.json`:
   - image rects
   - all 88 line segments (as sets, endpoint order ignored)
   - the triangle vertices
   - the page size

   The tolerance is **0.02 pt**. Fixture coordinates are top-left origin, in points, as PyMuPDF reports them.
2. **Render golden test** (`test_render.py`). Render a 9-card PDF from synthetic 488 × 680 solid-colour JPEGs. Open it
   with PyMuPDF and extract:
   - image bboxes from `page.get_image_info()`
   - lines and triangles from `page.get_drawings()`

   Assert the same geometry as test 1 on page 1, and a 1-card partial page 2 with 88 lines and 4 triangles. Also
   assert that the images keep `/DCTDecode`, and that the draw order is each image followed by its 4 triangles, with
   all grey lines last.
3. **Image test** (`test_images.py`).
   - A 488 × 680 card with a dark frame and light rounded corners comes out at exactly 488 × 680: no pixels added,
     which is what the reference does.
   - The stretched 512 × 704 canvas mtgprint uses is card-shaped and keeps the scan's own light corner.
   - A wrong aspect ratio raises an error that names the file.
   - Alpha flattens onto the border colour, not onto white; the border colour ignores the rounded corners.
   - The JPEG carries no EXIF and no ICC profile, and encodes to the same bytes every time.
4. **Determinism test.** Render the same input twice in fresh processes and require identical SHA-256. Change one
   input byte and require a different hash.
5. **Reference check.** `verify_references.py <dir>` reads real mtgprint exports with PyMuPDF and compares every
   page against `layout.py`: page size, image boxes, all 88 guides, every corner triangle. All eight exports on this
   homelab pass at a 0.02 pt tolerance (they agree to 0.009 pt, the reference rounds its MediaBox to 2 decimals).
6. **CLI smoke test.** Run `--deck laezel-counters --only-missing --exclude-basics` against a stubbed source that
   returns synthetic images. Check the page count is `ceil(cards / 8)`.

---

## 5. Build order

1. Write `profiles.py` and `layout.py`, then make `test_layout.py` pass. This is where exactness matters most.
2. Write `render.py` with synthetic images, then make `test_render.py` and the determinism test pass.
3. Write `images.py` (validation, border detection, encoding) and its tests.
4. Write `sources.py` (folder, manifest, decklist, the `card_images.json` map, the homelab host, the Scryfall
   fallback, the cache) and `--only-missing`.
5. Write `cli.py`, `--preview`, `--calibration`, and a `README.md` in `tools/proxies/` with usage and printing
   instructions.
6. Do a real run: `python3 -m tools.proxies --deck laezel-counters --out proxies/laezel-counters.pdf --preview`.
   - Compare page 1 by eye with the reference: it should be the same 8 cards in the same positions.
   - Run the PyMuPDF geometry check on the output.
7. Commit the code and tests. Don't commit `cache/` or `proxies/*.pdf`; add both to `.gitignore`. Push.

**Done when:** all tests pass, the Lae'zel PDF matches the reference geometry, two runs give the same SHA-256, and
the README explains how to print.

---

## 6. Printing (put this in the README)

- Print **landscape**, at **100% / Actual size**. Turn off "Fit to page", "Shrink oversized pages" and any borderless
  or auto-rotate scaling.
- Use US Letter paper. The 0.4 mm difference between the sheet's 279.0 × 216.0 mm and Letter's 279.4 × 215.9 mm
  doesn't matter at 100%.
- Print the calibration page first on a new printer or driver. The box must measure 63.2 × 88.2 mm.
- Cut on the grey guides. Each guide sits 1.4 mm inside the image edge, so a slightly off cut still lands on border
  colour, not white.

## 7. Out of scope for now

Card backs and duplex alignment, A4 or other paper sizes (add them later as new profiles), and any upscaling or AI
enhancement of low-resolution scans.
