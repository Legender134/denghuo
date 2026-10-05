"""Exercise real process startup/deadline and single-instance behavior locally."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    local = ROOT / ".local"
    local.mkdir(exist_ok=True)
    runtime = local / "runtime.json"
    before = runtime.read_bytes() if runtime.exists() else None
    with tempfile.TemporaryDirectory(prefix="runtime-test-", dir=local) as folder:
        test_root = Path(folder).resolve()
        assert test_root.is_relative_to(local.resolve())
        config = test_root / "session.json"
        config.write_text(json.dumps({"save_root": str(test_root)}), encoding="utf-8")
        stop_at = (datetime.now(timezone.utc) + timedelta(seconds=4)).isoformat()
        process = subprocess.Popen([sys.executable, "-m", "companion", "--no-overlay", "--no-browser",
                                    "--config", str(config), "--stop-at", stop_at], cwd=ROOT,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        record = config.with_suffix(".runtime.json")
        deadline = time.monotonic() + 3
        while not record.exists() and time.monotonic() < deadline and process.poll() is None:
            time.sleep(.05)
        assert record.exists(), "Headless service failed to start"
        info = json.loads(record.read_text())
        with urlopen(info["url"] + "api/status", timeout=2) as response:
            state = json.load(response)
        assert state["settings"]["stop_at"], "Deadline was not configured"
        out, err = process.communicate(timeout=8)
        assert process.returncode == 0, err.decode(errors="replace")
        print("PASS: real HTTP startup and timed clean shutdown")
        # A bad save must not prevent opening the UI or healing on a later save.
        save_root = test_root / 'broken-saves'
        save = save_root / 'game1' / 'game.dat'
        save.parent.mkdir(parents=True)
        game = {'depth':4, 'branch':0, 'version':912, 'hero':{'class':'WARRIOR','HP':20,'HT':30,
                'STR':10**1000, 'lvl':5, 'inventory':[], 'buffs':[]}}
        save.write_text(json.dumps(game), encoding='utf-8')
        broken_config = test_root / 'broken.json'
        broken_config.write_text(json.dumps({'save_root':str(save_root),'slot':'auto'}), encoding='utf-8')
        failsafe = (datetime.now(timezone.utc) + timedelta(seconds=15)).isoformat()
        process = subprocess.Popen([sys.executable, '-m', 'companion', '--no-overlay', '--no-browser',
                                    '--config', str(broken_config), '--stop-at', failsafe], cwd=ROOT,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            record = broken_config.with_suffix('.runtime.json')
            deadline = time.monotonic() + 3
            while not record.exists() and time.monotonic() < deadline and process.poll() is None:
                time.sleep(.05)
            assert record.exists(), 'Bad save prevented service startup'
            info = json.loads(record.read_text())
            with urlopen(info['url']+'api/status',timeout=2) as response:
                state=json.load(response)
            assert state['data'] is None and '超出范围' in state['error']
            assert '最近更新的槽位 1' in state['error'] and state['active_slot'] is None
            game['hero']['STR']=12
            save.write_text(json.dumps(game),encoding='utf-8')
            deadline=time.monotonic()+5
            while state['data'] is None and time.monotonic()<deadline:
                time.sleep(.25)
                with urlopen(info['url']+'api/status',timeout=2) as response:
                    state=json.load(response)
            assert state['data']['hero']['hp']==20 and state['error']=='', 'Corrected save did not recover'
            request=Request(info['url']+'api/shutdown',data=b'{}',method='POST',
                            headers={'Content-Type':'application/json','X-Companion-Token':state['token'],
                                     'Origin':info['url'].rstrip('/')})
            with urlopen(request,timeout=2) as response:
                assert response.status==200
            _,err=process.communicate(timeout=5)
            assert process.returncode==0,err.decode(errors='replace')
            print('PASS: bad-save startup remains usable and a corrected save recovers automatically')
        finally:
            if process.poll() is None:
                process.terminate();process.communicate(timeout=5)
    if before:
        assert runtime.read_bytes() == before, "Isolated CLI test overwrote live runtime metadata"
        if os.name == "nt":
            info = json.loads(before)
            try:
                with urlopen(info["url"] + "api/status", timeout=2) as response:
                    assert response.status == 200
            except OSError:
                print("SKIP: existing instance is not running")
            else:
                result = subprocess.run([sys.executable, "-m", "companion", "--no-browser"], cwd=ROOT,
                                        capture_output=True, timeout=5)
                assert result.returncode == 0, result.stderr.decode(errors="replace")
                assert runtime.read_bytes() == before
                print("PASS: duplicate launch exits without replacing the live service")
                result = subprocess.run([sys.executable, str(ROOT/'launch.pyw'), '--no-browser'], cwd=ROOT,
                                        capture_output=True, timeout=5)
                assert result.returncode == 0, result.stderr.decode(errors='replace')
                assert runtime.read_bytes() == before
                print('PASS: desktop Python entrypoint reuses the live service')


if __name__ == "__main__":
    main()
