"""The optional Real-ESRGAN upscale path.

Most of these stub out the GPU: `fake_gpu` replaces the realesrgan subprocess
with a plain 4x resize and makes the binary look installed, so the dedupe, cache
and wiring logic is tested without a GPU or the binary. One test actually runs
the binary and is skipped unless REALESRGAN_GPU_TEST=1.
"""
import importlib.util, io, os, sys

import pytest
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)

from tools.proxies import cli, images, upscale  # noqa: E402


def card_bytes(colour=(20, 40, 80), size=(488, 680)):
    buf = io.BytesIO()
    Image.new('RGB', size, colour).save(buf, 'PNG')
    return buf.getvalue()


@pytest.fixture(scope='module')
def server():
    spec = importlib.util.spec_from_file_location('gauntlet_server', os.path.join(ROOT, 'mcp_server/server.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fake_gpu(monkeypatch, tmp_path):
    """Make the upscaler look installed and swap the GPU run for a 4x resize."""
    calls = []

    def fake_run_batch(in_dir, out_dir, model):
        names = sorted(os.listdir(in_dir))
        calls.append(names)
        for fn in names:
            with Image.open(os.path.join(in_dir, fn)) as im:
                big = im.resize((im.width * upscale.SCALE, im.height * upscale.SCALE))
            big.save(os.path.join(out_dir, fn))

    monkeypatch.setattr(upscale, 'available', lambda: True)
    monkeypatch.setattr(upscale, '_run_batch', fake_run_batch)
    monkeypatch.setattr(upscale, 'CACHE', str(tmp_path / 'ups-cache'))   # absolute: isolates the cache
    return calls


@pytest.fixture
def pics(tmp_path):
    folder = tmp_path / 'pics'
    folder.mkdir()
    for i, colour in enumerate([(30, 60, 90), (200, 40, 40), (240, 240, 230), (20, 120, 60)]):
        Image.new('RGB', (488, 680), colour).save(folder / f'c{i}.jpg', 'JPEG',
                                                    quality=95, subsampling=0)
    return folder


# ---------------------------------------------------------------- the module
def test_upscale_map_dedupes_caches_and_scales(fake_gpu):
    a, b = card_bytes((10, 20, 30)), card_bytes((90, 10, 10))
    got = upscale.upscale_map([a, a, b])                 # a is a duplicate
    assert set(got) == {images.sha(a), images.sha(b)}    # collapsed to the two distinct
    assert fake_gpu == [['0000.png', '0001.png']]        # one batch, two images
    out = Image.open(io.BytesIO(got[images.sha(a)]))
    assert out.size == (488 * upscale.SCALE, 680 * upscale.SCALE)

    again = upscale.upscale_map([a, b])                  # both cached now
    assert len(fake_gpu) == 1                             # no second GPU run
    assert again[images.sha(a)] == got[images.sha(a)]


def test_upscale_map_errors_when_unavailable(monkeypatch):
    monkeypatch.setattr(upscale, 'available', lambda: False)
    with pytest.raises(upscale.UpscaleError) as e:
        upscale.upscale_map([card_bytes()])
    assert 'not installed' in str(e.value)


# ---------------------------------------------------------------- the CLI
def test_cli_upscale_reports_and_changes_the_bytes(fake_gpu, pics, tmp_path):
    plain = cli.main(['--images', str(pics), '--out', str(tmp_path / 'plain.pdf'), '--quiet'])
    sharp = cli.main(['--images', str(pics), '--out', str(tmp_path / 'sharp.pdf'), '--upscale', '--quiet'])
    assert 'upscaled' not in plain
    assert sharp['upscaled'] == {'model': upscale.DEFAULT_MODEL, 'scale': upscale.SCALE, 'images': 4}
    assert sharp['sha256'] != plain['sha256']            # sharper images -> different sheet


# ---------------------------------------------------------------- the MCP tool
def test_builder_upscale_surfaces_the_field_and_a_new_url(server, fake_gpu, pics, tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'PROXY_SERVE_DIR', str(tmp_path / 'served'))
    monkeypatch.setattr(server, 'PROXY_PUBLIC_BASE', 'https://cards.test/proxies')
    plain = server._build_proxy_sheet(images_dir=str(pics), out=str(tmp_path / 'a.pdf'))
    sharp = server._build_proxy_sheet(images_dir=str(pics), out=str(tmp_path / 'b.pdf'), upscale=True)
    assert sharp['upscaled']['images'] == 4
    assert sharp['url'] != plain['url']                  # different hash -> different served name


def test_result_text_mentions_the_upscale(server, fake_gpu, pics, tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'PROXY_SERVE_DIR', str(tmp_path / 'served'))
    monkeypatch.setattr(server, 'PROXY_PUBLIC_BASE', 'https://cards.test/proxies')
    res = server.print_proxies(images_dir=str(pics), out=str(tmp_path / 'c.pdf'), upscale=True)
    assert res.isError is False
    assert 'Real-ESRGAN' in next(c.text for c in res.content if c.type == 'text')


def test_builder_upscale_without_the_binary_is_a_clean_error(server, pics, tmp_path, monkeypatch):
    monkeypatch.setattr(upscale, 'available', lambda: False)
    monkeypatch.setattr(server, 'PROXY_SERVE_DIR', str(tmp_path / 'served'))
    got = server._build_proxy_sheet(images_dir=str(pics), out=str(tmp_path / 'd.pdf'), upscale=True)
    assert 'not installed' in got['error']
    assert 'traceback' not in got['error'].lower()


# ---------------------------------------------------------------- the real GPU
@pytest.mark.skipif(os.environ.get('REALESRGAN_GPU_TEST') != '1' or not upscale.available(),
                    reason='set REALESRGAN_GPU_TEST=1 with the binary installed to run the real GPU pass')
def test_real_gpu_upscale_quadruples_a_card(tmp_path, monkeypatch):
    monkeypatch.setattr(upscale, 'CACHE', str(tmp_path / 'gpu-cache'))
    data = card_bytes((40, 80, 120))
    got = upscale.upscale_map([data])
    out = Image.open(io.BytesIO(got[images.sha(data)]))
    assert out.size == (488 * upscale.SCALE, 680 * upscale.SCALE)
