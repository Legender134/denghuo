"""Build a self-contained Windows directory with an explicit data allowlist."""
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def build():
    output = ROOT/'dist'/('desktop-'+str(time.time_ns()))
    work = ROOT/'.local'/'desktop-work'/output.name
    subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--windowed','--noupx',
                    '--name','灯火','--distpath',str(output),'--workpath',str(work),
                    '--specpath',str(work), '--add-data',str(ROOT/'data')+';data',
                    '--add-data',str(ROOT/'web')+';web','--hidden-import','pystray._win32',
                    '--icon',str(ROOT/'data/lamp.ico'), '--copy-metadata','pystray', '--copy-metadata','Pillow',
                    str(ROOT/'desktop.pyw')],cwd=ROOT,check=True)
    print(output/'灯火'/'灯火.exe')
    return output/'灯火'


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    build()
