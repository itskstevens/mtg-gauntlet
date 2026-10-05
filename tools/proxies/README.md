# Proxy print sheets

Turns card images into a print-ready PDF laid out exactly like the mtgprint
export that is known to print at the right size on the home printer. The same
input always gives a byte-identical PDF.

```bash
python3 -m tools.proxies --deck laezel-counters --out proxies/laezel-counters.pdf
python3 -m tools.proxies --images ~/pics --order manifest.txt --preview
python3 -m tools.proxies --deck laezel-counters --only-missing --exclude-basics
```

## Printing

- **Landscape, 100 % / actual size.** Do not use "fit to page" or "shrink".
- Print the calibration page first on a new printer or driver: the box must measure **63.2 × 88.2 mm**.
- Cut on the grey guides. Each card comes out at 63.2 × 88.2 mm with square corners.
- 8 cards per page, 13 pages for a 100-card deck.

## Where the numbers come from

Measured on 2026-10-05 against real mtgprint exports on this homelab: eight
PDFs, but only **three distinct sheets** (107, 102 and 100 cards — 309 in total,
40 pages), because mtgprint wrote the same sheet again for each job attempt and
for each upload of it. `tools/proxies/verify_references.py` re-reads them with
PyMuPDF and checks every page — page size, image boxes, all 88 guide segments and
every corner triangle — against what `layout.py` draws. All eight agree to
**0.009 pt**, which is 0.003 mm and comes from the reference rounding its
MediaBox to two decimals.

| | |
|---|---|
| Page | 279 × 216 mm |
| Card image | 66 × 91 mm, 8 per page in 4 × 2, slots touching |
| Cut box | 63.2 × 88.2 mm, so 1.4 mm is trimmed off each edge |
| Guides | light grey (0.863), 0.57 pt, 88 segments on every page including partial ones |
| Corner marks | filled dark (0.09, 0.082, 0.067), 8.5 pt legs, four per card |

### Two things worth knowing

**No bleed is added to the images.** The sources are 488 × 680 Scryfall "normal"
scans, and the reference stretches them over the whole 66 × 91 mm slot without
padding anything. You can see it in the exports: the card's own frame runs to the
image edge and the rounded corners are still light in the very corner of the
image. So the printed sheet is 4.4 % wider and 3.2 % taller than the card you
cut, and the corner triangles square off the rounded corners the trim exposes.

**The art ends up about 1.3 % wider than a real card.** mtgprint pulls every
scan to a fixed 512 × 704 canvas, which is not the aspect of a 488 × 680 scan,
so the stretch is not quite uniform. That is inherited from the reference and
reproduced deliberately, because it is the layout that is known to print
correctly here. If you would rather have true proportions, print the cards a
little smaller and ignore the guides — but then the sheets do not stack against
the reference ones.

## From a Claude chat

The `print_proxies` MCP tool (`mcp_server/server.py`) builds the same sheet on the
homelab and hands it back so you can open it from the chat: the page-1 preview comes
back inline as a PNG, and `url` / `preview_url` are HTTPS links that Caddy serves from
`/mnt/expansion/mtg-data/proxies` under an unguessable `<deck>-<sha12>` name. The
homelab path and an `scp` line are still returned, and a small PDF (under 5 MB) is also
attached as an embedded resource. See `mcp_server/README.md`.

## Options

| Flag | What it does |
|---|---|
| `--deck NAME` | A deck folder under `decks/`, printed in decklist order, commander first |
| `--images DIR` | A folder of card images instead |
| `--order FILE` | Manifest of `<qty> <filename>` lines, so `--images` follows your order |
| `--out PATH` | Output PDF, default `proxies/<name>.pdf` |
| `--exclude-basics` | Drops Plains, Island, Swamp, Mountain, Forest, Wastes |
| `--only-missing` | Skips what `collection/cards.tsv` already covers, by quantity |
| `--copies N` | Print N of each card instead of the decklist quantity |
| `--dfc both` | Also print the back of a double-faced card |
| `--preview` | Writes `<out>-p1.png` at 150 dpi to look at before printing |
| `--calibration` | Adds a leading page with the cut-size box and two 100 mm rulers |
| `--no-network` | Fail rather than fall back to Scryfall |
| `--quiet` | Summary only, no per-source counts |

## Where images come from

In deck mode, each card name is resolved in this order:

1. `decks/<deck>/card_images.json`, a name → path map on `mtg-cards.lab.kstevens.ca`
2. the local mtg-rules card cache at `/mnt/expansion/mtg-data`
3. the Scryfall API, rate-limited to 10 requests a second

Everything downloaded is cached under `cache/proxy-images` by the hash of its
URL, and prepared images under `cache/proxy-prepared` by the hash of the source
bytes, so a second run never touches the network and never depends on one.

## Tests

```bash
.venv/bin/python -m pytest tools/proxies/tests -q
```

The suite renders PDFs and reads them back with PyMuPDF: it checks every
rectangle, line and triangle against the measured fixture, checks that two runs
in separate processes give the same SHA-256, and checks that the bytes embedded
in the PDF are exactly the bytes `images.prepare()` returned.

To also check against real mtgprint exports, put them in a directory and point
`PROXY_REF_DIR` at it:

```bash
PROXY_REF_DIR=/path/to/exports .venv/bin/python -m pytest tools/proxies/tests -q
.venv/bin/python tools/proxies/verify_references.py /path/to/exports
```

## Requirements

`reportlab`, `Pillow`, `pymupdf`, `requests` — pinned in `tools/proxies/requirements.txt`.
The versions are pinned because the prepared-image cache and the PDF hash both
depend on them.