"""Rebuild the shipped, GPL-licensed offline scout from its exact source archive.

Requires Rust 1.99.0 and wasm32-unknown-unknown. Cargo fetches the versions in
Cargo.lock when they are not already cached. No game or personal files are read.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'third_party/seed_seeker'


def extract(directory):
    receipt = json.loads((SOURCE/'source.json').read_text(encoding='utf-8'))
    archive = (SOURCE/'engine-source.zip').read_bytes()
    if hashlib.sha256(archive).hexdigest() != receipt['source_archive_sha256']:
        raise ValueError('Forecast source archive checksum mismatch')
    expected = {row['path']: row['sha256'] for row in receipt['source_files']}
    with zipfile.ZipFile(SOURCE/'engine-source.zip') as bundle:
        if len(bundle.infolist()) != len(expected) or sum(row.file_size for row in bundle.infolist()) > 64*1024*1024:
            raise ValueError('Invalid forecast source archive bounds')
        seen = set()
        for row in bundle.infolist():
            path = PurePosixPath(row.filename)
            if (row.filename not in expected or row.filename in seen or path.is_absolute()
                    or '..' in path.parts or '\\' in row.filename or row.is_dir()
                    or (row.external_attr >> 16) & 0o170000 != 0o100000):
                raise ValueError('Unexpected forecast source member')
            raw = bundle.read(row)
            if hashlib.sha256(raw).hexdigest() != expected[row.filename]:
                raise ValueError('Forecast source file checksum mismatch')
            target = directory.joinpath(*path.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            seen.add(row.filename)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Write a candidate WASM here; default only verifies against the shipped hash')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='denghuo-forecast-') as temporary:
        directory = Path(temporary)
        receipt = extract(directory)
        env = dict(os.environ)
        env['CARGO_TARGET_WASM32_UNKNOWN_UNKNOWN_RUSTFLAGS'] = '-Clink-arg=--max-memory=134217728'
        subprocess.run(['cargo', 'build', '--release', '--locked', '-p', 'denghuo-forecast', '--target', 'wasm32-unknown-unknown'],
                       cwd=directory, env=env, check=True)
        output = directory/'target/wasm32-unknown-unknown/release/denghuo_forecast.wasm'
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        if args.output:
            if args.output.exists():
                raise ValueError('Output already exists; choose a new candidate filename')
            args.output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(output, args.output)
        elif digest != receipt['wasm_sha256']:
            raise ValueError('Rebuild differs from shipped WASM; inspect a separately named --output candidate')
        print(json.dumps({'sha256': digest, 'matches_shipped': digest == receipt['wasm_sha256'], 'bytes': output.stat().st_size}))


if __name__ == '__main__':
    main()
