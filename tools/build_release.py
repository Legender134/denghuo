"""Build the same local source ZIP from the same explicit set of file bytes."""

import hashlib
import json
from pathlib import Path
import stat
import sys
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from companion import __version__


# Deliberate allowlist: never include save data, local preferences, logs or research.
FILES = (
    "README.md", "BUILD.md", "CONTRIBUTING.md", "CHANGELOG.md", ".gitignore", ".github/workflows/ci.yml", "THIRD_PARTY_NOTICES.md", "LICENSE.txt", "launch.pyw", "启动灯火助手.cmd", "desktop.pyw", "requirements-desktop.txt",
    "companion/__init__.py", "companion/__main__.py", "companion/diagnostics.py", "companion/panel.py", "companion/hotkeys.py", "companion/game_math.py",
    "companion/engine.py", "companion/overlay.py", "companion/play_state.py", "companion/play_overlay.py", "companion/play_settings.py", "companion/quick_reference.py", "companion/windows.py", "companion/saves.py", "companion/paths.py", "companion/tray.py", "data/lamp.ico", "data/lamp.png",
    "companion/knowledge.py", "companion/knowledge_search.py", "companion/decisions.py", "companion/support.py", "companion/workspace_service.py", "companion/values_resources.py", "companion/reference_sources.py", "companion/backup_workflows.py",
    "companion/server.py", "companion/service.py", "companion/backups.py", "companion/backup_archive.py", "companion/rules.py", "companion/values.py", "companion/values_data.py", "companion/values_abilities.py", "companion/values_decisions.py", "data/catalog.json", "data/numeric_rules.json",
    "web/index.html", "web/style.css", "web/app.js", "web/backups.js", "web/rules.js", "web/compare.js", "web/workspace.js", "web/help.js", "web/play.js", "web/backup-workflows.js", "web/icon.svg",
    "tools/build_catalog.py", "tools/numeric_catalog.py", "tools/build_numeric_rules.py", "tools/build_release.py", "tools/smoke_runtime.py",
    "tools/verify_release.py", "tools/verify_rules.py", "tools/build_desktop.py", "tools/build_brand.py", "tools/verify_desktop.py", "tools/installer.iss", "tools/build_installer.py", "tools/package_desktop.py", "tests/test_companion.py", "tests/test_startup.py", "tests/test_paths.py",
    "tests/test_overlay.py", "tests/test_play_state.py", "tests/test_play_overlay.py", "tests/test_quick_reference.py", "tests/test_release.py", "tests/test_backups.py", "tests/test_rules.py", "tests/test_values.py", "tests/test_panel.py", "tests/test_hotkeys.py", "tests/test_workspace.py", "tests/test_native_workspace.py", "tests/test_backup_workflows.py", "tests/test_mature_context.py", "tools/verify_frontend.js",
    "companion/game_process.py",
    "companion/session_exit.py",
    "companion/values_investment.py",
    "companion/native_host.py",
    "companion/native_workspace.py",
    "companion/native_settings.py",
    "companion/native_manager.py",
    "companion/native_focus.py",
    "companion/migration.py",
    "companion/alchemy.py",
    "native/NativeCompanion.cs",
    "native/NativeCompanion.manifest",
    "native/NativeCompanion.exe.config",
    "tools/build_native_helper.py",
    "web/migration.js",
    "web/alchemy.js",
    "tests/test_session_exit.py",
    "tests/test_game_process.py",
    "tests/test_native_controllers.py",
    "tests/test_native_exit_controls.py",
    "tests/test_native_packaging.py",
    "tests/test_migration.py",
    "tests/test_alchemy.py",
    "tools/alchemy_catalog.py",
    "companion/alchemy_flow.py",
    "companion/character_scene.py",
    "companion/character_comparison.py",
    "companion/public_item_levels.py",
    "companion/public_item_state.py",
    "companion/public_source_data.py",
    "companion/public_talents.py",
    "web/character.js",
    "tests/test_alchemy_flow.py",
    "tests/test_character_comparison.py",
    "tests/test_character_scene.py",
    "tests/test_food_equipment_context.py",
    "tests/test_public_alchemy_state.py",
    "tests/test_public_item_levels.py",
    "tests/test_service_r8_workflows.py",
    "tests/test_workspace_concurrency.py",
    "tests/verify_data_workflows.js",
    "tools/verify_web_exit_receipt.js",
    "tools/verify_workspace_concurrency.js",
    "tools/verify_alchemy_workflow.js",
)
STAMP = (2026, 10, 2, 0, 0, 0)


def file_bytes(root, relative):
    path = root / relative
    for part in (path, *path.parents):
        if part == root:
            break
        attrs = part.lstat()
        if part.is_symlink() or getattr(attrs, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError(f"Refusing linked release input: {relative}")
    if not path.resolve().is_relative_to(root):
        raise ValueError(f"Release input escaped the project: {relative}")
    return path.read_bytes()


def build_release(root=ROOT, output=None):
    root = Path(root).resolve()
    output = Path(output) if output is not None else root / "dist"
    payloads = {name: file_bytes(root, name) for name in sorted(FILES)}
    manifest = {
        "format": 1, "version": __version__,
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()},
    }
    payloads["MANIFEST.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    output.mkdir(parents=True, exist_ok=True)
    stem = f"denghuo-{__version__}"
    target = output / f"{stem}.zip"
    pending = target.with_suffix(".zip.tmp")
    with ZipFile(pending, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(payloads.items()):
            entry = ZipInfo(f"{stem}/{name}", STAMP)
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = ZIP_DEFLATED
            archive.writestr(entry, data, compresslevel=9)
    digest = hashlib.sha256(pending.read_bytes()).hexdigest()
    pending.replace(target)
    target.with_suffix(".zip.sha256").write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    return target, digest


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    archive, digest = build_release()
    print(f"{archive}\nSHA-256 {digest}")
