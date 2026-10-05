"""The same input must always give the same bytes.

Run in fresh processes on purpose: a hash that only holds inside one interpreter
is not a hash, it is a coincidence of caches and import order.
"""
import hashlib, io, json, os, subprocess, sys

import pytest
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)

from tools.proxies import render


def cards(n):
    out = []
    for i in range(n):
        buf = io.BytesIO()
        Image.new('RGB', (488, 680), (30 + 12 * i, 60, 90)).save(buf, 'JPEG', quality=95, subsampling=0)
        out.append({'name': f'card-{i}', 'jpeg': buf.getvalue()})
    return out


CHILD = r'''
import hashlib, io, json, sys
sys.path.insert(0, %(root)r)
from PIL import Image
from tools.proxies import render
payload = json.loads(sys.argv[2])
cards = []
for name, colour in payload['cards']:
    buf = io.BytesIO()
    Image.new('RGB', (488, 680), tuple(colour)).save(buf, 'JPEG', quality=95, subsampling=0)
    cards.append({'name': name, 'jpeg': buf.getvalue()})
summary = render.write_pdf(sys.argv[1], cards, calibration=payload['calibration'])
print(summary['sha256'])
'''


def child_run(out, spec):
    code = CHILD % {'root': ROOT}
    r = subprocess.run([sys.executable, '-c', code, out, json.dumps(spec)],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def sha(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


SPEC = {'calibration': False, 'cards': [[f'card-{i}', [30 + 12 * i, 60, 90]] for i in range(9)]}


def test_two_fresh_processes_agree(tmp_path):
    a, b = str(tmp_path / 'a.pdf'), str(tmp_path / 'b.pdf')
    assert child_run(a, SPEC) == child_run(b, SPEC) == sha(a)
    assert sha(a) == sha(b)


def test_a_different_input_gives_a_different_hash(tmp_path):
    a = str(tmp_path / 'a.pdf')
    child_run(a, SPEC)
    other = {'calibration': False, 'cards': [[f'card-{i}', [31 + 12 * i, 60, 90]] for i in range(9)]}
    b = str(tmp_path / 'b.pdf')
    child_run(b, other)
    assert sha(a) != sha(b)


def test_calibration_page_is_also_stable(tmp_path):
    spec = dict(SPEC, calibration=True)
    a, b = str(tmp_path / 'a.pdf'), str(tmp_path / 'b.pdf')
    assert child_run(a, spec) == child_run(b, spec)


def test_card_order_matters(tmp_path):
    forward = str(tmp_path / 'f.pdf')
    backward = str(tmp_path / 'b.pdf')
    child_run(forward, SPEC)
    child_run(backward, {'calibration': False, 'cards': list(reversed(SPEC['cards']))})
    assert sha(forward) != sha(backward)


def test_in_process_render_matches_child(tmp_path):
    out = str(tmp_path / 'x.pdf')
    summary = render.write_pdf(out, cards(9))
    assert summary['sha256'] == sha(out)
    assert summary['sha256'] == child_run(str(tmp_path / 'y.pdf'), SPEC)