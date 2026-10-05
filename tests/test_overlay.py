"""Tk component checks use a withdrawn fixture; no desktop input automation."""
from pathlib import Path
import json
import tempfile
import time
import unittest
from unittest.mock import patch

from companion.service import Session

try:
    import tkinter as tk
    from companion.overlay import Overlay
except ImportError:
    tk = None


@unittest.skipIf(tk is None,'Tk is not installed')
class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='lamp-overlay-test-')
        self.addCleanup(self.temp.cleanup)
        self.session=Session(Path(self.temp.name)/'settings.json')
        self.session.update_settings({'always_on_top':False,'save_root':self.temp.name})
        self.session.update_manual({'hp':4,'ht':30,'buffs':['Burning']})
        try:
            self.overlay=Overlay(self.session,'http://127.0.0.1:1/',visible=False)
        except tk.TclError as exc:
            self.skipTest(str(exc))
        self.addCleanup(self.close_fixture)
        self.overlay.root.update_idletasks()

    def close_fixture(self):
        try:self.overlay.close()
        except tk.TclError:pass

    def test_compact_keeps_footer_and_restores_controls(self):
        overlay=self.overlay
        overlay.toggle_compact();overlay.tick()
        self.assertEqual(overlay.compact_button.cget('text'),'展开')
        self.assertEqual(overlay.controls.winfo_manager(),'')
        self.assertEqual(overlay.body.winfo_manager(),'')
        self.assertEqual(overlay.compact_tip.winfo_manager(),'pack')
        self.assertEqual(overlay.footer.winfo_manager(),'pack')
        self.assertEqual(len(overlay.cards.winfo_children()),1)
        overlay.toggle_compact();overlay.tick()
        self.assertEqual(overlay.compact_button.cget('text'),'收起')
        self.assertEqual(overlay.controls.winfo_manager(),'pack')
        self.assertEqual(overlay.body.winfo_manager(),'pack')
        self.assertGreater(len(overlay.cards.winfo_children()),1)

    def test_action_error_survives_status_refresh(self):
        def fail():raise OSError('受控设置写入失败')
        self.overlay.safely(fail);self.overlay.tick()
        self.assertEqual(self.overlay.status.cget('text'),'受控设置写入失败')
        self.overlay.safely(lambda:None);self.overlay.tick()
        self.assertNotIn('受控设置写入失败',self.overlay.status.cget('text'))

    def test_failed_pin_setting_restores_actual_checkbox_state(self):
        self.overlay.pin_var.set(True)
        with patch.object(self.session,'update_settings',side_effect=PermissionError('受控设置写入失败')):
            self.overlay.set_pin()
        self.assertFalse(self.overlay.pin_var.get())
        self.assertFalse(self.session.settings['always_on_top'])

    def test_manual_and_library_buttons_have_distinct_destinations(self):
        buttons={child.cget('text'):child for child in self.overlay.footer.winfo_children() if isinstance(child,tk.Button)}
        with patch.object(self.session.panel,'request') as browser:
            buttons['推演'].invoke();buttons['手册'].invoke()
        self.assertEqual([call.args[0] for call in browser.call_args_list],['manual','library'])

    def test_service_stop_closes_window_and_cancels_timer(self):
        self.session.stop.set();self.overlay.tick()
        self.assertIsNone(self.overlay.tick_id)
        with self.assertRaises(tk.TclError):self.overlay.root.winfo_exists()

    def test_close_control_keeps_monitoring_and_explicit_exit_stops(self):
        with patch.object(self.overlay.root,'iconify') as minimize:
            self.overlay.hide_to_tray()
        minimize.assert_called_once();self.assertFalse(self.session.stop.is_set())
        from unittest.mock import Mock
        self.overlay.tray=Mock()
        with patch.object(self.overlay.root,'withdraw') as hide:
            self.overlay.hide_to_tray()
        hide.assert_called_once();self.assertFalse(self.session.stop.is_set())
        self.overlay.close()
        self.assertTrue(self.session.stop.is_set())

    def test_high_dpi_window_dimensions_follow_point_font_scaling(self):
        with patch('tkinter.Misc.winfo_fpixels',return_value=192):
            overlay=Overlay(self.session,'http://127.0.0.1:1/',visible=False)
        try:
            self.assertEqual(overlay.ui_scale,2)
            self.assertEqual(overlay.minimum_size[0],650)
            self.assertGreaterEqual(overlay.expanded_size[0],650)
            self.assertEqual(overlay.pixels(250),500)
        finally:overlay.close()

    def test_saved_layout_clamps_offscreen_and_restores_compact(self):
        self.overlay.layout_path.write_text(json.dumps({'x':16000,'y':16000,'width':720,'height':900,
                            'scale':2,'compact':True}),encoding='utf-8')
        overlay=Overlay(self.session,'http://127.0.0.1:1/',visible=False)
        try:
            overlay.root.update_idletasks()
            self.assertTrue(overlay.compact)
            self.assertLessEqual(overlay.root.winfo_x()+overlay.expanded_size[0],overlay.root.winfo_screenwidth())
            self.assertEqual(overlay.controls.winfo_manager(),'')
        finally:overlay.destroy_window()

    def test_layout_persistence_keeps_expanded_size_and_user_settings(self):
        settings=self.session.config_path.read_bytes()
        # Normal state only in this disposable component fixture.
        self.overlay.root.deiconify();self.overlay.root.update_idletasks()
        self.overlay.toggle_compact();self.overlay.root.update_idletasks();self.overlay.remember_layout()
        row=json.loads(self.overlay.layout_path.read_text())
        self.assertTrue(row['compact'])
        self.assertEqual((row['width'],row['height']),self.overlay.expanded_size)
        self.assertEqual(self.session.config_path.read_bytes(),settings)
        self.overlay.root.withdraw()

    def test_compact_restart_preserves_saved_expanded_dimensions_before_mapping(self):
        self.overlay.layout_path.write_text(json.dumps({'x':100,'y':100,'width':600,'height':600,
                                                       'scale':1,'compact':True}),encoding='utf-8')
        with patch('tkinter.Misc.winfo_fpixels',return_value=96):
            overlay=Overlay(self.session,'http://127.0.0.1:1/',visible=False)
        try:
            self.assertTrue(overlay.compact)
            self.assertEqual(overlay.expanded_size,(600,600))
            overlay.toggle_compact();overlay.root.update_idletasks()
            self.assertFalse(overlay.compact)
            self.assertEqual(overlay.expanded_size,(600,600))
        finally:overlay.destroy_window()

    def test_tray_commands_run_on_tk_and_exit_stops_window(self):
        self.overlay.commands.put(('backups',None))
        with patch('companion.overlay.webbrowser.open') as browser:self.overlay.tick()
        browser.assert_called_once_with('http://127.0.0.1:1/#backups')
        self.overlay.commands.put(('exit',None));self.overlay.tick()
        self.assertTrue(self.session.stop.is_set())
        self.assertIsNone(self.overlay.tick_id)

    def test_stale_manual_status_requires_manual_update_and_preserves_unknown_resources(self):
        self.session.update_manual({'hp':4,'ht':30,'branch':1})
        self.session.modified=time.time()-65
        self.overlay.tick()
        self.assertIn('手动信息已过期',self.overlay.status.cget('text'))
        self.assertIn('重新填写',self.overlay.status.cget('text'))
        self.assertNotIn('保存游戏',self.overlay.status.cget('text'))
        self.assertIn('金币未填写',self.overlay.metrics.cget('text'))
        self.assertIn('支线',self.overlay.hero.cget('text'))


if __name__=='__main__':unittest.main()

