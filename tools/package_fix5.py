"""Package fix5 only after native EXE and full-catalog audits succeed."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

BASE=Path(__file__).resolve().parents[1]
ROOT=BASE/'dist/releases/fix5/VertexViewer'
OUT=BASE/'work/operators-20261101'
report=json.loads((OUT/'frozen-release-check/release-verification.json').read_text(encoding='utf-8'))
assert report['frozen'] and not report['errors'] and report['version']=='1.0+2026-11-01.fix5'
assert len(report['operators'])==4 and report['features']['credits_settings_unchanged']
audit=json.loads((OUT/'operator-audit.json').read_text())
assert audit['total']==484 and not any('error' in m or m['missing_materials'] for m in audit['models'])
materials=json.loads((OUT/'operator-material-audit.json').read_text())
assert materials['complete'] and not materials['errors']
assert not any(m.get('unresolved_base') for m in materials['materials'])
# Refuse a verification result produced before the final executable.
assert (OUT/'frozen-release-check/release-verification.json').stat().st_mtime >= (ROOT/'VertexViewer.exe').stat().st_mtime
shutil.copy2(BASE/'docs/NOTES-29.md',ROOT/'更新说明-fix5.md')
archive=BASE/'VertexViewer-1.0+2026-11-01.fix5-win64.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for file in sorted(ROOT.rglob('*')):
        if file.is_file() and '__pycache__' not in file.parts:
            z.write(file,str(file.relative_to(ROOT.parent)))
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    count=len(z.infolist())
result={'archive':str(archive),'bytes':archive.stat().st_size,
        'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'zip_files':count,
        'executable':str(ROOT/'VertexViewer.exe'),'operator_models':audit['total'],
        'operator_materials':len(materials['materials']),'frozen_errors':report['errors']}
(OUT/'delivery.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
