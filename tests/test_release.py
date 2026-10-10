import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from tools.build_release import FILES, build_release


class ReleaseTests(unittest.TestCase):
    def test_source_archive_contains_the_complete_regression_suite(self):
        tests = Path(__file__).resolve().parent
        expected = {'tests/' + path.name for pattern in ('test_*.py', 'verify_*.js')
                    for path in tests.glob(pattern)}
        self.assertEqual({name for name in FILES if name.startswith('tests/')}, expected)

    def test_cli_unicode_path_works_with_legacy_pipe_encoding(self):
        script = Path(__file__).resolve().parents[1] / "tools/build_release.py"
        with tempfile.TemporaryDirectory(prefix="lamp-cli-中文 空格-") as folder:
            root = Path(folder)
            for name in FILES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(("controlled release file " + name).encode("utf-8"))
            (root / "tools/build_release.py").write_bytes(script.read_bytes())
            (root / "companion/__init__.py").write_text('__version__ = "0.3.0"\n', encoding="utf-8")
            env = dict(os.environ, PYTHONIOENCODING="cp1252:strict", PYTHONUTF8="0")
            env.pop("PYTHONPATH", None)
            result = subprocess.run([sys.executable, str(root / "tools/build_release.py")],
                                    cwd=root, env=env, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", errors="replace"))
            self.assertIn(str(root.resolve()), result.stdout.decode("utf-8"))
            self.assertTrue((root / "dist/denghuo-0.3.0.zip").is_file())

    def test_reproducible_allowlisted_archive_and_checksums(self):
        with tempfile.TemporaryDirectory(prefix="lamp-release-test-") as folder:
            root = Path(folder)
            for name in FILES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(("release file " + name).encode("utf-8"))
            for name in (".local/settings.json", ".local/private.dat", ".research/upstream/private.txt", "DEVELOPMENT.md"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("DO NOT PACKAGE")
            first, digest = build_release(root, root / "one")
            second, second_digest = build_release(root, root / "two")
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(digest, second_digest)
            self.assertEqual(first.with_suffix(".zip.sha256").read_text().split()[0], digest)
            with ZipFile(first) as archive:
                prefix = first.stem + "/"
                self.assertEqual(set(archive.namelist()), {prefix + name for name in (*FILES, "MANIFEST.json")})
                manifest = json.loads(archive.read(prefix + "MANIFEST.json"))
                for name, expected in manifest["files"].items():
                    self.assertEqual(hashlib.sha256(archive.read(prefix + name)).hexdigest(), expected)

    def test_missing_required_file_does_not_replace_existing_package(self):
        with tempfile.TemporaryDirectory(prefix="lamp-release-test-") as folder:
            root = Path(folder)
            output = root / "dist"
            output.mkdir()
            marker = output / "keep.zip"
            marker.write_bytes(b"existing package")
            with self.assertRaises(FileNotFoundError):
                build_release(root, output)
            self.assertEqual(marker.read_bytes(), b"existing package")
            self.assertEqual(list(output.iterdir()), [marker])

    def test_linked_source_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="lamp-release-test-") as folder:
            root = Path(folder)
            (root / "README.md").write_text("placeholder")
            with patch("tools.build_release.FILES", ("README.md",)):
                with patch.object(Path, "is_symlink", return_value=True):
                    with self.assertRaisesRegex(ValueError, "linked release input"):
                        build_release(root)


if __name__ == "__main__":
    unittest.main()
