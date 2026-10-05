"""Build sheets end to end through the CLI, and check them against real exports.

`test_reference_exports` is the one that matters most: it reads actual mtgprint
PDFs and demands that every page of every one of them matches what `layout.py`
draws. Those files are not in the repo (17 MB each), so point `PROXY_REF_DIR` at
a directory of them and the test runs; without it the test skips and says so.

    PROXY_REF_DIR=/path/to/exports .venv/bin/python -m pytest tools/proxies/tests
"""
import glob, io, os, subprocess, sys

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from tools.proxies import images, verify_references
from tools.proxies.profiles import PROFILE

REF_DIR = os.environ.get('PROXY_REF_DIR', '')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _cards(n, folder, name='c'):
    """Write n synthetic card scans and return the folder."""
    folder.mkdir(exist_ok=True)
    for i in range(n):
        im = Image.new('RGB', (488, 680), (30 + i * 4, 60, 90))
        im.save(folder / f'{name}{i:03}.jpg', 'JPEG', quality=95, subsampling=0)
    return folder


def test_deck_mode_builds_a_printable_sheet(tmp_path):
    from tools.proxies.cli import main
    out = tmp_path / 'deck.pdf'
    cards = _cards(9, tmp_path / 'pics')
    manifest = tmp_path / 'manifest.txt'
    manifest.write_text(''.join(f'1 {p.name}\n' for p in sorted(cards.iterdir())))
    summary = main(['--images', str(cards), '--order', str(manifest), '--out', str(out),
                    '--quiet'])
    assert summary['cards'] == 9
    assert summary['card_pages'] == 2
    assert os.path.exists(out)
    assert len(summary['sha256']) == 64


def test_preview_and_calibration_flags(tmp_path):
    from tools.proxies.cli import main
    out = tmp_path / 'cal.pdf'
    cards = _cards(3, tmp_path / 'pics2')
    summary = main(['--images', str(cards), '--out', str(out),
                    '--preview', '--calibration', '--quiet'])
    assert summary['pages'] == summary['card_pages'] + 1
    assert os.path.exists(summary['preview'])


def test_only_missing_and_exclude_basics_use_the_collection(tmp_path):
    from tools.proxies import sources
    entries = sources.expand('laezel-counters')
    assert len(entries) == 100
    trimmed = sources.only_missing(entries, owned={})
    assert trimmed == entries
    dropped = sources.expand('laezel-counters', exclude_basics=True)
    assert len(dropped) < len(entries)
    assert all(e['name'] not in sources.BASICS for e in dropped)


@pytest.mark.parametrize('argv', [[], ['--deck', 'laezel-counters', '--images', '/tmp']])
def test_exactly_one_source_is_required(argv):
    from tools.proxies.cli import main
    with pytest.raises(SystemExit):
        main(argv + ['--quiet'])


def test_an_unknown_deck_is_reported():
    from tools.proxies import sources
    with pytest.raises(sources.SourceError) as err:
        sources.deck_cards('no-such-deck')
    assert 'no-such-deck' in str(err.value)


def test_module_entry_point_runs(tmp_path):
    cards = _cards(2, tmp_path / 'pics3')
    out = tmp_path / 'cli.pdf'
    r = subprocess.run([sys.executable, '-m', 'tools.proxies', '--images', str(cards),
                        '--out', str(out)], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert 'cards from' in r.stdout
    assert os.path.exists(out)


@pytest.mark.parametrize('name', sorted(os.path.basename(p) for p in
                                        glob.glob(os.path.join(REF_DIR, '*.pdf'))))
def test_reference_exports(name):
    """Every page of a real mtgprint export matches layout.py."""
    _, verdict, problems = verify_references.check(os.path.join(REF_DIR, name))
    assert not problems, f'{name}: {verdict}\n' + '\n'.join(problems[:10])


def test_reference_dir_is_configured():
    if not REF_DIR:
        pytest.skip('set PROXY_REF_DIR to a directory of mtgprint exports to run this')
    assert glob.glob(os.path.join(REF_DIR, '*.pdf')), f'no PDFs in {REF_DIR}'


def test_prepared_image_is_what_the_pdf_embeds(tmp_path):
    """The bytes handed to ReportLab are the bytes prepare() returned."""
    from tools.proxies import render
    card = images.prepare(open(__file__, 'rb').read()[:0] or _jpeg(), cache_root=str(tmp_path))
    out = tmp_path / 'one.pdf'
    render.write_pdf(str(out), [{'name': 'x', 'jpeg': card['jpeg']}])
    import pymupdf
    doc = pymupdf.open(out)
    raw = doc.extract_image(doc[0].get_image_info(xrefs=True)[0]['xref'])
    doc.close()
    assert raw['image'] == card['jpeg']
    assert raw['ext'] == 'jpeg'


def _jpeg():
    buf = io.BytesIO()
    Image.new('RGB', (488, 680), (25, 40, 60)).save(buf, 'JPEG', quality=95, subsampling=0)
    return buf.getvalue()