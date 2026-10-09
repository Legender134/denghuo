"""Build a Windows directory with the native helper already included."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_native_helper import build as build_native


def native_resources(application, expected_helper=None):
    """Validate the actual PyInstaller resource layout, not a developer override."""
    folder = Path(application) / '_internal' / 'native'
    helper, config = folder / 'NativeCompanion.exe', folder / 'NativeCompanion.exe.config'
    if not helper.is_file() or not config.is_file():
        raise ValueError('程序缺少预置原生窗口：_internal/native/NativeCompanion.exe 及其 .exe.config')
    if helper.is_symlink() or config.is_symlink():
        raise ValueError('原生窗口发行输入不能是链接文件')
    with helper.open('rb') as stream:
        if stream.read(2) != b'MZ':
            raise ValueError('预置原生窗口不是 Windows 程序')
    if config.read_bytes() != (ROOT / 'native' / 'NativeCompanion.exe.config').read_bytes():
        raise ValueError('原生窗口运行配置与当前源码不一致')
    digest = hashlib.sha256(helper.read_bytes()).hexdigest()
    if expected_helper is not None and digest != hashlib.sha256(Path(expected_helper).read_bytes()).hexdigest():
        raise ValueError('发行程序中的原生窗口与本次编译结果不一致')
    return {'helper': helper, 'config': config, 'sha256': digest}


def desktop_command(output, work, helper):
    helper = Path(helper)
    return [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onedir', '--windowed', '--noupx',
            '--contents-directory', '_internal', '--name', '灯火', '--distpath', str(output),
            '--workpath', str(work), '--specpath', str(work),
            '--add-data', str(ROOT / 'data') + ';data', '--add-data', str(ROOT / 'web') + ';web',
            '--add-binary', str(helper) + ';native',
            '--add-data', str(helper.with_suffix('.exe.config')) + ';native',
            '--hidden-import', 'pystray._win32', '--icon', str(ROOT / 'data/lamp.ico'),
            '--copy-metadata', 'pystray', '--copy-metadata', 'Pillow', str(ROOT / 'desktop.pyw')]


def build(references, compiler=None):
    # Builder-only references and compiler never become player prerequisites.
    helper = build_native(references, compiler=compiler)
    output = ROOT / 'dist' / ('desktop-' + str(time.time_ns()))
    work = ROOT / '.local' / 'desktop-work' / output.name
    subprocess.run(desktop_command(output, work, helper), cwd=ROOT, check=True)
    application = output / '灯火'
    native_resources(application, helper)
    print(application / '灯火.exe')
    return application


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--references', type=Path, required=True, help='verified Framework 4.0 reference assemblies')
    parser.add_argument('--compiler', type=Path)
    args = parser.parse_args()
    build(args.references, args.compiler)
