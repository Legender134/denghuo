"""Own-widget checks; no input injection or control of other applications."""
import gc
import os
from pathlib import Path
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from queue import Queue

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
    def test_waiting_tooltip_changes_when_the_previous_save_becomes_protected(self):
        tray=Tray.__new__(Tray);tray.icon=Mock();tray.state=None
        tray.update({'state':'waiting','last_save_protected':False})
        self.assertNotIn('上次保存已备份',tray.icon.title)
        tray.update({'state':'waiting','last_save_protected':True})
        self.assertIn('上次保存已备份',tray.icon.title)
        tray.icon.notify.assert_not_called()
        tray.update({'state':'paused','last_save_protected':True})
        self.assertIn('已暂停',tray.icon.title)

    def test_only_one_failure_toast_per_blocked_episode(self):
        tray=Tray.__new__(Tray);tray.icon=Mock();tray.state=None
        for health in ({'state':'protected'}, {'state':'blocked','error':'first'},
                       {'state':'blocked','error':'second'}, {'state':'protected'},
                       {'state':'blocked','error':'third'}):tray.update(health)
        self.assertEqual(tray.icon.notify.call_count,2)
        self.assertEqual(tray.icon.notify.call_args.args[0],'third')


@unittest.skipUnless(tk is not None, 'Tk display controller import')
class PassiveOwnershipTests(unittest.TestCase):
    def test_unlock_uses_the_native_window_and_preserves_legacy_fallback(self):
        for ready in (True, False):
            with self.subTest(ready=ready):
                ui = SimpleNamespace(host=SimpleNamespace(ready=ready), show=Mock())
                play = PlayDisplay.__new__(PlayDisplay)
                play.manager = SimpleNamespace(native_ui=ui, hide_to_tray=Mock())
                play.editing, play.drag = False, None
                play.unlock_layout(persist=False)
                if ready:
                    ui.show.assert_called_once(); play.manager.hide_to_tray.assert_not_called()
                    self.assertFalse(play.editing)
                else:
                    ui.show.assert_not_called(); play.manager.hide_to_tray.assert_called_once()
                    self.assertTrue(play.editing)

    def test_native_workspace_and_handle_suppress_old_cards_with_fallback_preserved(self):
        from companion.play_state import PLAY_DEFAULTS
        for ready in (True, False):
            for collapsed in (True, False):
                for burning in (True, False):
                    with self.subTest(ready=ready, collapsed=collapsed, burning=burning):
                        game = {'rect': (0, 0, 1280, 720)}
                        host = SimpleNamespace(process=SimpleNamespace(pid=2), ready=ready, visibility={'manager': ready})
                        ui = SimpleNamespace(host=host, companion_collapsed=collapsed, track_game=Mock())
                        play = PlayDisplay.__new__(PlayDisplay)
                        play.manager = SimpleNamespace(root=SimpleNamespace(after=Mock()), native_ui=ui)
                        play.native = SimpleNamespace(game=lambda: game, remembered_game=lambda: game,
                                                      foreground=lambda: 1, process=lambda _: 1)
                        play.closed, play.lookup = False, None
                        play.worker = SimpleNamespace(results=Queue())
                        play.state = dict(PLAY_DEFAULTS)
                        play.snap = {'data': {'tips': [{'id': 'burning'}] if burning else []}}
                        play.status, play.notice, play.peek = Mock(), Mock(), Mock()
                        play.draw = Mock()
                        play.poll()
                        ui.track_game.assert_called_once_with(game, True)
                        if ready:
                            play.draw.assert_not_called()
                            for card in (play.status, play.notice, play.peek): card.hide.assert_called_once()
                        else:
                            play.draw.assert_called_once()


@unittest.skipUnless(tk is not None and os.name=='nt','Windows passive display component')
class PlayOverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp=SimpleNamespace(name=tempfile.mkdtemp(prefix='lamp-play-component-'))
        self.session=Session(Path(self.temp.name)/'settings.json')
        self.session.update_settings({'save_root':self.temp.name,'always_on_top':False})
        self.session.update_manual({'hp':20,'ht':30})
        try:
            with patch('companion.native_manager.NativeHost'):
                self.manager=Overlay(self.session,'http://127.0.0.1:1/',visible=False)
        except tk.TclError as exc:self.skipTest(str(exc))
        self.native=WindowsDisplay()
        self.play=PlayDisplay(self.manager,self.native)
        self.manager.play=self.play
        self.addCleanup(self.close_fixture)

    def close_fixture(self):
        self.session.stop.set()
        self.manager.destroy_window()
        self.manager=self.play=None
        gc.collect()  # Dispose Tk fixture cycles on the thread that created them.

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

    def test_default_game_display_shows_conditional_advice_without_repeating_health(self):
        self.session.update_manual({'hp':4,'ht':30,'buffs':['Burning']})
        self.play.update(self.session.snapshot())
        self.play.game={'rect':(0,0,1280,720)}
        self.play.draw()
        self.assertTrue(self.play.status.visible)
        self.assertFalse(self.play.peek_open)
        summary=self.play.status.labels[1].cget('text')
        self.assertNotIn('HP 4/30',summary)
        self.assertIn('接触水',summary)
        self.assertNotIn('危险血量',summary)

    def test_healthy_game_display_keeps_class_advice_in_full_reference(self):
        self.play.update(self.session.snapshot())
        self.play.game={'rect':(0,0,1280,720)}
        self.play.draw()
        summary=self.play.status.labels[1].cget('text')
        self.assertEqual('',summary)
        self.assertNotIn('战士：检查纹章和护甲',summary)
        self.assertIn('战士：检查纹章和护甲',str(self.session.data['tips']))

    def test_game_cards_never_overlap_and_small_space_retains_source_and_backup(self):
        from companion.quick_reference import peek_reference
        self.session.update_manual({'hp':4,'ht':30,'level':5,'buffs':['Burning']})
        self.session.data['items']=[{'location':'主武器','name':'单手剑 +2','key':'items.weapon.melee.sword',
                                    'known':True,'available':True,'level':2,'level_known':True}]
        snap=self.session.snapshot();snap['backup_health']={'state':'paused'}
        data=peek_reference(self.session,snap)
        self.play.snap=snap
        for font in (1,2):
            for anchor in ('top_left','top_right','bottom_left','bottom_right'):
                for offset in (100,500):
                    with self.subTest(font=font,anchor=anchor,offset=offset):
                        rect=(0,0,1000,800);self.play.game={'rect':rect}
                        self.play.state={**self.play.state,'font_scale':font,'anchor':anchor,'offset_y':offset}
                        self.play.peek_open=True
                        self.play.peek_key=snap['revision'],snap.get('error'),snap['stale'],repr(self.play.pinned)
                        self.play.peek_data=data
                        self.play.draw()
                        cards=[card for card in (self.play.status,self.play.peek) if card.visible]
                        self.assertTrue(cards)
                        for card in cards:
                            x,y,w,h,_=card.geometry
                            self.assertGreaterEqual(x,0);self.assertGreaterEqual(y,0)
                            self.assertLessEqual(x+w,rect[2]);self.assertLessEqual(y+h,rect[3])
                        if len(cards)==2:
                            a,b=(card.geometry for card in cards)
                            self.assertTrue(a[1]+a[3]<=b[1] or b[1]+b[3]<=a[1])
                        text='\n'.join(label.cget('text') for card in cards for label in card.labels)
                        self.assertIn('备份暂停',text);self.assertIn('手填局势',text)
                        self.play.peek_open=False;self.play.draw()
                        self.assertTrue(self.play.status.visible);self.assertFalse(self.play.peek.visible)


if __name__ == '__main__': unittest.main()
