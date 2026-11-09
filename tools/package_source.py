"""Package the current viewer source, static resources and animation build inputs."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from core.version import VERSION, BUILD

SKIP = {'__pycache__', 'bin', 'obj', '.git', '.venv', '.pytest_cache', 'node_modules', '.cache'}
PRIVATE_NAMES = {'license.json', 'activation.json', 'settings.json', 'owner-signing-key.pem'}


def allowed(path: Path, relative: Path) -> bool:
    name = path.name.lower()
    return (not SKIP.intersection(relative.parts)
            and path.suffix.lower() not in {'.pyc', '.pyo', '.pem', '.key', '.pfx', '.p12', '.partial'}
            and name not in PRIVATE_NAMES and not name.startswith('.env')
            and not ('aeskey' in name and path.suffix.lower() == '.json'))


def _rel(path):
    """清单里只写包内相对路径，避免泄漏构建机器的绝对路径。"""
    try:
        return path.resolve().relative_to(BASE.resolve()).as_posix()
    except ValueError:
        return path.name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=BASE/f'VertexViewer-{VERSION}+{BUILD}-full-source.zip')
    parser.add_argument('--animation-sdk', type=Path)
    parser.add_argument('--native-source', type=Path)
    parser.add_argument('--fluent-source', type=Path)
    args = parser.parse_args()
    files = {}

    def add(source, target):
        source = Path(source)
        if not source.is_file(): raise FileNotFoundError(source)
        if target in files: raise ValueError('Duplicate archive entry: ' + target)
        files[target] = source

    def tree(source, target):
        if not source.is_dir(): raise FileNotFoundError(source)
        for path in sorted(source.rglob('*')):
            relative = path.relative_to(source)
            if path.is_file() and allowed(path, relative):
                add(path, (Path(target)/relative).as_posix())

    for name in ('app', 'assets', 'core', 'docs', 'exporters', 'render', 'tests', '_cue'):
        tree(BASE/name, name)
    # SDK is added separately so extracted packages can be archived again.
    for path in sorted((BASE/'tools').rglob('*')):
        relative = path.relative_to(BASE/'tools')
        if path.is_file() and allowed(path, relative) and not relative.is_relative_to('animation_bridge/sdk'):
            add(path, 'tools/'+relative.as_posix())
    for name in ('__main__.py', 'cache.py', 'VertexViewer.spec', 'requirements.txt',
                 'requirements-build.txt', 'README-source.md', 'README.md', 'NOTES.md',
                 'build-source.ps1', '启动 VertexViewer.bat'):
        path = BASE/name
        if path.exists():
            add(path, name)
    # 游戏派生数据（物品图标库、中文名表、本地化表）不进发布包：
    # 显示名由 core/humanize.py 从代号生成，图标用占位块。
    for name in ('mesh_catalog.json', 'pakinfo.json'):
        path = BASE/'work'/name
        if path.exists():
            add(path, 'work/'+name)

    sdk = args.animation_sdk or BASE/'tools/animation_bridge/sdk'
    if not sdk.is_dir() and args.animation_sdk is None: sdk = BASE/'work/animation-hands-sdk'
    native = args.native_source or BASE/'third_party/CUE4Parse-native'
    if not native.is_dir() and args.native_source is None: native = BASE/'work/cue-native-source'
    fluent = args.fluent_source or BASE/'third_party/fluentpy-qt'
    if not fluent.is_dir() and args.fluent_source is None: fluent = BASE.parent/'vertexviewer/third_party/fluentpy-qt'
    sdk_manifest = json.loads((BASE/'tools/animation_bridge/sdk-manifest.json').read_text(encoding='utf-8'))
    for name, digest in sdk_manifest['source'].items():
        if hashlib.sha256((sdk/name).read_bytes()).hexdigest() != digest:
            raise ValueError('Animation SDK hash mismatch: '+name)
    tree(sdk, 'tools/animation_bridge/sdk')
    tree(native, 'third_party/CUE4Parse-native')
    tree(fluent, 'third_party/fluentpy-qt')
    required = ('app/wizard.py', 'core/inspection.py', 'core/inspection_scene.py',
                'core/gunsmith_animation.py', 'core/activation.py', 'core/part_offsets.json',
                'exporters/animation_glb.py', 'render/shaders/scene.frag',
                'assets/animation/VertexViewer.AnimationBridge.exe', 'assets/animation/CUE4Parse-Natives.dll',
                'assets/audio/OPEN_0.wav', 'assets/credits.json', 'assets/wizard_row3.png',
                'tools/animation_bridge/Program.cs', 'tools/animation_bridge/sdk/dfmap.dll',
                'third_party/CUE4Parse-native/CUE4Parse-Natives/ACL/ACL.cpp',
                'third_party/CUE4Parse-native/CUE4Parse-Natives/ACL/external/acl/includes/acl/core/iallocator.h',
                'third_party/fluentpy-qt/fluentpy/__init__.py', 'build-source.ps1')
    for name in required:
        if name not in files: raise FileNotFoundError('Required archive entry: '+name)

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix+'.partial')
    root = 'VertexViewer-source/'
    entries = []
    with zipfile.ZipFile(partial, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for target, source in sorted(files.items()):
            data = source.read_bytes()
            if re.search(rb'-----BEGIN (?:ENCRYPTED |RSA |EC |OPENSSH )?PRIVATE KEY-----\s*\r?\n[A-Za-z0-9+/=]{32,}', data):
                raise ValueError('Unexpected private key material: '+target)
            entries.append({'file': target, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
            archive.writestr(root+target, data)
        manifest = {'product': 'VertexViewer', 'version': f'{VERSION}+{BUILD}',
                    'packaged_at': datetime.now(timezone.utc).isoformat(), 'project': BASE.name,
                    'animation_sdk': _rel(sdk), 'native_source': _rel(native),
                    'pinned_sdk_hashes': sdk_manifest['source'], 'file_count': len(entries),
                    'total_bytes': sum(item['bytes'] for item in entries), 'files': entries}
        archive.writestr(root+'SOURCE-MANIFEST.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(partial) as archive:
        if archive.testzip() is not None: raise ValueError('ZIP CRC verification failed')
        if len(archive.namelist()) != len(entries)+1: raise ValueError('ZIP file count differs')
        for entry in entries:
            data = archive.read(root+entry['file'])
            if len(data) != entry['bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
                raise ValueError('ZIP content differs: '+entry['file'])
            if data != files[entry['file']].read_bytes(): raise ValueError('Source changed: '+entry['file'])
    partial.replace(output)
    digest = hashlib.file_digest(output.open('rb'), 'sha256').hexdigest()
    output.with_suffix(output.suffix+'.sha256').write_text(digest+'  '+output.name+'\n', encoding='utf-8')
    print(json.dumps({'archive': str(output), 'bytes': output.stat().st_size,
                      'files': len(entries)+1, 'source_bytes': manifest['total_bytes'],
                      'sha256': digest, 'zip_crc': 'passed', 'content_hashes': 'passed'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
