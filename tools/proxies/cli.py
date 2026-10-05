#!/usr/bin/env python3
"""Build a proxy print sheet.

  python3 -m tools.proxies --deck laezel-counters --out proxies/laezel.pdf
  python3 -m tools.proxies --images ~/pics --order manifest.txt
  python3 -m tools.proxies --deck laezel-counters --only-missing --exclude-basics

Print landscape at 100% / actual size. See tools/proxies/README.md.
"""
import argparse, os, sys

from . import images, layout, render, sources
from .profiles import PROFILES, PROFILE


def parse_args(argv=None):
    ap = argparse.ArgumentParser(prog='python3 -m tools.proxies', description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_argument_group('what to print')
    src.add_argument('--deck', help='deck folder under decks/')
    src.add_argument('--images', help='a folder of card images')
    src.add_argument('--order', help='manifest of "<qty> <filename>" lines, for --images')
    ap.add_argument('--copies', type=int, help='print this many of each card, ignoring the decklist')
    out = ap.add_argument_group('how to print it')
    out.add_argument('--out', help='output PDF (default proxies/<name>.pdf)')
    out.add_argument('--profile', default=PROFILE.name, choices=sorted(PROFILES))
    out.add_argument('--exclude-basics', action='store_true',
                     help='drop Plains, Island, Swamp, Mountain, Forest and Wastes')
    out.add_argument('--only-missing', action='store_true',
                     help='skip cards collection/cards.tsv already covers')
    out.add_argument('--dfc', default='front', choices=('front', 'both'),
                     help='print the back of a double-faced card too')
    out.add_argument('--preview', action='store_true', help=f'also write <out>-p1.png at 150 dpi')
    out.add_argument('--calibration', action='store_true',
                     help='add a leading page with a cut-size box and two 100 mm rulers')
    ap.add_argument('--no-network', action='store_true',
                    help='fail rather than fall back to Scryfall')
    ap.add_argument('--quiet', action='store_true')
    return ap.parse_args(argv)


def gather(args, p):
    """The ordered print list, as [{'name', 'data', 'origin'}]."""
    if args.deck:
        entries = sources.expand(args.deck, copies=args.copies,
                                 exclude_basics=args.exclude_basics, dfc=args.dfc)
        if args.only_missing:
            entries = sources.only_missing(entries)
        db = sources._rules_db()
        out = []
        for entry in entries:
            if entry['face'] == 'back':
                url = sources.back_face_url(entry['name'], db)
                if not url:
                    continue
                out.append({'name': f"{entry['name']} (back)", 'data': sources.fetch(url, ext='.png'),
                            'origin': 'scryfall-back'})
            else:
                got = sources.resolve(entry['name'], args.deck, allow_network=not args.no_network, db=db)
                out.append({'name': entry['name'], **got})
        if db is not None:
            db.close()
        return out

    pairs = sources.folder_images(args.images, args.order)
    return [{'name': os.path.basename(path), 'data': open(path, 'rb').read(), 'origin': 'folder'}
            for path, qty in pairs for _ in range(qty)]


def main(argv=None):
    args = parse_args(argv)
    if bool(args.deck) == bool(args.images):
        raise SystemExit('give exactly one of --deck or --images')
    p = PROFILES[args.profile]
    name = args.deck or os.path.basename(os.path.normpath(args.images))
    out = args.out or os.path.join('proxies', f'{name}.pdf')

    entries = gather(args, p)
    if not entries:
        raise SystemExit('nothing to print: every card was filtered out')

    cards, origins, low_res, names = [], {}, [], set()
    for entry in entries:
        info = images.prepare(entry['data'], p, where=entry['name'])
        if info['low_res']:
            low_res.append((entry['name'], info['dpi']))
        origins[entry['origin']] = origins.get(entry['origin'], 0) + 1
        names.add(info['sha256'])
        cards.append({'name': entry['name'], 'jpeg': info['jpeg']})

    summary = render.write_pdf(out, cards, p, calibration=args.calibration)
    if args.preview:
        png = f'{os.path.splitext(out)[0]}-p1.png'
        render.page_image(summary['path'], 0, 150, png)
        summary['preview'] = os.path.abspath(png)

    summary['sources'] = origins
    summary['distinct_images'] = len(names)
    summary['low_resolution'] = [{'card': n, 'dpi': d} for n, d in low_res]
    if not args.quiet:
        _report(summary, p)
    return summary


def _report(s, p):
    print(f"{s['cards']} cards from {s['distinct_images']} images on {s['card_pages']} page(s)"
          f"{' + calibration page' if s['pages'] > s['card_pages'] else ''} -> {s['path']}")
    for origin in sorted(s['sources']):
        print(f'  {s["sources"][origin]:>4} cards from {origin}')
    for row in s['low_resolution']:
        print(f"  warning: {row['card']} is only {row['dpi']} dpi in the slot")
    if s.get('preview'):
        print(f'  preview: {s["preview"]}')
    print(f"  sha256: {s['sha256']}")
    print(f'  print landscape, 100% / actual size, cut on the grey guides '
          f'({p.cut_mm[0]} x {p.cut_mm[1]} mm cards)')


if __name__ == '__main__':
    main()
