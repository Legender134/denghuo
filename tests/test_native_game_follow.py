"""Regression checks for helper startup and bounded transport retries."""
import unittest
from types import SimpleNamespace
from companion.native_manager import NativeManager


class GameFollowTests(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.accept = True
        self.host = SimpleNamespace(ready=False, process=SimpleNamespace(pid=101), command=self.send)
        self.ui = NativeManager.__new__(NativeManager)
        self.ui.host = self.host
        self.game = {'rect': (0, 0, 1920, 1080)}

    def send(self, action, **payload):
        self.sent.append((action, payload))
        return self.accept

    def test_ready_and_replacement_helper_receive_unchanged_bounds(self):
        self.ui.track_game(self.game, True)
        self.ui.track_game(self.game, True)
        self.assertEqual(len(self.sent), 1)
        self.host.ready = True
        self.ui.track_game(self.game, True)
        self.assertEqual(len(self.sent), 2)
        self.host.process.pid = 202
        self.ui.track_game(self.game, True)
        self.assertEqual(len(self.sent), 3)
        self.ui.track_game(self.game, False)
        self.assertFalse(self.sent[-1][1]['visible'])

    def test_rejected_message_is_retried_without_geometry_change(self):
        self.accept = False
        self.ui.track_game(self.game, True)
        self.accept = True
        self.ui.track_game(self.game, True)
        self.ui.track_game(self.game, True)
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.sent[0], self.sent[1])
        self.ui.track_game(None, False)
        self.assertEqual(self.sent[-1][1], {'rect': [], 'visible': False})
