#!/usr/bin/env python3
"""Package the portable skill, including catalogue/source docs and labelled samples."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
EXTENSIONS={'.md','.py','.yaml','.json','.tsv','.png','.gif','.txt'}


def package(out):
    out=Path(out).resolve();out.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(ROOT.rglob('*')):
            if p.is_symlink() or not p.is_file() or '__pycache__' in p.parts:continue
            if p.name.startswith('.env') or p.name in ('auth.json','credentials.json'):continue
            if p.suffix not in EXTENSIONS and p.name not in ('LICENSE','requirements.txt'):continue
            z.write(p,str(Path(ROOT.name)/p.relative_to(ROOT)))
    with zipfile.ZipFile(out) as z:
        return {'path':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'members':z.namelist(),'crc_error':z.testzip()}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);args=p.parse_args()
    print(json.dumps(package(args.out),ensure_ascii=False,indent=2))
