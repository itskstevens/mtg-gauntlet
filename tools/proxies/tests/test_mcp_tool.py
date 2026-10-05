"""The MCP tool that builds sheets on the homelab for Claude on the laptop.

Loaded from the file path rather than imported, because mcp_server/ is a script
rather than a package and importing it would run the module-level server setup.
"""
import importlib.util, os, sys

import pytest
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)


@pytest.fixture(scope='module')
def print_proxies():
    spec = importlib.util.spec_from_file_location('gauntlet_server', os.path.join(ROOT, 'mcp_server/server.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.print_proxies


@pytest.fixture
def pics(tmp_path):
    folder = tmp_path / 'pics'
    folder.mkdir()
    for i, colour in enumerate([(30, 60, 90), (200, 40, 40), (240, 240, 230), (20, 120, 60)]):
        Image.new('RGB', (488, 680), colour).save(folder / f'c{i}.jpg', 'JPEG',
                                                    quality=95, subsampling=0)
    return folder


@pytest.mark.parametrize('kwargs,expected', [
    ({}, 'exactly one'),
    ({'deck': 'laezel-counters', 'images_dir': '/tmp'}, 'exactly one'),
    ({'deck': 'no-such-deck'}, 'no deck folder'),
    ({'deck': 'laezel-counters', 'dfc': 'sideways'}, "must be 'front' or 'both'"),
    ({'deck': 'laezel-counters', 'copies': -1}, 'negative'),
    ({'images_dir': '/no/such/folder'}, 'no such directory'),
    ({'images_dir': 'EMPTY'}, 'nothing to print'),
])
def test_arguments_are_refused_with_a_readable_message(print_proxies, tmp_path, kwargs, expected):
    if 'EMPTY' in kwargs.values():
        empty = tmp_path / 'empty'
        empty.mkdir()
        kwargs = {k: (str(empty) if v == 'EMPTY' else v) for k, v in kwargs.items()}
    got = print_proxies(**kwargs)
    assert expected in got['error'], got
    assert 'traceback' not in got['error'].lower()


def test_a_folder_becomes_a_pdf_plus_an_scp_line(print_proxies, pics, tmp_path):
    out = tmp_path / 'sheet.pdf'
    got = print_proxies(images_dir=str(pics), out=str(out))
    assert got['cards'] == 4 and got['pages'] == 1
    assert out.exists()
    assert got['fetch'] == f'scp homelab:{out} .'
    assert '63.2 x 88.2' in got['print']
    assert len(got['sha256']) == 64


def test_a_deck_builds_in_decklist_order(print_proxies, tmp_path):
    out = tmp_path / 'deck.pdf'
    got = print_proxies(deck='laezel-counters', out=str(out), exclude_basics=True)
    assert got['cards'] > 0
    assert got['card_pages'] == -(-got['cards'] // 8)
    assert got['sources'] == {'card_images.json': got['cards']}
    assert got['low_resolution'] == []


def test_calibration_and_preview_flags_reach_the_pdf(print_proxies, pics, tmp_path):
    out = tmp_path / 'cal.pdf'
    got = print_proxies(images_dir=str(pics), out=str(out), calibration=True, preview=True)
    assert got['pages'] == got['card_pages'] + 1, got
    assert os.path.exists(got['preview'])


def test_the_same_request_twice_gives_the_same_bytes(print_proxies, pics, tmp_path):
    a = print_proxies(images_dir=str(pics), out=str(tmp_path / 'a.pdf'))
    b = print_proxies(images_dir=str(pics), out=str(tmp_path / 'b.pdf'))
    assert a['sha256'] == b['sha256']