import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED

from companion.backups import BackupManager, NODES, snapshot_identity, game_closed, unlinked, atomic_json
from companion.engine import Catalog
from companion.saves import open_save


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="denghuo-backup-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "游戏存档"
        self.root.mkdir()
        self.clock = 10000
        self.manager = BackupManager(Path(self.temporary.name) / "backups", clock=lambda: self.clock,
                                     closed_check=lambda: None)
        self.write_save()

    def write_save(self, hp=20, slot=1, branch=0):
        folder = self.root / f"game{slot}"
        folder.mkdir(exist_ok=True)
        game = {"depth": 2, "branch": branch, "version": 912, "seed": 9,"generated_levels":[2+1000*branch],
                "hero": {"class": "MAGE", "HP": hp, "HT": 30, "STR": 10, "lvl": 2, "inventory": [], "buffs": []}}
        (folder / "game.dat").write_bytes(gzip.compress(json.dumps(game).encode()))
        floor = "depth2" + (f"-branch{branch}" if branch else "") + ".dat"
        level={'__className':'com.shatteredpixel.shatteredpixeldungeon.levels.SewerLevel','version':912,'width':4,'height':4,
               'map':[4]*16,'visited':[False]*16,'mapped':[False]*16}
        (folder / floor).write_bytes(gzip.compress(json.dumps({'level':level}).encode()))
        stamp = 1700000000 + hp
        os.utime(folder / "game.dat", (stamp, stamp))
        os.utime(folder / floor, (stamp, stamp))
        return folder

    def payload(self, row):
        return {"slot": row["slot"], "id": row["id"], "confirm": f"恢复槽位 {row['slot']}"}

    def manage(self, root, payload):
        # Existing lifecycle cases submit the version actually read by this editor.
        current = self.manager.selected(root, payload)
        self.manager.manage(root, {**payload, 'expected_metadata_revision': current['metadata_revision']})

    def test_metadata_cas_rejects_old_unlock_and_aba_but_ignores_observations(self):
        row = self.manager.capture(self.root, 1)
        selected = {'slot': 1, 'id': row['id']}
        original = self.manager.selected(self.root, selected)['metadata_revision']
        self.manager.manage(self.root, {**selected, 'label': '永久保留', 'locked': True,
                                       'expected_metadata_revision': original})
        with self.assertRaisesRegex(ValueError, '已变化'):
            self.manager.manage(self.root, {**selected, 'label': '旧窗口输入', 'locked': False,
                                           'expected_metadata_revision': original})
        fixed = self.manager.selected(self.root, selected)
        self.assertEqual((fixed['label'], fixed['locked']), ('永久保留', True))
        revision = fixed['metadata_revision']
        self.clock += 20
        self.manager.capture(self.root, 1)
        self.assertEqual(self.manager.selected(self.root, selected)['metadata_revision'], revision)
        self.manager.manage(self.root, {**selected, 'label': '', 'locked': False,
                                       'expected_metadata_revision': revision})
        self.assertNotEqual(self.manager.selected(self.root, selected)['metadata_revision'], original)
        with self.assertRaisesRegex(ValueError, '已变化'):
            self.manager.manage(self.root, {**selected, 'locked': False,
                                           'expected_metadata_revision': original})
        with self.assertRaisesRegex(ValueError, '已变化'):
            self.manager.manage(self.root, {**selected, 'locked': False})

    def test_metadata_receipt_belongs_to_its_write_and_cannot_unlock_a_later_write(self):
        row = self.manager.capture(self.root, 1)
        selected = {'slot': 1, 'id': row['id']}
        original = self.manager.selected(self.root, selected)
        receipt = self.manager.manage(self.root, {**selected, 'label': '  提交名称  ', 'locked': False,
            'expected_metadata_revision': original['metadata_revision']})
        self.assertEqual(receipt['label'], '提交名称')
        self.manager.manage(self.root, {**selected, 'label': '另一窗口', 'locked': True,
            'expected_metadata_revision': receipt['metadata_revision']})
        self.assertEqual(receipt['label'], '提交名称')
        self.assertFalse(receipt['locked'])
        with self.assertRaisesRegex(ValueError, '已变化'):
            self.manager.manage(self.root, {**selected, 'label': '继续输入', 'locked': False,
                'expected_metadata_revision': receipt['metadata_revision']})
        self.assertTrue(self.manager.selected(self.root, selected)['locked'])

    def test_discovered_legacy_backup_exposes_editable_metadata_version(self):
        row = self.manager.capture(self.root, 1)
        (self.manager.scope(self.root) / 'history.json').unlink()
        reloaded = BackupManager(self.manager.directory, closed_check=lambda: None)
        discovered = reloaded.history(self.root)[0]
        self.assertEqual(discovered['id'], row['id'])
        self.assertEqual(len(discovered['metadata_revision']), 64)
        reloaded.manage(self.root, {**discovered, 'label': '发现的原件',
                                   'expected_metadata_revision': discovered['metadata_revision']})

    def test_game_replacement_during_backup_read_is_allowed_and_rejected_as_unstable(self):
        path = (self.root / 'game1' / 'game.dat').resolve()
        old = json.loads(gzip.decompress(path.read_bytes()))
        old['hero']['HP'] = 19
        new = gzip.compress(json.dumps(old).encode())
        replacement = path.with_suffix('.spdtmp')
        replacement.write_bytes(new)
        injected = []
        def interleaved(file):
            stream = open_save(file)
            if file == path:
                injected.append(file)
                try:
                    file.unlink()
                    replacement.replace(file)
                except BaseException:
                    stream.close()
                    raise
            return stream
        with patch('companion.backups.open_save', side_effect=interleaved):
            with self.assertRaisesRegex(ValueError, '正在保存'):
                self.manager.capture(self.root, 1)
        self.assertEqual(injected, [path])
        self.assertEqual(path.read_bytes(), new)
        self.assertFalse(list(self.manager.directory.rglob('*.zip')))
        self.write_save(hp=19)
        row = self.manager.capture(self.root, 1)
        self.assertTrue(self.manager.checked_archive(self.root, row['id'], 1))

    def test_game_closed_check_uses_windows_system_tool_and_fails_closed(self):
        from types import SimpleNamespace
        import subprocess
        with (patch.object(subprocess, 'CREATE_NO_WINDOW', getattr(subprocess, 'CREATE_NO_WINDOW', 0), create=True),
              patch('companion.backups.sys.platform','win32'),patch('companion.game_process.game_window_pids',return_value=set()),patch.dict(os.environ,{'SystemRoot':'C:\\Windows','PATH':'C:\\Windows\\System32'})):
            with patch('companion.backups.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps({'schema':1,'ok':True,'candidates':[]}))) as execute:
                game_closed()
                expected = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
                self.assertEqual(Path(execute.call_args.args[0][0]), expected)
                self.assertEqual(execute.call_args.kwargs['creationflags'], subprocess.CREATE_NO_WINDOW)
            for response in (SimpleNamespace(returncode=1,stdout=''),SimpleNamespace(returncode=0,stdout='"java.exe"')):
                with patch('companion.backups.subprocess.run',return_value=response),self.assertRaises(ValueError):game_closed()
            with patch('companion.backups.subprocess.run',side_effect=subprocess.TimeoutExpired('controlled',10)),self.assertRaises(ValueError):game_closed()

    def test_dangling_links_are_rejected_before_any_management_write(self):
        missing=Path(self.temporary.name)/'missing-target.json'
        link=Path(self.temporary.name)/'settings.pending'
        try:link.symlink_to(missing)
        except OSError as exc:self.skipTest(f'Host cannot create a controlled symlink: {exc}')
        self.assertFalse(link.exists())
        with self.assertRaisesRegex(ValueError,'链接'):unlinked(link)
        with self.assertRaisesRegex(ValueError,'链接'):atomic_json(link,{'controlled':True})
        self.assertFalse(missing.exists())

    def test_link_attributes_are_checked_even_when_exists_returns_false(self):
        from types import SimpleNamespace
        import stat
        with patch.object(Path,'exists',return_value=False),patch.object(Path,'lstat',return_value=SimpleNamespace(st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)),patch.object(Path,'is_symlink',return_value=True):
            with self.assertRaisesRegex(ValueError,'链接'):unlinked(self.root/'controlled-dangling-link')

    def test_health_for_selected_slot_cannot_borrow_newer_slot_save(self):
        self.clock=1700001000
        self.write_save(slot=2)
        for path in (self.root/'game2').iterdir():os.utime(path,(self.clock,self.clock))
        self.manager.tick(self.root)
        self.assertEqual(self.manager.health_status(self.root)['state'],'protected')
        self.assertEqual(self.manager.health_status(self.root,1)['state'],'waiting')
        self.assertEqual(self.manager.health_status(self.root,2)['state'],'protected')
        self.assertEqual(self.manager.health_status(self.root,1)['saved'],1700000020)

    def test_rejoin_retained_backup_validates_without_restore_or_delete(self):
        self.manager.tick(self.root);first=self.manager.events(self.root)[0]
        self.manage(self.root,{**first,'label':'首领之前','locked':False})
        original=(self.root/'game1/game.dat').read_bytes()
        self.manager.remove(self.root,{**first,'confirm':'移出备份 1'})
        retained=self.manager.retained_status(self.root)
        self.assertEqual(len(retained),1)
        self.assertEqual(retained[0]['label'],'首领之前')
        self.assertAlmostEqual(retained[0]['time'],int(Path(retained[0]['file']).stem.split('-')[1])/1e9)
        self.clock+=86400
        breakdown=self.manager.storage_breakdown(self.root)
        self.assertGreater(breakdown['retained'],0)
        self.manager.rejoin(self.root,retained[0])
        self.assertEqual((self.root/'game1/game.dat').read_bytes(),original)
        self.assertEqual(len(self.manager.retained_status(self.root)),1)
        self.assertEqual(self.manager.selected(self.root,first)['id'],first['id'])
        self.assertEqual(self.manager.selected(self.root,first)['label'],'首领之前')
        self.assertEqual(self.manager.selected(self.root,first)['time'],10000)
        self.manage(self.root,{**first,'label':'新名称','locked':False})
        self.manager.rejoin(self.root,retained[0])
        self.assertEqual(self.manager.selected(self.root,first)['label'],'新名称')
        with self.assertRaises(ValueError):self.manager.rejoin(self.root,{'file':'../settings.json'})

    def test_retained_metadata_damage_does_not_restore_or_rejoin(self):
        self.manager.tick(self.root);first=self.manager.events(self.root)[0]
        self.manager.remove(self.root,{**first,'confirm':'移出备份 1'})
        row=self.manager.retained_status(self.root)[0]
        sidecar=self.manager.directory.parent/'backup-recycle'/self.manager.scope(self.root).name/Path(row['file']).with_suffix('.json')
        sidecar.write_text('{invalid',encoding='utf-8')
        original=(self.root/'game1/game.dat').read_bytes()
        self.assertIn('metadata_error',self.manager.retained_status(self.root)[0])
        with self.assertRaisesRegex(ValueError,'名称记录损坏'):self.manager.rejoin(self.root,row)
        self.assertEqual((self.root/'game1/game.dat').read_bytes(),original)
        self.assertFalse(self.manager.history(self.root))

    def test_restore_health_waits_for_new_capture_and_counts_preserved_directory(self):
        self.manager.tick(self.root);first=self.manager.events(self.root)[0]
        self.manager.restore(self.root,self.payload(first))
        self.assertEqual(self.manager.health_status(self.root,1)['state'],'waiting')
        sizes=self.manager.storage_breakdown(self.root)
        self.assertGreater(sizes['before_restore'],0)
        self.assertEqual(sizes['total'],sum(sizes[k] for k in ('active','retained','quarantine','before_restore')))

    def test_readonly_capture_deduplicates_data_and_keeps_observation_times(self):
        before = {p.name: p.read_bytes() for p in (self.root / "game1").iterdir()}
        self.manager.tick(self.root)
        self.clock += 10
        self.manager.tick(self.root)
        rows = self.manager.events(self.root)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["id"], rows[1]["id"])
        self.assertEqual(len(list(self.manager.scope(self.root).glob("*.zip"))), 1)
        self.assertEqual(before, {p.name: p.read_bytes() for p in (self.root / "game1").iterdir()})

    def test_time_nodes_never_choose_a_newer_than_requested_backup(self):
        self.manager.tick(self.root)
        self.clock += 10
        self.write_save(hp=10)
        self.manager.tick(self.root)
        self.clock += 10
        result = self.manager.snapshot(self.root)["slots"][0]
        nodes = {r["seconds"]: r["backup"] for r in result["nodes"]}
        self.assertEqual(tuple(nodes), NODES)
        self.assertEqual(nodes[10]["time"], 10010)
        self.assertEqual(nodes[20]["time"], 10000)
        self.assertIsNone(nodes[30])

    def test_identical_slots_have_independent_restorable_archives(self):
        self.write_save(slot=2)
        # Ensure byte-for-byte identity, including gzip headers, between the slots.
        for source in (self.root/'game1').iterdir():
            (self.root/'game2'/source.name).write_bytes(source.read_bytes())
            os.utime(self.root/'game2'/source.name,ns=(source.stat().st_mtime_ns,source.stat().st_mtime_ns))
        self.manager.tick(self.root)
        rows=self.manager.events(self.root)
        self.assertEqual(len(rows),2)
        self.assertNotEqual(rows[0]['id'],rows[1]['id'])
        self.write_save(hp=2,slot=1);self.write_save(hp=3,slot=2)
        for row in rows:
            self.manager.restore(self.root,self.payload(row))
            hero=json.loads(gzip.decompress((self.root/f"game{row['slot']}"/'game.dat').read_bytes()))['hero']
            self.assertEqual(hero['HP'],20)

    def test_legacy_format_one_archives_remain_restorable(self):
        self.manager.tick(self.root)
        row=self.manager.events(self.root)[0]
        target=self.manager.scope(self.root)/(row['id']+'.zip')
        with ZipFile(target) as archive:
            metadata=json.loads(archive.read('manifest.json'))
            contents={name:archive.read(name) for name in metadata['files']}
        metadata['format']=1
        legacy=snapshot_identity(metadata['files'],row['slot'],1)
        with ZipFile(self.manager.scope(self.root)/(legacy+'.zip'),'w',ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json',json.dumps(metadata))
            for name,data in contents.items():archive.writestr(name,data)
        row['id']=legacy
        (self.manager.scope(self.root)/'timeline.json').write_text(json.dumps([row]))
        self.write_save(hp=2)
        self.manager.restore(self.root,self.payload(row))
        hero=json.loads(gzip.decompress((self.root/'game1/game.dat').read_bytes()))['hero']
        self.assertEqual(hero['HP'],20)

    def test_restore_full_folder_and_preserve_original_including_extra_files(self):
        folder = self.root / "game1"
        original = {p.name: p.read_bytes() for p in folder.iterdir()}
        timestamps = {p.name: p.stat().st_mtime_ns for p in folder.iterdir()}
        self.manager.tick(self.root)
        row = self.manager.events(self.root)[0]
        self.write_save(hp=2)
        (folder / "notes.txt").write_text("preserve this")
        (folder / "depth3.dat").write_bytes(b"later floor")
        changed = {p.name: p.read_bytes() for p in folder.iterdir()}
        self.manager.restore(self.root, self.payload(row))
        self.assertEqual(original, {p.name: p.read_bytes() for p in folder.iterdir()})
        self.assertEqual(timestamps, {p.name: p.stat().st_mtime_ns for p in folder.iterdir()})
        saved = list(self.root.glob(".denghuo-before-1-*"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(changed, {p.name: p.read_bytes() for p in saved[0].iterdir()})

    def test_restore_requires_confirmation_scope_slot_and_closed_game(self):
        self.manager.tick(self.root)
        row = self.manager.events(self.root)[0]
        before = (self.root / "game1/game.dat").read_bytes()
        bad = self.payload(row)
        bad["confirm"] = "yes"
        with self.assertRaisesRegex(ValueError, "确认"):
            self.manager.restore(self.root, bad)
        bad = self.payload(row)
        bad.update(slot=2, confirm="恢复槽位 2")
        with self.assertRaisesRegex(ValueError, "不属于"):
            self.manager.restore(self.root, bad)
        another = Path(self.temporary.name) / "other"
        another.mkdir()
        with self.assertRaisesRegex(ValueError, "不属于"):
            self.manager.restore(another, self.payload(row))
        self.manager.closed_check = lambda: (_ for _ in ()).throw(ValueError("游戏仍在运行"))
        with self.assertRaisesRegex(ValueError, "运行"):
            self.manager.restore(self.root, self.payload(row))
        self.assertEqual(before, (self.root / "game1/game.dat").read_bytes())
        self.assertFalse(list(self.root.glob(".denghuo-before-*")))

    def test_corrupt_archive_and_path_injection_are_rejected_before_game_writes(self):
        self.manager.tick(self.root)
        row = self.manager.events(self.root)[0]
        path = self.manager.scope(self.root) / (row["id"] + ".zip")
        before = (self.root / "game1/game.dat").read_bytes()
        with ZipFile(path, "a") as archive:
            archive.writestr("../escape.dat", b"malicious")
        with self.assertRaisesRegex(ValueError, "清单"):
            self.manager.restore(self.root, self.payload(row))
        path.write_bytes(b"broken zip")
        with self.assertRaisesRegex(ValueError, "校验"):
            self.manager.restore(self.root, self.payload(row))
        self.assertEqual(before, (self.root / "game1/game.dat").read_bytes())
        self.assertFalse((self.root.parent / "escape.dat").exists())

    def test_hash_mismatch_rejected(self):
        self.manager.tick(self.root)
        row = self.manager.events(self.root)[0]
        path = self.manager.scope(self.root) / (row["id"] + ".zip")
        with ZipFile(path) as archive:
            contents = {name: archive.read(name) for name in archive.namelist()}
        contents["game.dat"] = b"tampered"
        with ZipFile(path, "w", ZIP_DEFLATED) as archive:
            for name, data in contents.items():
                archive.writestr(name, data)
        with self.assertRaisesRegex(ValueError, "校验失败"):
            self.manager.restore(self.root, self.payload(row))

    def test_failed_directory_swap_rolls_back_original(self):
        self.manager.tick(self.root)
        row = self.manager.events(self.root)[0]
        self.write_save(hp=1)
        before = (self.root / "game1/game.dat").read_bytes()
        replace = Path.replace
        def fail_stage(path, target):
            if path.name.startswith(".denghuo-stage"):
                raise OSError("simulated directory rename failure")
            return replace(path, target)
        with patch.object(Path, "replace", fail_stage):
            with self.assertRaises(OSError):
                self.manager.restore(self.root, self.payload(row))
        self.assertEqual(before, (self.root / "game1/game.dat").read_bytes())

    def test_game_reopening_before_swap_blocks_restore(self):
        self.manager.tick(self.root)
        row = self.manager.events(self.root)[0]
        before = (self.root / "game1/game.dat").read_bytes()
        checks = iter([None, ValueError("游戏重新打开")])
        def check():
            result = next(checks)
            if result:
                raise result
        self.manager.closed_check = check
        with self.assertRaisesRegex(ValueError, "重新打开"):
            self.manager.restore(self.root, self.payload(row))
        self.assertEqual(before, (self.root / "game1/game.dat").read_bytes())

    def test_branch_maps_are_captured_and_restored(self):
        self.write_save(branch=1)
        self.manager.tick(self.root)
        row = self.manager.events(self.root)[0]
        self.write_save(hp=1, branch=1)
        self.manager.restore(self.root, self.payload(row))
        self.assertTrue((self.root / "game1/depth2-branch1.dat").exists())

    def test_inconsistent_or_invalid_floor_is_not_backed_up(self):
        self.write_save()
        os.utime(self.root / "game1/depth2.dat", (1, 1))
        with self.assertRaisesRegex(ValueError, "一致存档"):
            self.manager.tick(self.root, force=True)
        self.assertEqual(self.manager.events(self.root), [])
        self.write_save()
        (self.root / "game1/depth1.dat").write_bytes(b"broken old floor")
        with self.assertRaises(ValueError):
            self.manager.tick(self.root, force=True)
        self.assertEqual(self.manager.events(self.root), [])

    def test_auto_disabled_persists_but_manual_capture_works(self):
        self.manager.set_enabled(False)
        self.manager.tick(self.root)
        self.assertEqual(self.manager.events(self.root), [])
        self.manager.tick(self.root, force=True)
        self.assertEqual(len(self.manager.events(self.root)), 1)
        reloaded = BackupManager(self.manager.directory)
        self.assertFalse(reloaded.enabled)

    def test_storage_limit_keeps_existing_backup(self):
        self.manager.tick(self.root)
        first = self.manager.events(self.root)[0]
        self.write_save(hp=2)
        self.clock += 10
        with patch("companion.backups.MAX_STORAGE", 1):
            with self.assertRaisesRegex(ValueError, "上限"):
                self.manager.tick(self.root, force=True)
        self.assertTrue((self.manager.scope(self.root) / (first["id"] + ".zip")).exists())

    def test_invalid_timeline_cannot_leak_nonfinite_values_or_restore(self):
        self.manager.tick(self.root)
        row=self.manager.events(self.root)[0]
        before=(self.root/'game1/game.dat').read_bytes()
        path=self.manager.scope(self.root)/'timeline.json'
        for key,value in [('saved',float('nan')),('saved',10**1000),('time',float('inf')),('depth',True),('version','912')]:
            with self.subTest(key=key):
                broken={**row,key:value};path.write_text(json.dumps([broken]))
                result=self.manager.snapshot(self.root)
                self.assertTrue(result['error']);self.assertEqual(result['slots'],[])
                json.dumps(result,allow_nan=False)
                with self.assertRaises(ValueError):self.manager.restore(self.root,self.payload(row))
                self.assertEqual(before,(self.root/'game1/game.dat').read_bytes())

    def test_recursive_preferences_and_timeline_pause_with_recoverable_errors(self):
        self.manager.directory.mkdir()
        bad='['*1200+'0'+']'*1200
        (self.manager.directory/'preferences.json').write_text(bad)
        reloaded=BackupManager(self.manager.directory)
        self.assertFalse(reloaded.enabled);self.assertTrue(reloaded.error)
        self.manager.tick(self.root)
        (self.manager.scope(self.root)/'timeline.json').write_text(bad)
        self.assertIn('损坏',self.manager.snapshot(self.root)['error'])

    def test_numeric_reference_examples_and_sources(self):
        catalog = Catalog()
        rows = {row["id"]: row for row in catalog.entries}
        self.assertEqual(len(rows), len(catalog.entries), 'catalog identities must be unique')
        seeds = {'plants.' + name + '$seed' for name in ('blindweed', 'mageroyal', 'earthroot',
                 'fadeleaf', 'firebloom', 'icecap', 'rotberry', 'sorrowmoss', 'starflower',
                 'stormvine', 'sungrass', 'swiftthistle')}
        self.assertTrue(seeds <= rows.keys(), 'all standard seed materials need named catalog identities')
        self.assertEqual(sum(bool(row.get("numbers")) for row in rows.values()), catalog.data["numeric_count"])
        rat = {r["label"]: r["value"] for r in rows["actors.mobs.rat"]["numbers"]}
        self.assertEqual(rat["初始生命"], "8")
        self.assertEqual(rat["基础命中"], "8")
        self.assertIn("1–4", rat["基础伤害随机范围"])
        sword = {r["label"]: r["value"] for r in rows["items.weapon.melee.sword"]["numbers"]}
        self.assertEqual(sword["最低基础伤害"], "3 + L")
        self.assertEqual(sword["最高基础伤害"], "5*(3+1) + L*(3+1)")
        self.assertEqual(len(catalog.search(category="角色与机制")["entries"]), 24)
        self.assertIn("57a4e06a4caf162446d1c28caa7983f0493fecf0", rows["actors.mobs.rat"]["source"])
        self.assertTrue(catalog.search("基础命中")["total"])

    def test_corrupt_reused_archive_is_quarantined_and_rebuilt(self):
        self.manager.tick(self.root)
        row = self.manager.events(self.root)[0]
        archive = self.manager.scope(self.root)/(row['id']+'.zip')
        archive.write_bytes(b'controlled broken zip')
        self.clock += 10
        self.manager.tick(self.root)
        self.assertEqual(self.manager.error, '')
        self.manager.checked_archive(self.root, row['id'], 1)
        copies = list((self.manager.directory.parent/'backup-quarantine').rglob('*.zip'))
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].read_bytes(), b'controlled broken zip')

    def test_old_history_restores_after_restart_and_preserves_names(self):
        self.manager.tick(self.root)
        first = self.manager.events(self.root)[0]
        self.manage(self.root, {**first, 'label': '首领之前', 'locked': True})
        for hp in (10, 5):
            self.clock += 4000
            self.write_save(hp)
            self.manager.tick(self.root)
        self.assertNotIn(first['id'], [r['id'] for r in self.manager.events(self.root)])
        reloaded = BackupManager(self.manager.directory, clock=lambda:self.clock, closed_check=lambda:None)
        history = reloaded.snapshot(self.root)['history']
        saved = next(r for r in history if r['id'] == first['id'])
        self.assertEqual(saved['label'], '首领之前')
        self.assertTrue(saved['locked'])
        reloaded.restore(self.root, self.payload(first))
        self.assertEqual(reloaded.current_summary(self.root, 1)['hp'], 20)

    def test_undo_survives_restart_and_preserves_progress_and_extra_files(self):
        self.manager.tick(self.root)
        first = self.manager.events(self.root)[0]
        folder = self.write_save(2)
        (folder/'notes.txt').write_text('original metadata')
        before = {p.name:p.read_bytes() for p in folder.iterdir()}
        self.manager.restore(self.root, self.payload(first))
        self.write_save(12)
        intermediate = (folder/'game.dat').read_bytes()
        reloaded = BackupManager(self.manager.directory, closed_check=lambda:None)
        record = reloaded.undo_status(self.root)[0]
        reloaded.undo(self.root, {**record, 'confirm':'撤回槽位 1'})
        self.assertEqual(before, {p.name:p.read_bytes() for p in folder.iterdir()})
        self.assertEqual(reloaded.undo_status(self.root), [])
        preserved = list(self.root.glob('.denghuo-before-1-*'))
        self.assertTrue(any((p/'game.dat').read_bytes()==intermediate for p in preserved))

    def test_undo_rejects_modified_original_and_reopened_game(self):
        self.manager.tick(self.root)
        self.write_save(2)
        self.manager.restore(self.root, self.payload(self.manager.events(self.root)[0]))
        record = self.manager.undo_status(self.root)[0]
        original = list(self.root.glob('.denghuo-before-1-*'))[0]
        original.joinpath('tampered.txt').write_text('changed')
        current = (self.root/'game1/game.dat').read_bytes()
        with self.assertRaisesRegex(ValueError, '副本已变化'):
            self.manager.undo(self.root, {**record, 'confirm':'撤回槽位 1'})
        self.assertEqual(current, (self.root/'game1/game.dat').read_bytes())
        original.joinpath('tampered.txt').unlink()
        calls=[]
        def reopen():
            calls.append(1)
            if len(calls)==2:raise ValueError('游戏仍在运行')
        self.manager.closed_check=reopen
        with self.assertRaisesRegex(ValueError, '仍在运行'):
            self.manager.undo(self.root, {**record, 'confirm':'撤回槽位 1'})
        self.assertEqual(current, (self.root/'game1/game.dat').read_bytes())

    def test_journal_write_failure_rolls_back_both_restore_and_undo(self):
        from companion.backups import atomic_json
        self.manager.tick(self.root)
        self.write_save(2)
        current = (self.root/'game1/game.dat').read_bytes()
        def fail_journal(path, value):
            if path.name=='restores.json':raise OSError('controlled journal failure')
            return atomic_json(path,value)
        with patch('companion.backups.atomic_json', side_effect=fail_journal):
            with self.assertRaises(OSError):
                self.manager.restore(self.root,self.payload(self.manager.events(self.root)[0]))
        self.assertEqual(current,(self.root/'game1/game.dat').read_bytes())
        self.manager.restore(self.root,self.payload(self.manager.events(self.root)[0]))
        restored=(self.root/'game1/game.dat').read_bytes()
        record=self.manager.undo_status(self.root)[0]
        with patch('companion.backups.atomic_json',side_effect=fail_journal):
            with self.assertRaises(OSError):self.manager.undo(self.root,{**record,'confirm':'撤回槽位 1'})
        self.assertEqual(restored,(self.root/'game1/game.dat').read_bytes())
        self.assertEqual(len(self.manager.undo_status(self.root)),1)

    def test_non_io_journal_failure_rolls_back_restore_and_undo(self):
        self.manager.tick(self.root);first=self.manager.events(self.root)[0]
        self.write_save(2);folder=self.root/'game1'
        current={p.name:p.read_bytes() for p in folder.iterdir()}
        for failure in (ValueError('controlled serialization failure'),RuntimeError('controlled journal failure'),
                        UnicodeEncodeError('utf-8','\ud800',0,1,'controlled surrogate')):
            with self.subTest(failure=type(failure).__name__):
                with patch('companion.backups.atomic_json',side_effect=failure),self.assertRaises((ValueError,RuntimeError)):
                    self.manager.restore(self.root,self.payload(first))
                self.assertEqual({p.name:p.read_bytes() for p in folder.iterdir()},current)
                self.assertEqual(self.manager.undo_status(self.root),[])
        self.manager.restore(self.root,self.payload(first))
        record=self.manager.undo_status(self.root)[0]
        self.write_save(3);restored={p.name:p.read_bytes() for p in folder.iterdir()}
        journal_path=self.manager.scope(self.root)/'restores.json';journal_before=journal_path.read_bytes()
        with (patch('companion.backups.atomic_json',side_effect=ValueError('controlled second restore failure')),
                self.assertRaises(ValueError)):
            self.manager.restore(self.root,self.payload(first))
        self.assertEqual({p.name:p.read_bytes() for p in folder.iterdir()},restored)
        self.assertEqual(journal_path.read_bytes(),journal_before)
        for failure in (ValueError('controlled serialization failure'),RuntimeError('controlled journal failure')):
            with self.subTest(undo_failure=type(failure).__name__):
                with patch('companion.backups.atomic_json',side_effect=failure),self.assertRaises((ValueError,RuntimeError)):
                    self.manager.undo(self.root,{**record,'confirm':'撤回槽位 1'})
                self.assertEqual({p.name:p.read_bytes() for p in folder.iterdir()},restored)
                self.assertEqual(len(self.manager.undo_status(self.root)),1)

    def test_restore_and_undo_preserve_malformed_unicode_in_original_save(self):
        from companion.saves import read_bundle
        self.manager.tick(self.root);first=self.manager.events(self.root)[0]
        folder=self.write_save(2);game=read_bundle(folder/'game.dat')
        game['hero']['class']='\ud800'
        (folder/'game.dat').write_bytes(gzip.compress(json.dumps(game).encode()))
        current={p.name:p.read_bytes() for p in folder.iterdir()}
        self.manager.restore(self.root,self.payload(first))
        record=self.manager.undo_status(self.root)[0]
        self.assertEqual(record['before']['class'],'\ud800')
        restarted=BackupManager(self.manager.directory,clock=lambda:self.clock,closed_check=lambda:None)
        record=restarted.undo_status(self.root)[0]
        restarted.undo(self.root,{**record,'confirm':'撤回槽位 1'})
        self.assertEqual({p.name:p.read_bytes() for p in folder.iterdir()},current)

    def test_undo_rechecks_both_directories_after_process_check(self):
        self.manager.tick(self.root);first=self.manager.events(self.root)[0]
        self.write_save(2);self.manager.restore(self.root,self.payload(first))
        record=self.manager.undo_status(self.root)[0]
        journal=self.manager.journals(self.root)[0]
        original=self.root/journal['original'];folder=self.root/'game1'
        for target in (original,folder):
            with self.subTest(target=target.name):
                before=(folder/'game.dat').read_bytes();calls=[]
                def change_during_check():
                    calls.append(1)
                    if len(calls)==2:(target/'new-save.txt').write_text('changed')
                self.manager.closed_check=change_during_check
                with self.assertRaisesRegex(ValueError,'变化'):
                    self.manager.undo(self.root,{**record,'confirm':'撤回槽位 1'})
                self.assertEqual((folder/'game.dat').read_bytes(),before)
                self.assertEqual(len(self.manager.undo_status(self.root)),1)
                (target/'new-save.txt').unlink()

    def test_undo_slot_stays_selectable_when_all_active_backups_removed(self):
        self.manager.tick(self.root);first=self.manager.events(self.root)[0]
        self.write_save(2);before=(self.root/'game1/game.dat').read_bytes()
        self.manager.restore(self.root,self.payload(first));self.manager.set_enabled(False)
        with self.assertRaisesRegex(ValueError, '撤回'):
            self.manager.remove(self.root,{**first,'confirm':'移出备份 1'})
        # External movement of the active library must not hide its intact undo journal.
        scope=self.manager.scope(self.root)
        (scope/(first['id']+'.zip')).replace(Path(self.temporary.name)/'externally-preserved.zip')
        atomic_json(scope/'history.json',[])
        atomic_json(scope/'timeline.json',[])
        reloaded=BackupManager(self.manager.directory,clock=lambda:self.clock,closed_check=lambda:None)
        snapshot=reloaded.snapshot(self.root)
        self.assertEqual(snapshot['history'],[])
        self.assertEqual([r['slot'] for r in snapshot['slots']],[1])
        self.assertIsNone(snapshot['slots'][0]['latest'])
        reloaded.undo(self.root,{**snapshot['undo'][0],'confirm':'撤回槽位 1'})
        self.assertEqual((self.root/'game1/game.dat').read_bytes(),before)

    def test_all_floor_structures_are_checked_before_capture_and_import(self):
        self.manager.tick(self.root);first=self.manager.events(self.root)[0]
        valid,filename=self.manager.export(self.root,first)
        from io import BytesIO
        for invalid in ({},{'level':None},{'level':[]},{'level':'invalid'}):
            for floor_name in ('depth1.dat','depth2.dat'):
                with self.subTest(invalid=invalid,floor=floor_name):
                    folder=self.write_save();before=(folder/'game.dat').read_bytes()
                    (folder/floor_name).write_bytes(gzip.compress(json.dumps(invalid).encode()))
                    os.utime(folder/floor_name,(1700000020,1700000020))
                    with self.assertRaises(ValueError):self.manager.capture(self.root,1)
                    self.assertEqual((folder/'game.dat').read_bytes(),before)
                    with ZipFile(BytesIO(valid)) as archive:
                        payloads={n:archive.read(n) for n in archive.namelist() if n!='manifest.json'}
                        manifest=json.loads(archive.read('manifest.json'))
                    payloads[floor_name]=gzip.compress(json.dumps(invalid).encode())
                    manifest['files']={n:hashlib.sha256(raw).hexdigest() for n,raw in payloads.items()}
                    stream=BytesIO()
                    with ZipFile(stream,'w',ZIP_DEFLATED) as archive:
                        for name,raw in payloads.items():archive.writestr(name,raw)
                        archive.writestr('manifest.json',json.dumps(manifest))
                    with self.assertRaisesRegex(ValueError,'地图结构'):
                        self.manager.import_archive(self.root,stream.getvalue())
                    self.assertEqual((folder/'game.dat').read_bytes(),before)
                    if floor_name=='depth1.dat':(folder/floor_name).unlink()

    def test_floor_geometry_arrays_and_type_are_required_for_a_usable_backup(self):
        from companion.saves import read_bundle,validate_level
        folder=self.write_save();valid=read_bundle(folder/'depth2.dat')['level']
        cases=[{**valid,'width':0},{**valid,'height':True},{**valid,'map':[4]},
               {**valid,'map':[-1]*16},{**valid,'map':[256]*16},
               {**valid,'map':[False]*16},{**valid,'visited':[]},{**valid,'mapped':[0]*16},
               {k:v for k,v in valid.items() if k!='__className'}, {**valid,'__className':[]},
               {**valid,'__className':'com.shatteredpixel.shatteredpixeldungeon.levels.Level'},
               {k:v for k,v in valid.items() if k!='version'}]
        for invalid in cases:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):validate_level({'level':invalid})
                (folder/'depth2.dat').write_bytes(gzip.compress(json.dumps({'level':invalid}).encode()))
                os.utime(folder/'depth2.dat',(1700000020,1700000020))
                before=(folder/'game.dat').read_bytes()
                with self.assertRaises(ValueError):self.manager.capture(self.root,1)
                self.assertEqual((folder/'game.dat').read_bytes(),before)

    def test_generated_floor_members_are_required_for_main_and_branches(self):
        from companion.saves import read_bundle,validate_floor_members
        folder=self.write_save();game=read_bundle(folder/'game.dat')
        for generated,missing in (([1,2],'depth1.dat'),([2,1011],'depth11-branch1.dat')):
            with self.subTest(generated=generated):
                game['generated_levels']=generated
                (folder/'game.dat').write_bytes(gzip.compress(json.dumps(game).encode()))
                os.utime(folder/'game.dat',(1700000020,1700000020))
                before=(folder/'game.dat').read_bytes()
                with self.assertRaisesRegex(ValueError,'历史楼层'):self.manager.capture(self.root,1)
                self.assertEqual((folder/'game.dat').read_bytes(),before)
                (folder/missing).write_bytes((folder/'depth2.dat').read_bytes())
                row=self.manager.capture(self.root,1)
                self.assertTrue(self.manager.checked_archive(self.root,row['id']))
                (folder/missing).unlink()
        for invalid in (None,[True],['2'],[1000],[27],[21002]):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                validate_floor_members({**game,'generated_levels':invalid},['game.dat','depth2.dat'])
        validate_floor_members({**game,'version':833,'generated_levels':[2]},['game.dat','depth2.dat'])
        legacy={k:v for k,v in game.items() if k!='generated_levels'};legacy['version']=832
        validate_floor_members(legacy,['game.dat','depth2.dat'])

    def test_archive_rejects_out_of_range_terrain_in_current_and_historical_floors(self):
        from io import BytesIO
        from companion.saves import read_bundle
        folder=self.write_save();self.manager.tick(self.root)
        row=self.manager.events(self.root)[0]
        with ZipFile(BytesIO(self.manager.export(self.root,row)[0])) as archive:
            source={name:archive.read(name) for name in archive.namelist() if name!='manifest.json'}
            metadata=json.loads(archive.read('manifest.json'))
        original={p.name:p.read_bytes() for p in folder.iterdir()}
        valid=read_bundle(folder/'depth2.dat')['level']
        for floor in ('depth2.dat','depth1.dat'):
            for terrain in (-1,256):
                with self.subTest(floor=floor,terrain=terrain):
                    payloads=dict(source)
                    payloads[floor]=gzip.compress(json.dumps({'level':{**valid,'map':[terrain]*16}}).encode())
                    manifest={**metadata,'files':{name:hashlib.sha256(raw).hexdigest() for name,raw in payloads.items()}}
                    stream=BytesIO()
                    with ZipFile(stream,'w',ZIP_DEFLATED) as archive:
                        for name,raw in payloads.items():archive.writestr(name,raw)
                        archive.writestr('manifest.json',json.dumps(manifest))
                    with self.assertRaisesRegex(ValueError,'地形编号'):
                        self.manager.import_archive(self.root,stream.getvalue())
                    self.assertEqual({p.name:p.read_bytes() for p in folder.iterdir()},original)

    def test_undo_detects_changes_during_final_directory_hash(self):
        import io
        self.manager.tick(self.root);first=self.manager.events(self.root)[0]
        self.write_save(2);self.manager.restore(self.root,self.payload(first))
        record=self.manager.undo_status(self.root)[0]
        original=(self.root/self.manager.journals(self.root)[0]['original']).resolve()
        baseline={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in original.iterdir()}
        native_open=Path.open
        for change in ('add','delete','rewrite_read_file'):
            with self.subTest(change=change):
                reads=[]
                def controlled_open(path,*args,**kwargs):
                    if path==original/'game.dat' and args and args[0]=='rb':
                        reads.append(1)
                        if len(reads)==2:
                            with native_open(path,'rb') as stream:raw=stream.read()
                            class MutatingRead(io.BytesIO):
                                def read(inner,*read_args):
                                    data=super().read(*read_args)
                                    if change=='add':
                                        with native_open(original/'new-file.txt','wb') as added:added.write(b'new')
                                    elif change=='delete':(original/'depth2.dat').unlink()
                                    else:
                                        with native_open(original/'depth2.dat','wb') as altered:altered.write(b'changed after read')
                                    return data
                            return MutatingRead(raw)
                    return native_open(path,*args,**kwargs)
                current=(self.root/'game1/game.dat').read_bytes()
                with patch.object(Path,'open',controlled_open),self.assertRaisesRegex(ValueError,'变化'):
                    self.manager.undo(self.root,{**record,'confirm':'撤回槽位 1'})
                self.assertEqual(len(reads),2)
                self.assertEqual((self.root/'game1/game.dat').read_bytes(),current)
                self.assertEqual(len(self.manager.undo_status(self.root)),1)
                for name,(raw,stamp) in baseline.items():
                    (original/name).write_bytes(raw);os.utime(original/name,ns=(stamp,stamp))
                if (original/'new-file.txt').exists():(original/'new-file.txt').unlink()

    def test_import_export_locked_recoverable_removal_and_preview(self):
        self.manager.tick(self.root)
        first=self.manager.events(self.root)[0]
        stored=(self.manager.scope(self.root)/(first['id']+'.zip')).read_bytes()
        raw,filename=self.manager.export(self.root,first)
        self.assertTrue(filename.endswith('.zip'))
        self.manage(self.root,{**first,'locked':True})
        with self.assertRaisesRegex(ValueError,'永久保留'):
            self.manager.remove(self.root,{**first,'confirm':'移出备份 1'})
        self.manage(self.root,{**first,'locked':False})
        self.manager.remove(self.root,{**first,'confirm':'移出备份 1'})
        self.assertEqual(self.manager.history(self.root),[])
        recycled=list((self.manager.directory.parent/'backup-recycle').rglob('*.zip'))
        self.assertEqual(recycled[0].read_bytes(),stored)
        self.manager.import_archive(self.root,raw)
        self.write_save(2)
        preview=self.manager.preview(self.root,first)
        self.assertEqual(preview['current']['hp'],2)
        self.assertEqual(preview['target']['hp'],20)
        self.assertTrue(preview['same_run'])
        with self.assertRaises(ValueError):self.manager.import_archive(self.root,b'not a zip')

    def test_backup_health_reports_blockage_and_pause_without_opening_library(self):
        self.manager.tick(self.root)
        self.assertEqual(self.manager.health_status(self.root)['state'],'protected')
        self.write_save(2);self.clock+=10
        with patch('companion.backups.MAX_STORAGE',1):self.manager.tick(self.root)
        health=self.manager.health_status(self.root)
        self.assertEqual(health['state'],'blocked');self.assertIn('上限',health['error'])
        self.manager.set_enabled(False)
        self.assertEqual(self.manager.health_status(self.root)['state'],'paused')

    def test_removal_second_index_failure_keeps_archive_and_both_indexes(self):
        from companion.backups import atomic_json
        self.manager.tick(self.root)
        first=self.manager.events(self.root)[0]
        scope=self.manager.scope(self.root)
        before={name:(scope/name).read_bytes() for name in ('history.json','timeline.json')}
        def fail_timeline(path,value):
            if path.name=='timeline.json':raise OSError('controlled second index failure')
            return atomic_json(path,value)
        with patch('companion.backups.atomic_json',side_effect=fail_timeline):
            with self.assertRaises(OSError):
                self.manager.remove(self.root,{**first,'confirm':'移出备份 1'})
        self.assertTrue((scope/(first['id']+'.zip')).exists())
        for name,raw in before.items():self.assertEqual((scope/name).read_bytes(),raw)
        self.assertEqual(self.manager.selected(self.root,first)['id'],first['id'])

    def test_undo_restore_into_originally_absent_slot_preserves_restored_progress(self):
        self.manager.tick(self.root)
        first=self.manager.events(self.root)[0]
        folder=self.root/'game1'
        for path in folder.iterdir():path.unlink()
        folder.rmdir()
        self.manager.restore(self.root,self.payload(first))
        restored=(folder/'game.dat').read_bytes()
        record=self.manager.undo_status(self.root)[0]
        self.manager.undo(self.root,{**record,'confirm':'撤回槽位 1'})
        self.assertFalse(folder.exists())
        self.assertTrue(any((path/'game.dat').read_bytes()==restored
                            for path in self.root.glob('.denghuo-before-1-*')))

    def test_health_uses_current_save_time_after_restoring_older_progress(self):
        self.clock=1700000000+20
        self.manager.tick(self.root)
        first=self.manager.events(self.root)[0]
        self.clock+=120
        self.write_save(2)
        folder=self.root/'game1'
        for path in folder.iterdir():os.utime(path,(self.clock,self.clock))
        self.manager.tick(self.root)
        self.assertEqual(self.manager.health_status(self.root)['state'],'protected')
        self.manager.restore(self.root,self.payload(first))
        self.manager.tick(self.root)
        self.assertEqual(self.manager.health_status(self.root)['state'],'waiting')
        self.assertEqual(self.manager.snapshot(self.root)['health'],'waiting')

    def test_invalid_changed_save_is_blocked_and_ended_slot_is_not_an_error(self):
        self.manager.tick(self.root)
        (self.root/'game1/game.dat').write_bytes(b'broken save bytes')
        self.clock+=10;self.manager.tick(self.root)
        self.assertEqual(self.manager.health_status(self.root)['state'],'blocked')
        self.assertIn('槽位 1',self.manager.error)
        (self.root/'game1/game.dat').write_bytes(b'\0')
        self.clock+=10;self.manager.tick(self.root)
        self.assertEqual(self.manager.health_status(self.root)['state'],'waiting')
        self.assertEqual(self.manager.error,'')

    def test_preview_changed_progress_rejects_before_staging_or_index_discovery(self):
        self.manager.tick(self.root)
        row = self.manager.history(self.root)[0]
        preview = self.manager.preview(self.root, row)
        self.assertEqual(preview['expected_current'], self.manager.directory_digest(self.root / 'game1'))
        self.write_save(2)
        before = {p.name: p.read_bytes() for p in self.manager.scope(self.root).iterdir() if p.is_file()}
        game_before = {p.name: p.read_bytes() for p in (self.root / 'game1').iterdir()}
        with patch.object(self.manager, 'selected', side_effect=AssertionError('must not discover/write history')):
            with self.assertRaisesRegex(ValueError, '进度已变化.*重新预览'):
                self.manager.restore(self.root, {**self.payload(row), 'expected_current': preview['expected_current']})
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.manager.scope(self.root).iterdir() if p.is_file()})
        self.assertEqual(game_before, {p.name: p.read_bytes() for p in (self.root / 'game1').iterdir()})
        self.assertFalse(list(self.root.glob('.denghuo-stage-*')))

    def test_preview_rejects_summary_drift_and_same_bytes_directory_replacement(self):
        self.manager.tick(self.root)
        row = self.manager.history(self.root)[0]
        original_summary = self.manager.current_summary
        def drift(*args):
            result = original_summary(*args)
            self.write_save(2)
            return result
        with patch.object(self.manager, 'current_summary', side_effect=drift), self.assertRaisesRegex(ValueError, '预览期间变化'):
            self.manager.preview(self.root, row)
        def replacement(*args):
            result = original_summary(*args)
            folder = self.root / 'game1'
            previous = self.root / 'previous-slot'
            folder.rename(previous)
            shutil.copytree(previous, folder)
            return result
        with patch.object(self.manager, 'current_summary', side_effect=replacement), self.assertRaisesRegex(ValueError, '预览期间变化'):
            self.manager.preview(self.root, row)

    def test_expected_current_strict_types_and_null_absent_slot(self):
        self.manager.tick(self.root)
        row = self.manager.history(self.root)[0]
        for value in (True, 1, [], {}, '', 'g' * 64, 'a' * 63):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, '摘要不正确'):
                self.manager.restore(self.root, {**self.payload(row), 'expected_current': value})
        self.assertFalse(list(self.root.glob('.denghuo-stage-*')))
        (self.root / 'game1').rename(self.root / 'previous-slot')
        self.assertIsNone(self.manager.preview(self.root, row)['expected_current'])
        self.write_save(2)
        with self.assertRaisesRegex(ValueError, '进度已变化'):
            self.manager.restore(self.root, {**self.payload(row), 'expected_current': None})
        self.assertFalse(list(self.root.glob('.denghuo-stage-*')))

    def test_history_recovery_preserves_originals_undo_and_progress_and_defaults_to_locked(self):
        self.manager.tick(self.root)
        first = self.manager.history(self.root)[0]
        self.manage(self.root, {**first, 'label': '无法从损坏索引确认的原名称', 'locked': True})
        old_revision = self.manager.selected(self.root, first)['metadata_revision']
        self.write_save(2)
        self.manager.restore(self.root, self.payload(first))
        self.write_save(8, slot=2); self.clock += 11; self.manager.tick(self.root)
        scope = self.manager.scope(self.root)
        atomic_json(scope / 'stages.json', {})
        (scope / 'history.json').write_bytes(b'{broken-history\xff\x00')
        names = ('history.json', 'timeline.json', 'restores.json', 'stages.json')
        originals = {name: (scope / name).read_bytes() for name in names}
        archives = {p.name: p.read_bytes() for p in scope.glob('*.zip')}
        game = {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        status = self.manager.snapshot(self.root)
        self.assertFalse(status['records_available']); self.assertTrue(status['repair_history_available'])
        preview = self.manager.history_repair_preview(self.root)
        self.assertEqual((scope / 'history.json').read_bytes(), originals['history.json'])
        result = self.manager.repair_history(self.root, {'confirm': '恢复备份历史', 'expected': preview['expected']})
        for name in names:
            self.assertEqual((Path(result['recovery_directory']) / name).read_bytes(), originals[name])
            if name != 'history.json': self.assertEqual((scope / name).read_bytes(), originals[name])
        self.assertEqual({p.name: p.read_bytes() for p in scope.glob('*.zip')}, archives)
        self.assertEqual({p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}, game)
        restarted = BackupManager(self.manager.directory, clock=lambda: self.clock, closed_check=lambda: None)
        restored = restarted.snapshot(self.root)
        self.assertTrue(restored['records_available']); self.assertTrue(restored['undo'])
        self.assertTrue(all(row['locked'] and row['metadata_recovered'] for row in restored['history']))
        self.assertEqual(len(restored['history']), preview['valid_archives'])
        with self.assertRaisesRegex(ValueError, '已变化'):
            restarted.manage(self.root, {**first, 'locked': False, 'expected_metadata_revision': old_revision})
        self.clock += 11; restarted.tick(self.root)
        self.assertTrue(all(row['locked'] for row in restarted.history(self.root)))
        chosen = restarted.selected(self.root, first)
        restarted.manage(self.root, {**first, 'label': '重新核对的名称', 'locked': True,
                                   'expected_metadata_revision': chosen['metadata_revision']})
        self.assertNotIn('metadata_recovered', restarted.selected(self.root, first))
        self.assertEqual(restarted.validate(self.root), [])
        raw, _ = restarted.export(self.root, first)
        self.assertEqual(restarted.import_archive(self.root, raw)['id'], first['id'])
        restarted.restore(self.root, self.payload(first))
        journal = restarted.undo_status(self.root)[0]
        restarted.undo(self.root, {'id': journal['id'], 'slot': journal['slot'], 'confirm': '撤回槽位 1'})

    def test_history_recovery_keeps_bad_and_missing_archives_unavailable_in_history_and_nodes(self):
        self.manager.tick(self.root); first = self.manager.history(self.root)[0]
        self.clock += 30; self.write_save(8); self.manager.tick(self.root)
        scope = self.manager.scope(self.root)
        broken = scope / (first['id'] + '.zip'); broken.write_bytes(b'bad original ZIP')
        unknown = scope / 'unknown.zip'; unknown.write_bytes(b'unknown original')
        events = self.manager.events(self.root)
        events.append({**events[0], 'slot': 3, 'id': 'c' * 64})
        atomic_json(scope / 'timeline.json', events); (scope / 'history.json').write_bytes(b'bad index')
        preview = self.manager.history_repair_preview(self.root)
        self.assertEqual(preview['valid_archives'], 1); self.assertEqual(len(preview['unavailable']), 3)
        self.manager.repair_history(self.root, {'confirm': '恢复备份历史', 'expected': preview['expected']})
        restarted = BackupManager(self.manager.directory, clock=lambda: self.clock, closed_check=lambda: None)
        status = restarted.snapshot(self.root)
        bad = next(row for row in status['history'] if row['id'] == first['id'])
        self.assertFalse(bad['integrity']['valid']); self.assertTrue(bad['locked'])
        slot = next(row for row in status['slots'] if row['slot'] == 1)
        node = next(node['backup'] for node in slot['nodes'] if node['backup'])
        self.assertFalse(node['integrity']['valid'])
        self.assertEqual(broken.read_bytes(), b'bad original ZIP'); self.assertEqual(unknown.read_bytes(), b'unknown original')
        with self.assertRaises(ValueError): restarted.export(self.root, first)

    def test_history_recovery_rejects_changes_after_preview_and_preserves_every_changed_original(self):
        self.manager.tick(self.root); scope = self.manager.scope(self.root)
        (scope / 'history.json').write_bytes(b'broken original')
        for change in ('history', 'timeline', 'zip', 'restore', 'stage'):
            with self.subTest(change=change):
                preview = self.manager.history_repair_preview(self.root)
                path = next(scope.glob('*.zip')) if change == 'zip' else scope / {
                    'history': 'history.json', 'timeline': 'timeline.json', 'restore': 'restores.json', 'stage': 'stages.json'}[change]
                original = path.read_bytes() if path.exists() else None
                if change == 'history': changed = b'another broken original'
                elif change == 'timeline':
                    rows = json.loads(original); rows[0]['time'] += 1; changed = json.dumps(rows).encode()
                elif change == 'zip': changed = original + b'outside edit'
                elif change == 'restore': changed = b'[]'
                else: changed = b'{}'
                path.write_bytes(changed)
                with self.assertRaisesRegex(ValueError, '重新预览'):
                    self.manager.repair_history(self.root, {'confirm': '恢复备份历史', 'expected': preview['expected']})
                self.assertEqual(path.read_bytes(), changed)
                if original is None: path.unlink()
                else: path.write_bytes(original)

    def test_history_recovery_preservation_or_publication_failure_retains_corrupt_original(self):
        self.manager.tick(self.root); scope = self.manager.scope(self.root)
        path = scope / 'history.json'; original = b'broken original'; path.write_bytes(original)
        real_atomic = atomic_json
        for failure in ('preserve', 'publish'):
            preview = self.manager.history_repair_preview(self.root)
            def fail(target, value):
                if failure == 'preserve' and target.name == 'manifest.json': raise OSError('controlled full disk')
                real_atomic(target, value)
                if failure == 'publish' and target == path: raise OSError('controlled publish failure')
            with self.subTest(failure=failure), patch('companion.backups.atomic_json', side_effect=fail), self.assertRaises((OSError, ValueError)):
                self.manager.repair_history(self.root, {'confirm': '恢复备份历史', 'expected': preview['expected']})
            self.assertEqual(path.read_bytes(), original)
            self.assertTrue(any((directory / 'history.json').read_bytes() == original for directory in scope.glob('history-recovery-*')))

    def test_history_recovery_stops_if_other_relationships_are_damaged(self):
        self.manager.tick(self.root); scope = self.manager.scope(self.root)
        (scope / 'history.json').write_bytes(b'broken history')
        for name in ('timeline.json', 'restores.json', 'stages.json'):
            with self.subTest(name=name):
                path = scope / name; original = path.read_bytes() if path.exists() else None
                path.write_bytes(b'broken related record')
                self.assertFalse(self.manager.snapshot(self.root)['repair_history_available'])
                with self.assertRaisesRegex(ValueError, '不能安全恢复'):
                    self.manager.history_repair_preview(self.root)
                self.assertEqual(path.read_bytes(), b'broken related record')
                if original is None: path.unlink()
                else: path.write_bytes(original)

    def test_repair_timeline_preserves_sources_names_locks_and_undo(self):
        self.manager.tick(self.root)
        first = self.manager.history(self.root)[0]
        self.manage(self.root, {**first, 'label': '首领前', 'locked': True})
        self.write_save(2)
        (self.root / 'game1/notes.txt').write_bytes(b'original extra file')
        previous = {p.name: p.read_bytes() for p in (self.root / 'game1').iterdir()}
        self.manager.restore(self.root, self.payload(first))
        self.write_save(8, slot=2)
        self.clock += 10
        self.manager.tick(self.root)
        scope = self.manager.scope(self.root)
        history = self.manager.history(self.root)
        orphan = next(r for r in history if r['slot'] == 2)
        rows = [r for r in history if r['id'] != orphan['id']]
        rows += [{**first, 'id': 'a' * 64, 'slot': 3, 'label': '坏文件仍固定', 'locked': True},
                 {**first, 'id': 'b' * 64, 'slot': 4, 'label': '缺失仍固定', 'locked': True}]
        atomic_json(scope / 'history.json', rows)
        (scope / ('a' * 64 + '.zip')).write_bytes(b'bad ZIP original')
        (scope / 'timeline.json').write_bytes(b'{broken\xff\x00')
        self.manager.set_enabled(False)
        names = ('timeline.json', 'history.json', 'restores.json')
        originals = {name: (scope / name).read_bytes() for name in names}
        game_before = {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        zip_before = {p.name: p.read_bytes() for p in scope.glob('*.zip')}
        status = self.manager.snapshot(self.root)
        self.assertTrue(status['repair_timeline_available'])
        self.assertEqual(status['health'], 'paused')
        self.assertFalse(status['records_available'])
        self.assertIn('损坏', status['error'])
        self.assertEqual(status['storage_bytes'], sum(len(raw) for raw in zip_before.values()))
        self.assertIn('storage_breakdown', status)
        result = self.manager.repair_timeline(self.root, {'confirm': '恢复时间记录'})
        for name, raw in originals.items():
            self.assertEqual((Path(result['recovery_directory']) / name).read_bytes(), raw)
        self.assertEqual(originals['restores.json'], (scope / 'restores.json').read_bytes())
        self.assertEqual(game_before, {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertEqual(zip_before, {p.name: p.read_bytes() for p in scope.glob('*.zip')})
        self.assertEqual(self.manager.events(self.root), [])
        state = self.manager.snapshot(self.root)
        records = {r['id']: r for r in state['history']}
        self.assertEqual(records[first['id']]['label'], '首领前')
        self.assertTrue(records[first['id']]['locked'])
        self.assertEqual(records[first['id']]['time'], first['time'])
        self.assertEqual(records[orphan['id']]['recovered_at'], self.clock)
        self.assertFalse(records['a' * 64]['integrity']['valid'])
        self.assertFalse(records['b' * 64]['integrity']['valid'])
        self.assertTrue(records['b' * 64]['locked'])
        self.assertFalse(self.manager.enabled)
        self.assertTrue(all(n['backup'] is None for s in state['slots'] for n in s['nodes']))
        reloaded = BackupManager(self.manager.directory, clock=lambda: self.clock, closed_check=lambda: None)
        self.assertFalse(next(r for r in reloaded.snapshot(self.root)['history'] if r['id'] == 'a' * 64)['integrity']['valid'])
        record = reloaded.undo_status(self.root)[0]
        reloaded.undo(self.root, {**record, 'confirm': '撤回槽位 1'})
        self.assertEqual(previous, {p.name: p.read_bytes() for p in (self.root / 'game1').iterdir()})

    def test_repair_timeline_refuses_other_bad_indexes_and_unconfirmed_action(self):
        self.manager.tick(self.root)
        scope = self.manager.scope(self.root)
        (scope / 'timeline.json').write_bytes(b'{broken')
        with self.assertRaisesRegex(ValueError, '明确确认'):
            self.manager.repair_timeline(self.root, {})
        for name in ('history.json', 'restores.json'):
            path = scope / name
            previous = path.read_bytes() if path.exists() else None
            path.write_bytes(b'{bad index')
            before = {p.name: p.read_bytes() for p in scope.iterdir() if p.is_file()}
            self.assertFalse(self.manager.snapshot(self.root)['repair_timeline_available'])
            with self.assertRaisesRegex(ValueError, name):
                self.manager.repair_timeline(self.root, {'confirm': '恢复时间记录'})
            self.assertEqual(before, {p.name: p.read_bytes() for p in scope.iterdir() if p.is_file()})
            self.assertFalse(list(scope.glob('records-recovery-*')))
            if previous is None:
                path.unlink()
            else:
                path.write_bytes(previous)

    def test_repair_timeline_rolls_back_both_indexes_even_after_publish(self):
        self.manager.tick(self.root)
        scope = self.manager.scope(self.root)
        self.write_save(8, slot=2)
        self.manager.capture(self.root, 2)
        atomic_json(scope / 'history.json', [r for r in self.manager.history(self.root) if r['slot'] == 1])
        (scope / 'timeline.json').write_bytes(b'{broken')
        original = {name: (scope / name).read_bytes() for name in ('history.json', 'timeline.json')}
        for index in ('history.json', 'timeline.json'):
            for exception in (OSError, ValueError, RuntimeError):
                with self.subTest(index=index, exception=exception.__name__):
                    def fail(path, value):
                        atomic_json(path, value)
                        if path.parent == scope and path.name == index:
                            raise exception('controlled post-publish failure')
                    with patch('companion.backups.atomic_json', side_effect=fail), self.assertRaisesRegex(ValueError, '原索引已恢复'):
                        self.manager.repair_timeline(self.root, {'confirm': '恢复时间记录'})
                    for name, raw in original.items():
                        self.assertEqual((scope / name).read_bytes(), raw)
        self.assertTrue(list(scope.glob('records-recovery-*/timeline.json')))

    def test_repair_preservation_failure_prevents_zip_scan(self):
        self.manager.tick(self.root)
        scope = self.manager.scope(self.root)
        (scope / 'timeline.json').write_bytes(b'{broken')
        before = {name: (scope / name).read_bytes() for name in ('history.json', 'timeline.json')}
        original_open = Path.open
        def fail(path, *args, **kwargs):
            if path.parent.name.startswith('records-recovery-') and path.name == 'history.json' and args and args[0] == 'xb':
                raise OSError('controlled preservation failure')
            return original_open(path, *args, **kwargs)
        with patch.object(Path, 'open', new=fail), patch('companion.backups.read_archive') as verify:
            with self.assertRaisesRegex(ValueError, '保留失败'):
                self.manager.repair_timeline(self.root, {'confirm': '恢复时间记录'})
            verify.assert_not_called()
        for name, raw in before.items():
            self.assertEqual((scope / name).read_bytes(), raw)

    def test_unbound_backup_error_is_visible_but_another_root_error_is_not(self):
        self.manager.error = '全局备份存储错误'
        self.assertIsNone(self.manager.health_root)
        for slot in (None, 1):
            state = self.manager.health_status(self.root, slot)
            self.assertEqual(state['state'], 'blocked')
            self.assertEqual(state['error'], '全局备份存储错误')
        self.manager.health_root = str(self.root.parent / 'other-root')
        self.manager.tick_failure = '别的目录读取失败'
        for slot in (None, 1):
            state = self.manager.health_status(self.root, slot)
            self.assertEqual(state['state'], 'waiting')
            self.assertEqual(state['error'], '')
            self.assertEqual(state['other_errors'], '')

    def test_health_cache_scope_and_repair_error_validation_after_restart(self):
        self.manager.tick(self.root)
        row = self.manager.history(self.root)[0]
        other = self.root.parent / 'other-saves'
        shutil.copytree(self.root, other)
        self.manager.tick(other, force=True)
        other_row = self.manager.history(other)[0]
        self.assertEqual(row['id'], other_row['id'])
        scope = self.manager.scope(self.root)
        archive = scope / (row['id'] + '.zip')
        original_zip = archive.read_bytes()
        archive.write_bytes(b'bad only in first root')
        with self.assertRaises(ValueError):
            self.manager.checked_archive(self.root, row['id'], 1)
        self.manager.checked_archive(other, other_row['id'], 1)
        self.assertFalse(self.manager.snapshot(self.root)['history'][0]['integrity']['valid'])
        self.assertTrue(self.manager.snapshot(other)['history'][0]['integrity']['valid'])
        (scope / 'timeline.json').write_bytes(b'{broken')
        before_health = self.manager.health_status(other)
        self.manager.repair_timeline(self.root, {'confirm': '恢复时间记录'})
        self.assertEqual(self.manager.health_status(other), before_health)
        self.assertTrue(self.manager.snapshot(other)['history'][0]['integrity']['valid'])
        self.assertNotEqual(self.manager.health_status(self.root)['state'], 'protected')
        reloaded = BackupManager(self.manager.directory, clock=lambda: self.clock, closed_check=lambda: None)
        self.assertFalse(reloaded.snapshot(self.root)['history'][0]['integrity']['valid'])
        archive.write_bytes(original_zip)
        reloaded.validate(self.root)
        self.assertNotIn('repair_error', reloaded.history(self.root)[0])
        self.assertTrue(reloaded.snapshot(self.root)['history'][0]['integrity']['valid'])

    def test_recurring_timeline_keeps_summaries_only_once_in_history(self):
        from companion.backup_archive import player_summary
        game={'depth':2,'hero':{'class':'MAGE','HP':20,'HT':30,'STR':10,'lvl':2}}
        summary={**player_summary(game,1700000020),'equipment':[{'name':'Long details '*5000}]}
        with patch('companion.backups.player_summary',return_value=summary):
            self.manager.tick(self.root)
            self.clock+=10;self.manager.tick(self.root)
        events=self.manager.events(self.root)
        self.assertEqual(len(events),2)
        self.assertNotIn('equipment',events[0])
        self.assertLess((self.manager.scope(self.root)/'timeline.json').stat().st_size,2048)
        snapshot=self.manager.snapshot(self.root)
        self.assertEqual(snapshot['slots'][0]['latest']['equipment'],summary['equipment'])
        self.assertEqual(snapshot['slots'][0]['nodes'][-1]['backup']['time'],10000)


    def test_export_import_preserves_names_locks_and_original_observations_across_two_moves(self):
        self.manager.tick(self.root)
        first = self.manager.history(self.root)[0]
        self.clock += 30
        self.manager.tick(self.root)
        self.manage(self.root, {**first, 'label': '首领之前 <保留>', 'locked': True})
        original = (self.manager.scope(self.root) / (first['id'] + '.zip')).read_bytes()
        raw, _ = self.manager.export(self.root, first)
        self.assertEqual((self.manager.scope(self.root) / (first['id'] + '.zip')).read_bytes(), original)
        for step in (1, 2):
            destination = Path(self.temporary.name) / f'new-save-root-{step}'
            destination.mkdir()
            self.clock += 86400
            imported = self.manager.import_archive(destination, raw)
            self.assertEqual(imported['id'], first['id'])
            self.assertEqual(imported['label'], '首领之前 <保留>')
            self.assertTrue(imported['locked'])
            self.assertEqual(imported['time'], 10000)
            self.assertEqual(imported['last_seen'], 10030)
            self.assertEqual(imported['imported_at'], self.clock)
            self.assertFalse((destination / 'game1').exists())
            self.assertEqual(self.manager.events(destination), [])
            self.assertIsNone(self.manager.snapshot(destination)['slots'][0]['nodes'][0]['backup'])
            raw, _ = self.manager.export(destination, imported)
        self.manage(destination, {**imported, 'label': '本机选择', 'locked': False})
        self.clock += 10
        again = self.manager.import_archive(destination, raw)
        self.assertEqual(again['label'], '本机选择')
        self.assertFalse(again['locked'])
        self.assertEqual((again['time'], again['last_seen']), (10000, 10030))
        self.assertEqual(again['imported_at'], self.clock)

    def test_legacy_import_marks_unknown_observations_until_actual_live_capture(self):
        self.manager.tick(self.root)
        first = self.manager.history(self.root)[0]
        raw = (self.manager.scope(self.root) / (first['id'] + '.zip')).read_bytes()
        destination = Path(self.temporary.name) / 'legacy-import'
        destination.mkdir()
        self.clock += 100
        imported = self.manager.import_archive(destination, raw)
        self.assertEqual(imported['recovered_at'], self.clock)
        from io import BytesIO
        exported, _ = self.manager.export(destination, imported)
        with ZipFile(BytesIO(exported)) as archive:
            transfer = json.loads(archive.read('manifest.json'))['transfer']
        self.assertIsNone(transfer['first_observed'])
        self.assertIsNone(transfer['last_observed'])
        shutil.copytree(self.root / 'game1', destination / 'game1')
        self.clock += 100
        self.manager.tick(destination, force=True)
        captured = self.manager.selected(destination, imported)
        self.assertNotIn('recovered_at', captured)
        self.assertEqual((captured['time'], captured['last_seen']), (self.clock, self.clock))

    def test_invalid_transfer_metadata_rejects_without_changing_game_or_history(self):
        from io import BytesIO
        self.manager.tick(self.root)
        first = self.manager.history(self.root)[0]
        raw, _ = self.manager.export(self.root, first)
        with ZipFile(BytesIO(raw)) as archive:
            metadata = json.loads(archive.read('manifest.json'))
            contents = {name: archive.read(name) for name in metadata['files']}
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        indexes = {p.name: p.read_bytes() for p in self.manager.scope(self.root).glob('*.json')}
        for change in ({'label': 'unsafe\nlabel'}, {'label': 'x' * 81}, {'locked': 1},
                       {'first_observed': float('nan')}, {'last_observed': 0}, {'first_observed': None},
                       {'last_observed': True}):
            with self.subTest(change=change):
                malformed = {**metadata, 'transfer': {**metadata['transfer'], **change}}
                output = BytesIO()
                with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
                    archive.writestr('manifest.json', json.dumps(malformed))
                    for name, data in contents.items():
                        archive.writestr(name, data)
                with self.assertRaisesRegex(ValueError, '原观察时间无效'):
                    self.manager.import_archive(self.root, output.getvalue())
                self.assertEqual(before, {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
                self.assertEqual(indexes, {p.name: p.read_bytes() for p in self.manager.scope(self.root).glob('*.json')})

    def test_aged_save_remains_explicitly_protected_and_errors_do_not_borrow_protection(self):
        self.clock = 1700000020
        self.manager.tick(self.root)
        self.clock += 61
        old = self.manager.health_status(self.root, 1)
        self.assertEqual(old['state'], 'waiting')
        self.assertTrue(old['last_save_protected'])
        self.assertTrue(self.manager.snapshot(self.root)['last_save_protected'])
        self.assertFalse(self.manager.health_status(self.root, 2)['last_save_protected'])
        (self.root / 'game1/game.dat').write_bytes(b'broken')
        self.clock += 10
        self.manager.tick(self.root)
        self.assertEqual(self.manager.health_status(self.root, 1)['state'], 'blocked')
        self.assertFalse(self.manager.health_status(self.root, 1)['last_save_protected'])


if __name__ == "__main__":
    unittest.main()

