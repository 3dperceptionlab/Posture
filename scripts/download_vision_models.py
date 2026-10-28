"""Bake upstream ONNX models into the image so analysis needs no Internet."""
import hashlib
import io
import json
import urllib.request
import zipfile
from pathlib import Path

root = Path('/opt/vision-models')
root.mkdir(parents=True, exist_ok=True)
urls = {
    'detector': 'https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/yolox_m_8xb8-300e_humanart-c2c7a14a.zip',
    'pose': 'https://download.openmmlab.com/mmpose/v1/projects/rtmw/onnx_sdk/rtmw-dw-x-l_simcc-cocktail14_270e-256x192_20231122.zip',
}
manifest = {'estimator': 'RTMW-x / COCO-WholeBody 133', 'rtmlib': '0.0.16', 'models': {}}
for name, url in urls.items():
    print('Downloading', name, flush=True)
    with urllib.request.urlopen(url, timeout=180) as response:
        data = response.read()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        files = [f for f in archive.namelist() if f.endswith('.onnx')]
        if len(files) != 1:
            raise RuntimeError(f'Unexpected model archive: {files}')
        model = archive.read(files[0])
    (root / (name + '.onnx')).write_bytes(model)
    manifest['models'][name] = {'url': url, 'archive_sha256': hashlib.sha256(data).hexdigest(),
                              'sha256': hashlib.sha256(model).hexdigest()}
(root / 'manifest.json').write_text(json.dumps(manifest, indent=2))
