#!/usr/bin/env python3
"""Mark which owned cards are Pauper candidates, from Forge's set files (rarity per printing) + Pauper banned list.

  python3 tools/pauper_legal.py            # writes collection/pauper_legal.txt for every card in collection/cards.tsv
  python3 tools/pauper_legal.py "Name" ... # just check these names

A card counts if any non-Funny printing is Common (C) or a basic-type Land (L) and it isn't banned. Commons printed
only in Commander precons are false positives (Sol Ring, Arcane Signet, Command Tower): always confirm final picks with
the mtg-rules card_search tool (game_format="pauper").
Scryfall is blocked from the cloud workspace, which is why this uses Forge (GitHub is reachable).
"""
import os, re, sys, glob, subprocess, unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, '.cache', 'forge')
RES = os.path.join(CACHE, 'forge-gui', 'res')

def norm(n):
    n = unicodedata.normalize('NFKD', n).encode('ascii', 'ignore').decode().split(' // ')[0].strip().lower()
    return re.sub(r'\s+', ' ', n)

def ensure_forge():
    if os.path.isdir(os.path.join(RES, 'editions')):
        subprocess.run(['git', '-C', CACHE, 'pull', '-q', '--depth', '1'], capture_output=True)
        return
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    subprocess.run(['git', 'clone', '-q', '--depth', '1', '--filter=blob:none', '--sparse',
                    'https://github.com/Card-Forge/forge.git', CACHE], check=True)
    subprocess.run(['git', '-C', CACHE, 'sparse-checkout', 'set', 'forge-gui/res/editions', 'forge-gui/res/formats'], check=True)

def pauper_pool():
    ensure_forge()
    fmt = open(os.path.join(RES, 'formats', 'Sanctioned', 'Pauper.txt')).read()
    banned = {norm(b) for b in re.search(r'Banned:(.*)', fmt).group(1).split(';')}
    common = set()
    for f in glob.glob(os.path.join(RES, 'editions', '*.txt')):
        txt = open(f, encoding='utf-8', errors='ignore').read()
        if re.search(r'^Type=Funny', txt, re.M): continue
        sec = None
        for line in txt.splitlines():
            if line.startswith('['): sec = line.strip('[]').lower(); continue
            if sec not in ('cards', 'main', 'card'): continue
            m = re.match(r'^\S+\s+([CULSRMTP])\s+(.+?)(?:\s+@.*)?$', line.strip())
            if m and m.group(1) in 'CL': common.add(norm(m.group(2)))
    return common - banned

def main():
    pool = pauper_pool()
    if len(sys.argv) > 1:
        for n in sys.argv[1:]: print(('LEGAL   ' if norm(n) in pool else 'not legal ') + n)
        return
    names = [l.rsplit('\t', 1)[0] for l in open(os.path.join(ROOT, 'collection', 'cards.tsv')) if '\t' in l]
    ok = sorted(n for n in names if norm(n) in pool and norm(n) not in {'plains', 'island', 'swamp', 'mountain', 'forest', 'wastes'})
    open(os.path.join(ROOT, 'collection', 'pauper_legal.txt'), 'w').write('\n'.join(ok) + '\n')
    print(f'{len(ok)} owned cards are Pauper candidates -> collection/pauper_legal.txt')

if __name__ == '__main__': main()
