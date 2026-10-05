"""The MCP tool that builds sheets on the homelab for Claude on the laptop.

Loaded from the file path rather than imported, because mcp_server/ is a script
rather than a package and importing it would run the module-level server setup.

The tool is split in two: `_build_proxy_sheet` does the work and returns a plain
dict of fields (easy to assert on), and `print_proxies` wraps that into the MCP
`CallToolResult` the chat sees — an inline preview image, a download link, and,
for a small sheet, the PDF as an embedded resource.
"""
import importlib.util, os, sys, time

import pytest
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)


@pytest.fixture(scope='module')
def server():
    spec = importlib.util.spec_from_file_location('gauntlet_server', os.path.join(ROOT, 'mcp_server/server.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def served(server, tmp_path, monkeypatch):
    """Point the tool at a throwaway served directory, not the real homelab one."""
    folder = tmp_path / 'served'
    folder.mkdir()
    monkeypatch.setattr(server, 'PROXY_SERVE_DIR', str(folder))
    monkeypatch.setattr(server, 'PROXY_PUBLIC_BASE', 'https://cards.test/proxies')
    return folder


@pytest.fixture
def pics(tmp_path):
    folder = tmp_path / 'pics'
    folder.mkdir()
    for i, colour in enumerate([(30, 60, 90), (200, 40, 40), (240, 240, 230), (20, 120, 60)]):
        Image.new('RGB', (488, 680), colour).save(folder / f'c{i}.jpg', 'JPEG',
                                                    quality=95, subsampling=0)
    return folder


# ---------------------------------------------------------------- validation
@pytest.mark.parametrize('kwargs,expected', [
    ({}, 'exactly one'),
    ({'deck': 'laezel-counters', 'images_dir': '/tmp'}, 'exactly one'),
    ({'deck': 'no-such-deck'}, 'no deck folder'),
    ({'deck': 'laezel-counters', 'dfc': 'sideways'}, "must be 'front' or 'both'"),
    ({'deck': 'laezel-counters', 'copies': -1}, 'negative'),
    ({'images_dir': '/no/such/folder'}, 'no such directory'),
    ({'images_dir': 'EMPTY'}, 'nothing to print'),
])
def test_arguments_are_refused_with_a_readable_message(server, served, tmp_path, kwargs, expected):
    if 'EMPTY' in kwargs.values():
        empty = tmp_path / 'empty'
        empty.mkdir()
        kwargs = {k: (str(empty) if v == 'EMPTY' else v) for k, v in kwargs.items()}
    got = server._build_proxy_sheet(**kwargs)
    assert expected in got['error'], got
    assert 'traceback' not in got['error'].lower()


def test_a_bad_request_comes_back_as_an_error_result(server, served):
    res = server.print_proxies()
    assert res.isError is True
    assert 'exactly one' in res.content[0].text
    assert 'exactly one' in res.structuredContent['error']


# ---------------------------------------------------------------- building
def test_a_folder_becomes_a_pdf_plus_an_scp_line(server, served, pics, tmp_path):
    out = tmp_path / 'sheet.pdf'
    got = server._build_proxy_sheet(images_dir=str(pics), out=str(out))
    assert got['cards'] == 4 and got['pages'] == 1
    assert out.exists()
    assert got['fetch'] == f'scp homelab:{out} .'
    assert '63.2 x 88.2' in got['print']
    assert len(got['sha256']) == 64


def test_a_deck_builds_in_decklist_order(server, served, tmp_path):
    out = tmp_path / 'deck.pdf'
    got = server._build_proxy_sheet(deck='laezel-counters', out=str(out), exclude_basics=True)
    assert got['cards'] > 0
    assert got['card_pages'] == -(-got['cards'] // 8)
    assert got['sources'] == {'card_images.json': got['cards']}
    assert got['low_resolution'] == []


def test_the_preview_is_rendered_even_without_the_preview_flag(server, served, pics, tmp_path):
    # The tool always renders page 1, so the chat always gets an inline image.
    got = server._build_proxy_sheet(images_dir=str(pics), out=str(tmp_path / 'p.pdf'))
    assert os.path.exists(got['preview'])
    assert os.path.exists(got['_served_png'])


def test_calibration_adds_a_leading_page(server, served, pics, tmp_path):
    got = server._build_proxy_sheet(images_dir=str(pics), out=str(tmp_path / 'cal.pdf'),
                                    calibration=True)
    assert got['pages'] == got['card_pages'] + 1, got


def test_the_same_request_twice_gives_the_same_bytes(server, served, pics, tmp_path):
    a = server._build_proxy_sheet(images_dir=str(pics), out=str(tmp_path / 'a.pdf'))
    b = server._build_proxy_sheet(images_dir=str(pics), out=str(tmp_path / 'b.pdf'))
    assert a['sha256'] == b['sha256']


# ---------------------------------------------------------------- publishing
def test_the_url_is_built_from_the_deck_name_and_the_hash(server, served, pics, tmp_path):
    got = server._build_proxy_sheet(images_dir=str(pics), out=str(tmp_path / 'pics.pdf'))
    stem = f"pics-{got['sha256'][:12]}"
    assert got['served_name'] == stem
    assert got['url'] == f'https://cards.test/proxies/{stem}.pdf'
    assert got['preview_url'] == f'https://cards.test/proxies/{stem}-p1.png'
    # the sheet and its preview are actually copied into the served directory
    assert (served / f'{stem}.pdf').exists()
    assert (served / f'{stem}-p1.png').exists()


def test_the_inline_preview_is_a_downscaled_png(server, served, pics, tmp_path):
    got = server._build_proxy_sheet(images_dir=str(pics), out=str(tmp_path / 'w.pdf'))
    assert Image.open(got['_served_png']).width == server.PROXY_PREVIEW_WIDTH


def test_old_served_files_are_pruned(server, served, pics, tmp_path):
    stale = served / 'old-deadbeef0000.pdf'
    stale.write_bytes(b'%PDF-1.4 stale')
    old = time.time() - (server.PROXY_PRUNE_DAYS + 1) * 86400
    os.utime(stale, (old, old))
    got = server._build_proxy_sheet(images_dir=str(pics), out=str(tmp_path / 'fresh.pdf'))
    assert got['pruned'] >= 1
    assert not stale.exists()
    assert (served / f"{got['served_name']}.pdf").exists()


# ---------------------------------------------------------------- the result Claude sees
def test_the_result_carries_an_inline_image_and_the_links(server, served, pics, tmp_path):
    res = server.print_proxies(images_dir=str(pics), out=str(tmp_path / 'r.pdf'))
    assert res.isError is False
    kinds = [c.type for c in res.content]
    assert 'image' in kinds
    image = next(c for c in res.content if c.type == 'image')
    assert image.mimeType == 'image/png' and len(image.data) > 0
    assert res.structuredContent['url'] == f"https://cards.test/proxies/{res.structuredContent['served_name']}.pdf"
    text = next(c for c in res.content if c.type == 'text').text
    assert res.structuredContent['url'] in text
    assert res.structuredContent['preview_url'] in text


def test_a_small_pdf_is_embedded_as_a_resource(server, served, pics, tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'PROXY_EMBED_MAX_BYTES', 50 * 1024 * 1024)
    res = server.print_proxies(images_dir=str(pics), out=str(tmp_path / 's.pdf'))
    assert res.structuredContent['embed'] is True
    resources = [c for c in res.content if c.type == 'resource']
    assert len(resources) == 1
    assert resources[0].resource.mimeType == 'application/pdf'
    assert len(resources[0].resource.blob) > 0


def test_a_large_pdf_is_not_embedded(server, served, pics, tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'PROXY_EMBED_MAX_BYTES', 1)   # anything real is "too big"
    res = server.print_proxies(images_dir=str(pics), out=str(tmp_path / 'l.pdf'))
    assert res.structuredContent['embed'] is False
    assert [c for c in res.content if c.type == 'resource'] == []
    # the link is still there, so the sheet is still reachable
    assert res.structuredContent['url'].endswith('.pdf')
