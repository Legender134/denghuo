"""Compile the local installer from an already verified frozen directory."""
import argparse
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from companion import __version__

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('application',type=Path)
    parser.add_argument('--compiler',type=Path,required=True)
    args=parser.parse_args()
    app=args.application.resolve()
    if not (app/'灯火.exe').is_file():raise SystemExit('Missing frozen application')
    subprocess.run([str(args.compiler),'/DAppDir='+str(app),'/DOutputDir='+str(ROOT/'dist'),
                    '/DAppVersion='+__version__,str(ROOT/'tools/installer.iss')],check=True,cwd=ROOT)
