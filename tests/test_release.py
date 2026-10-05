import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from tools.build_release import FILES, build_release


class ReleaseTests(unittest.TestCase):
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
