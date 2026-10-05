#!/usr/bin/env python3
"""Optional Real-ESRGAN super-resolution for proxy source images.

This is the one part of the pipeline that is *not* deterministic. It shells out
to `realesrgan-ncnn-vulkan`, which runs a 4x super-resolution model on the GPU
(the RX 580 here, through Vulkan/RADV — no ROCm needed). The output depends on
the binary, the model and the driver, so a sheet built with `upscale` does not
carry the byte-identical guarantee the rest of tools/proxies does. Everything
else still holds: the layout geometry is unchanged, the images are just sharper.

It is opt-in because it is slow: roughly 9 s per distinct card on this GPU, so a
100-card deck is ~10-15 minutes the first time. Results are cached by
(source hash, model, scale), so re-runs and cards shared between decks are free,
and only the *distinct* source images are ever sent to the GPU.

The binary and its models are not in the repo. By default they live in
`/mnt/expansion/mtg-data/realesrgan/` (installed from the upstream
realesrgan-ncnn-vulkan release); override with REALESRGAN_BIN / REALESRGAN_MODELS.
"""
import hashlib, os, shutil, subprocess, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_DIR = '/mnt/expansion/mtg-data/realesrgan'
BIN = os.environ.get('REALESRGAN_BIN', os.path.join(DEFAULT_DIR, 'realesrgan-ncnn-vulkan'))
MODELS = os.environ.get('REALESRGAN_MODELS', os.path.join(DEFAULT_DIR, 'models'))
DEFAULT_MODEL = os.environ.get('REALESRGAN_MODEL', 'realesrgan-x4plus')
GPU_ID = os.environ.get('REALESRGAN_GPU', '0')
SCALE = 4                               # the x4plus model is a 4x model
CACHE = 'cache/proxy-upscaled'
TIMEOUT = 3600                          # a whole deck's batch, with headroom


class UpscaleError(Exception):
    """Upscaling was asked for but could not be done."""


def available():
    """True when the binary and its model file are both present."""
    return (os.path.exists(BIN) and os.access(BIN, os.X_OK)
            and os.path.exists(os.path.join(MODELS, f'{DEFAULT_MODEL}.param')))


def _key(data, model, scale):
    return hashlib.sha256(data + f'|{model}|x{scale}'.encode()).hexdigest()


def _cache_path(key, cache_root=None):
    return os.path.join(ROOT, cache_root or CACHE, f'{key}.png')


def _run_batch(in_dir, out_dir, model):
    """One realesrgan process over a whole folder (the model loads once)."""
    cmd = [BIN, '-i', in_dir, '-o', out_dir, '-n', model, '-s', str(SCALE),
           '-m', MODELS, '-g', GPU_ID, '-f', 'png']
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
    except FileNotFoundError:
        raise UpscaleError(f'realesrgan binary not found at {BIN}')
    except subprocess.TimeoutExpired:
        raise UpscaleError(f'realesrgan timed out after {TIMEOUT}s')
    if proc.returncode != 0:
        raise UpscaleError(f'realesrgan failed ({proc.returncode}): {proc.stderr.strip()[-400:]}')


def upscale_map(datas, model=None, scale=SCALE, cache_root=None):
    """Upscale a set of distinct source images, newest model wins.

    `datas` is an iterable of raw image bytes (duplicates are fine and collapse).
    Returns {source_sha256 -> upscaled_png_bytes}. Cached results are read
    straight back; only cache misses go to the GPU, all in a single batch.
    Raises UpscaleError if the binary is unavailable or the run fails.
    """
    if not available():
        raise UpscaleError(
            f'Real-ESRGAN is not installed: expected {BIN} and {MODELS}/{DEFAULT_MODEL}.param. '
            'Set REALESRGAN_BIN / REALESRGAN_MODELS or install the realesrgan-ncnn-vulkan release.')
    model = model or DEFAULT_MODEL
    if not os.path.exists(os.path.join(MODELS, f'{model}.param')):
        raise UpscaleError(f'no Real-ESRGAN model {model!r} in {MODELS}')

    by_sha = {hashlib.sha256(d).hexdigest(): d for d in datas}
    out = {}
    misses = {}
    for sha, data in by_sha.items():
        cached = _cache_path(_key(data, model, scale), cache_root)
        if os.path.exists(cached):
            with open(cached, 'rb') as f:
                out[sha] = f.read()
        else:
            misses[sha] = data

    if misses:
        cache_dir = os.path.join(ROOT, cache_root or CACHE)
        os.makedirs(cache_dir, exist_ok=True)
        with tempfile.TemporaryDirectory() as tin, tempfile.TemporaryDirectory() as tout:
            order = list(misses)
            for i, sha in enumerate(order):
                with open(os.path.join(tin, f'{i:04d}.png'), 'wb') as f:
                    f.write(misses[sha])
            _run_batch(tin, tout, model)
            for i, sha in enumerate(order):
                produced = os.path.join(tout, f'{i:04d}.png')
                if not os.path.exists(produced):
                    raise UpscaleError(f'realesrgan produced no output for one image ({sha[:12]})')
                final = _cache_path(_key(misses[sha], model, scale), cache_root)
                shutil.move(produced, final)
                with open(final, 'rb') as f:
                    out[sha] = f.read()
    return out
