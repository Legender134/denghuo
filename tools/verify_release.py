"""Verify a local release's hashes, extracted tests and real HTTP lifecycle."""

import argparse
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
from zipfile import ZipFile

from build_release import FILES, ROOT, __version__


def verify(archive):
    archive = Path(archive).resolve()
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    expected = archive.with_suffix(".zip.sha256").read_text(encoding="utf-8").split()[0]
    if digest != expected:
        raise ValueError("ZIP checksum mismatch")
    prefix = archive.stem + "/"
    local = ROOT / ".local"
    local.mkdir(exist_ok=True)
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PYTHONIOENCODING"] = "utf-8"
    # Windows users commonly extract to folders containing Chinese and spaces.
    with tempfile.TemporaryDirectory(prefix="release-verification-中文 空格-", dir=local) as folder:
        folder = Path(folder).resolve()
        assert folder.is_relative_to(local.resolve())
        with ZipFile(archive) as package:
            names = package.namelist()
            required = {prefix + name for name in (*FILES, "MANIFEST.json")}
            if len(names) != len(required) or set(names) != required:
                raise ValueError("Unexpected or missing release files")
            manifest = json.loads(package.read(prefix + "MANIFEST.json"))
            if set(manifest["files"]) != set(FILES):
                raise ValueError("Manifest file list mismatch")
            for name, expected in manifest["files"].items():
                if hashlib.sha256(package.read(prefix + name)).hexdigest() != expected:
                    raise ValueError(f"File checksum mismatch: {name}")
            package.extractall(folder)
        root = folder / archive.stem
        result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                                cwd=root, env=env, capture_output=True, timeout=300, encoding="utf-8", errors="replace")
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        test_summary = result.stderr.strip().splitlines()[-3:]
        print("PASS: extracted package tests; " + " ".join(test_summary))
        # Confirm the delivered build tool needs no excluded development files.
        rebuilt = subprocess.run([sys.executable, "tools/build_release.py"], cwd=root, env=env,
                                 capture_output=True, timeout=15, encoding="utf-8", errors="replace")
        if rebuilt.returncode:
            raise RuntimeError(rebuilt.stderr)
        if hashlib.sha256((root / "dist" / archive.name).read_bytes()).hexdigest() != digest:
            raise ValueError("Extracted package did not reproduce the original ZIP")
        print("PASS: extracted sources reproduce the identical ZIP")
        config = root / ".local" / "verification.json"
        config.parent.mkdir(exist_ok=True)
        (root / "empty-test-saves").mkdir()
        config.write_text(json.dumps({"save_root": str(root / "empty-test-saves")}), encoding="utf-8")
        stop_at = (datetime.now(timezone.utc) + timedelta(seconds=15)).isoformat()
        process = subprocess.Popen([sys.executable, str(root / "launch.pyw"), "--no-overlay", "--no-browser",
                                    "--config", str(config), "--stop-at", stop_at], cwd=folder, env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            record = config.with_suffix(".runtime.json")
            deadline = time.monotonic() + 6
            while not record.exists() and time.monotonic() < deadline and process.poll() is None:
                time.sleep(.05)
            if not record.exists():
                raise RuntimeError("Extracted launcher failed to start")
            info = json.loads(record.read_text(encoding="utf-8"))
            with urlopen(info["url"] + "api/status", timeout=3) as response:
                state = json.load(response)
            expected_count = len(json.loads((root / "data/catalog.json").read_text(encoding="utf-8"))["entries"])
            assert state["catalog_count"] == expected_count and state["settings"]["save_root"] == str(root / "empty-test-saves")
            with urlopen(info["url"], timeout=3) as response:
                assert "灯火" in response.read().decode("utf-8")
            with urlopen(info["url"] + "api/library?q=Snake", timeout=3) as response:
                assert json.load(response)["total"] > 0
            with urlopen(info["url"] + "api/rules?offset=40", timeout=5) as response:
                rules = json.load(response)
                assert rules["total"] == 2069 and rules["coverage"]["uncovered_literals"] == 0
            with urlopen(info["url"] + "api/values?id=items.weapon.melee.sword&level=20", timeout=5) as response:
                detail = json.load(response)
                table = next(t for t in detail["blocks"] if t["title"] == "装备等级数值表")
                assert table["rows"][-1] == ["20", "23", "100"] and 'sections' not in detail
            with urlopen(info["url"] + "api/values?id=items.potions.potionofhealing&max_hp=100&hp=10", timeout=5) as response:
                detail=json.load(response)
                values={v['label']:v['value'] for b in detail['blocks'] for v in b.get('values',[])}
                assert values['最终实际恢复']=='90' and values['首次恢复']=='24'
            request = Request(info["url"] + "api/shutdown", data=b"{}", method="POST",
                              headers={"Content-Type": "application/json", "X-Companion-Token": state["token"],
                                       "Origin": info["url"].rstrip("/")})
            with urlopen(request, timeout=3) as response:
                assert response.status == 200
            _, errors = process.communicate(timeout=8)
            if process.returncode:
                raise RuntimeError(errors.decode(errors="replace"))
        finally:
            if process.poll() is None:
                process.terminate()
                process.communicate(timeout=8)
        print("PASS: desktop entrypoint from a Chinese/spaced path and different working directory; dashboard, catalog, shutdown")
    report = {"archive": archive.name, "sha256": digest, "version": manifest["version"],
              "verified_at": datetime.now(timezone.utc).isoformat(), "file_count": len(FILES),
              "tests": test_summary, "reproducible": True, "startup_shutdown": True,
              "unicode_space_path": True, "different_working_directory": True, "player_numeric_values": True}
    (local / "release-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, nargs="?", default=ROOT / "dist" / f"denghuo-{__version__}.zip")
    args = parser.parse_args()
    print(json.dumps(verify(args.archive), ensure_ascii=False, indent=2))
