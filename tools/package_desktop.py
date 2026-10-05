"""Add notices and corresponding source, then build a private-data-free desktop ZIP."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
from urllib.request import urlopen
from zipfile import ZIP_DEFLATED, ZipFile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from companion import __version__
from tools.build_release import build_release


def download(url,target,expected=None):
    if target.exists() and (not expected or hashlib.sha256(target.read_bytes()).hexdigest()==expected):return
    with urlopen(url,timeout=30) as response:raw=response.read()
    if expected and hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('Third-party source digest mismatch')
    target.write_bytes(raw)


def package(app,python_root,build_env,inno):
    notices=app/'licenses';notices.mkdir(exist_ok=True)
    site=build_env/'Lib/site-packages'
    inputs={
        'Python-LICENSE.txt':python_root/'LICENSE.txt',
        'Tk-license.terms':python_root/'tcl/tk8.6/license.terms',
        'Pillow-LICENSE.txt':site/'pillow-12.0.0.dist-info/licenses/LICENSE',
        'pystray-COPYING.txt':site/'pystray-0.19.5.dist-info/COPYING',
        'pystray-LGPL.txt':site/'pystray-0.19.5.dist-info/COPYING.LGPL',
        'six-LICENSE.txt':site/'six-1.17.0.dist-info/LICENSE',
        'PyInstaller-COPYING.txt':site/'pyinstaller-6.22.0.dist-info/licenses/COPYING.txt',
        'InnoSetup-LICENSE.txt':inno/'LICENSE.TXT',
    }
    for name,path in inputs.items():shutil.copy2(path,notices/name)
    download('https://raw.githubusercontent.com/tcltk/tcl/core-8-6-branch/license.terms',notices/'Tcl-license.terms')
    download('https://raw.githubusercontent.com/openssl/openssl/openssl-3.0/LICENSE.txt',notices/'OpenSSL-LICENSE.txt')
    sources=app/'corresponding-source';sources.mkdir(exist_ok=True)
    # Author's annotated v0.19.5 tag resolves to this immutable commit.
    download('https://codeload.github.com/moses-palmer/pystray/tar.gz/1907f8681d6d421517c63d94f425f9cdd74d0034',
             sources/'pystray-0.19.5-source.tar.gz')
    upstream=ROOT/'.local/Shattered-Pixel-Dungeon-4.0.1-source.zip'
    if not upstream.is_file():raise ValueError('Pinned upstream git archive is required')
    shutil.copy2(upstream,sources/upstream.name)
    source_zip,digest=build_release()
    shutil.copy2(source_zip,sources/source_zip.name)
    for name in ('README.md','BUILD.md','LICENSE.txt','THIRD_PARTY_NOTICES.md'):shutil.copy2(ROOT/name,app/name)
    target=ROOT/'dist'/f'灯火免安装-{__version__}.zip'
    manifest={}
    with ZipFile(target,'w',compression=ZIP_DEFLATED,compresslevel=6) as archive:
        for path in sorted(app.rglob('*')):
            if path.is_symlink():raise ValueError('Linked desktop package input')
            if path.is_file():
                name=path.relative_to(app).as_posix()
                if name.startswith(('.local/','.research/','backups/')) or name.endswith('.dat'):
                    raise ValueError('Private desktop package input')
                manifest[name]=hashlib.sha256(path.read_bytes()).hexdigest()
                archive.write(path,'灯火/'+name)
        archive.writestr('灯火/DESKTOP-MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    checksum=hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix('.zip.sha256').write_text(checksum+'  '+target.name+'\n',encoding='utf-8')
    print(str(target));print('SHA-256 '+checksum)
    return target


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser()
    parser.add_argument('application',type=Path)
    parser.add_argument('--python-root',type=Path,required=True)
    parser.add_argument('--build-env',type=Path,required=True)
    parser.add_argument('--inno',type=Path,required=True)
    args=parser.parse_args()
    package(args.application.resolve(),args.python_root,args.build_env,args.inno)
