"""Publish one verified installer to the existing, separately configured HTTPS route."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from companion import __version__
from companion.updates import MAX_INSTALLER, UPDATE_BASE, validate_manifest


def manifest_for(installer, version, notes=''):
    path = Path(installer)
    if path.name not in (f'灯火安装-{version}.exe', f'denghuo-setup-{version}.exe'):
        raise ValueError('Installer filename must match the version being published')
    if path.is_symlink() or not path.is_file() or not 1 <= path.stat().st_size <= MAX_INSTALLER:
        raise ValueError('Expected a regular installer of at most 256 MiB')
    with path.open('rb') as stream:
        if stream.read(2) != b'MZ':
            raise ValueError('Expected a Windows installer')
    raw = {'format': 1, 'application': 'denghuo', 'version': version, 'notes': notes,
           'installer': {'filename': 'Denghuo-Setup.exe', 'size': path.stat().st_size,
                         'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}}
    validate_manifest(raw)
    return raw


IDENTITY_PROBE = '''set -eu
token=$(curl --connect-timeout 3 --max-time 5 -fsS -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' http://169.254.169.254/latest/api/token)
curl --connect-timeout 3 --max-time 5 -fsS -H "X-aws-ec2-metadata-token: $token" http://169.254.169.254/latest/dynamic/instance-identity/document | python3 -c 'import json,sys; d=json.load(sys.stdin); print(json.dumps({k:d[k] for k in ["instanceId","region","architecture"]}))'
'''


def ssh(host, script):
    return subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                           '-o', 'ConnectTimeout=15', host, 'bash -s'],
                          input=script.replace('\r\n', '\n').encode('utf-8'), check=True,
                          capture_output=True, timeout=60).stdout.decode('utf-8')


def publish(installer, manifest, host, expected_instance):
    if not re.fullmatch('[A-Za-z0-9][A-Za-z0-9.-]{0,100}', host) or not re.fullmatch('i-[a-f0-9]{8,17}', expected_instance):
        raise ValueError('Use an existing SSH alias and exact expected EC2 instance id')
    identity = json.loads(ssh(host, IDENTITY_PROBE))
    if identity['instanceId'] != expected_instance:
        raise ValueError('SSH destination does not match the expected EC2 instance')
    # A fixed per-application directory isolates retention from every other service.
    # The nonce is generated here, never supplied by a manifest or shell user input.
    upload = '/tmp/denghuo-publish-' + uuid.uuid4().hex
    remote_guard = '''set -eu
test ! -L /srv/denghuo-updates
if test -d /srv/denghuo-updates; then
  test -z "$(find /srv/denghuo-updates -mindepth 1 -maxdepth 1 ! -name latest.json ! -name Denghuo-Setup.exe -print -quit)"
  test ! -L /srv/denghuo-updates/latest.json
  test ! -L /srv/denghuo-updates/Denghuo-Setup.exe
fi
'''
    ssh(host, remote_guard + f"test $(df --output=avail -B1 /srv | tail -1) -gt {manifest['installer']['size'] + 33554432}\n")
    try:
        with tempfile.TemporaryDirectory(prefix='denghuo-publish-') as local:
            metadata = Path(local) / 'latest.json'
            metadata.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
            for path, suffix in ((Path(installer).resolve(), '.exe'), (metadata, '.json')):
                subprocess.run(['scp', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                                str(path), host + ':' + upload + suffix], check=True)
        # Server-side serialization avoids mixed publisher races. The installer is replaced
        # first; a reader crossing this short boundary fails its hash check and can retry.
        promote = remote_guard + f'''exec 9>/tmp/denghuo-publish.lock
flock -w 15 9
python3 - {upload}.json <<'PY'
import json,pathlib,sys
candidate=json.loads(pathlib.Path(sys.argv[1]).read_text())
current=pathlib.Path('/srv/denghuo-updates/latest.json')
if current.exists():
    previous=json.loads(current.read_text())
    assert previous.get('application')=='denghuo', 'Existing manifest belongs to another application'
    assert tuple(map(int,candidate['version'].split('.'))) >= tuple(map(int,previous['version'].split('.'))), 'Refusing version rollback'
    if candidate['version']==previous['version']:
        assert candidate['installer']==previous['installer'], 'Same version must retain identical installer bytes'
PY
test "$(sha256sum {upload}.exe | cut -d ' ' -f 1)" = {manifest['installer']['sha256']}
test "$(stat -c %s {upload}.exe)" -eq {manifest['installer']['size']}
sudo -n install -d -m 755 /srv/denghuo-updates
sudo -n chown root:root {upload}.exe {upload}.json
sudo -n chmod 644 {upload}.exe {upload}.json
sudo -n mv -T {upload}.exe /srv/denghuo-updates/Denghuo-Setup.exe
sudo -n mv -T {upload}.json /srv/denghuo-updates/latest.json
sha256sum /srv/denghuo-updates/Denghuo-Setup.exe
find /srv/denghuo-updates -maxdepth 1 -type f -printf '%f %s bytes\\n'
'''
        receipt = ssh(host, promote)
        return {'identity': identity, 'manifest_url': UPDATE_BASE+'latest.json',
                'version': manifest['version'], 'sha256': manifest['installer']['sha256'],
                'server_receipt': receipt}
    finally:
        # Only the two exact uploads owned by this call; never traverse shared storage.
        ssh(host, f'set -eu\nsudo -n rm -f -- {upload}.exe {upload}.json\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('installer', type=Path)
    parser.add_argument('--version', default=__version__)
    parser.add_argument('--notes', default='')
    parser.add_argument('--manifest', type=Path, help='Write a local manifest without deploying')
    parser.add_argument('--host', help='Existing SSH alias; never pass a private key')
    parser.add_argument('--expected-instance', help='Verified EC2 instance id')
    args = parser.parse_args()
    manifest = manifest_for(args.installer, args.version, args.notes)
    if args.manifest:
        with args.manifest.open('x', encoding='utf-8') as output:
            json.dump(manifest, output, ensure_ascii=False, indent=2)
    if args.host:
        if not args.expected_instance:
            parser.error('--host requires --expected-instance')
        print(json.dumps(publish(args.installer, manifest, args.host, args.expected_instance), ensure_ascii=False))
    elif not args.manifest:
        parser.error('Choose a local --manifest or an explicitly authorized --host deployment')


if __name__ == '__main__':
    main()
