"""Compile only against fixed Framework 4.0 references; never needed by players."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ASSEMBLIES = ('mscorlib.dll', 'System.dll', 'System.Core.dll', 'System.Drawing.dll',
              'System.Windows.Forms.dll', 'System.Web.Extensions.dll', 'WindowsBase.dll',
              'PresentationCore.dll', 'PresentationFramework.dll', 'System.Xaml.dll', 'System.Xml.dll')


def build(references, output=None, compiler=None):
    references = Path(references).resolve()
    for name in ASSEMBLIES:
        if not (references/name).is_file():
            raise ValueError('缺少Framework 4.0 reference assembly：'+name)
    inputs = [ROOT/'native'/name for name in ('NativeCompanion.cs', 'NativeCompanion.manifest', 'NativeCompanion.exe.config')]+[ROOT/'data/lamp.ico']
    inputs += [ROOT/'native'/name for name in ('NativeShell.cs', 'NativeWorkspace.cs', 'NativeTheme.xaml')]
    digest = hashlib.sha256(b''.join(path.read_bytes() for path in inputs)+b''.join((references/name).read_bytes() for name in ASSEMBLIES)).hexdigest()
    output = Path(output) if output else ROOT/'.local'/'native'/digest[:20]
    output.mkdir(parents=True, exist_ok=True)
    compiler = Path(compiler or r'C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe')
    exe = output/'NativeCompanion.exe'
    command = [str(compiler), '/nologo', '/noconfig', '/nostdlib+', '/langversion:4', '/target:winexe', '/platform:anycpu',
               '/optimize+', '/out:'+str(exe), '/win32manifest:'+str(inputs[1]), '/win32icon:'+str(inputs[3]),
               *['/reference:'+str(references/name) for name in ASSEMBLIES],
               '/resource:'+str(inputs[6])+',Denghuo.Theme.xaml',
               '/resource:'+str(inputs[3])+',Denghuo.Lamp.ico',
               str(inputs[0]), str(inputs[4]), str(inputs[5])]
    completed = subprocess.run(command, capture_output=True, text=True, encoding='mbcs' if sys.platform == 'win32' else 'utf-8', errors='replace')
    if completed.returncode:
        raise RuntimeError(completed.stdout+completed.stderr)
    shutil.copy2(inputs[2], output/'NativeCompanion.exe.config')
    manifest = {'kind':'functional-native-helper-build', 'final_release_build':False, 'framework_api_baseline':'4.0',
                'source_hash':digest, 'command':command, 'binary_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),
                'inputs':{str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs},
                'references':{name:hashlib.sha256((references/name).read_bytes()).hexdigest() for name in ASSEMBLIES}}
    (output/'build-evidence.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return exe


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--references', required=True)
    parser.add_argument('--output')
    parser.add_argument('--compiler')
    args = parser.parse_args()
    try:
        print(build(args.references, args.output, args.compiler))
    except (ValueError, OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
