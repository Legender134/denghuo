"""Own-widget checks; no input injection or control of other applications."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from companion.service import Session
from companion.tray import Tray

try:
    import tkinter as tk
    from companion.overlay import Overlay
    from companion.play_overlay import PlayDisplay
    from companion.play_settings import PlaySettings
    from companion.windows import WindowsDisplay, NOACTIVATE, TRANSPARENT, TOOLWINDOW
except ImportError:
    tk=None


class TrayNoticeTests(unittest.TestCase):
    def test_only_one_failure_toast_per_blocked_episode(self):
        tray=Tray.__new__(Tray);tray.icon=Mock();tray.state=None
        for health in ({'state':'protected'}, {'state':'blocked','error':'first'},
                       {'state':'blocked','error':'second'}, {'state':'protected'},
                       {'state':'blocked','error':'third'}):tray.update(health)
        self.assertEqual(tray.icon.notify.call_count,2)
        self.assertEqual(tray.icon.notify.call_args.args[0],'third')


@unittest.skipUnless(tk is not None and os.name=='nt','Windows/Tk display component')
class PlayOverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='lamp-play-component-')
        self.addCleanup(self.temp.cleanup)
        self.session=Session(Path(self.temp.name)/'settings.json')
        self.session.update_settings({'save_root':self.temp.name,'always_on_top':False})
        self.session.update_manual({'hp':20,'ht':30})
        try:self.manager=Overlay(self.session,'http://127.0.0.1:1/',visible=False)
        except tk.TclError as exc:self.skipTest(str(exc))
        self.native=WindowsDisplay()
        self.play=PlayDisplay(self.manager,self.native)
        self.manager.play=self.play
        self.addCleanup(self.manager.close)

    def await_result(self):
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            self.manager.root.update()
            if self.play.lookup.rendered is not None:return
            time.sleep(.01)
        self.fail('numeric worker did not deliver')

    def test_passive_window_styles_are_ours_and_do_not_activate(self):
        before=self.native.foreground()
        card=self.play.status
        width,height=card.content('受控显示验收','','',1,290)
        card.show(0,0,width,height)
        self.manager.root.update_idletasks()
        self.assertEqual(self.native.foreground(),before)
        for widget in (card.window,card.background):
            style=self.native.style(widget)
            self.assertEqual(style & (NOACTIVATE|TRANSPARENT|TOOLWINDOW),NOACTIVATE|TRANSPARENT|TOOLWINDOW)
            self.assertTrue(self.native.is_own(self.native.hwnd(widget)))
        card.show(0,0,width,height,editing=True)
        self.assertFalse(self.native.style(card.window)&TRANSPARENT)
        self.assertTrue(self.native.style(card.background)&TRANSPARENT)
        card.hide();self.assertFalse(card.visible)

    def test_lookup_dirty_parameters_block_old_values_and_pin(self):
        self.play.open_lookup();lookup=self.play.lookup
        entry=next(x for x in self.session.catalog.entries if x['id']=='items.potions.potionofhealing')
        lookup.rows=[entry];lookup.list.delete(0,'end');lookup.list.insert(0,entry['name']);lookup.list.selection_set(0)
        lookup.select();self.await_result()
        self.assertIn('治疗池总量',lookup.text.get('1.0','end'))
        lookup.variables['max_hp'].set('100');lookup.variables['hp'].set('10')
        self.assertTrue(lookup.dirty);self.assertNotIn('治疗池总量',lookup.text.get('1.0','end'))
        lookup.pin();self.assertIsNone(self.play.pinned)
        lookup.calculate();lookup.rendered=None;self.await_result();lookup.pin()
        self.assertEqual(self.play.pinned[1]['max_hp'],100)
        self.assertIn('90',lookup.text.get('1.0','end'))
        lookup.clear_pin();self.assertIsNone(self.play.pinned)
        lookup.variables['hp'].set('')
        ticket=lookup.ticket;lookup.calculate();self.assertEqual(lookup.ticket,ticket)
        self.assertTrue(lookup.dirty)

    def test_late_results_after_edits_are_not_rendered(self):
        self.play.open_lookup();lookup=self.play.lookup
        detail=self.session.values.detail('items.potions.potionofhealing')
        lookup.identity=detail['id'];lookup.render(detail)
        lookup.submitted={key:var.get() for key,var in lookup.variables.items()}
        lookup.variables['hp'].set('1');lookup.render(detail)
        self.assertTrue(lookup.dirty);self.assertNotIn('治疗池总量',lookup.text.get('1.0','end'))

    def test_reopening_lookup_preserves_its_return_target_and_quick_key_closes_it(self):
        self.play.open_lookup();lookup=self.play.lookup
        target={'hwnd':123,'pid':456}
        lookup.return_target=target
        with patch.object(self.native,'game',return_value=None):lookup.show()
        self.assertEqual(lookup.return_target,target)
        with patch.object(self.native,'foreground',return_value=self.native.hwnd(lookup.window)), \
             patch.object(self.native,'return_to_game') as back:
            self.play.toggle_peek()
        back.assert_called_once_with(target);self.assertFalse(lookup.visible())

    def test_settings_scroll_and_invalid_unlock_does_not_hide_manager(self):
        settings=PlaySettings(self.manager);self.addCleanup(settings.window.destroy)
        self.assertTrue(settings.window.attributes('-topmost'))
        settings.vars['opacity'].set('0')
        with patch.object(self.play,'unlock_layout') as unlock:settings.unlock()
        unlock.assert_not_called();self.assertIn('超出范围',settings.status.cget('text'))
        settings.vars['opacity'].set('0.75');self.assertTrue(settings.save())
        self.assertEqual(self.play.state['opacity'],.75)

    def test_shutdown_cancels_poll_and_destroys_all_cards(self):
        cards=[self.play.status.window,self.play.notice.window,self.play.peek.window]
        self.play.close()
        self.assertIsNone(self.play.timer);self.assertTrue(self.play.worker.stop.is_set())
        for card in cards:self.assertFalse(card.winfo_exists())
        self.manager.play=None


if __name__=='__main__':unittest.main()
