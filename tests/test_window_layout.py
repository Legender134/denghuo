import json
from pathlib import Path
import tempfile
import unittest

from companion.window_layout import DEFAULT, WindowLayout, validate


class WindowLayoutTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='lamp-window-layout-')
        self.addCleanup(self.directory.cleanup)
        self.config = Path(self.directory.name)/'settings.json'
        self.path = self.config.with_name('companion-window.json')

    def test_layout_and_collapsed_page_survive_restart_without_touching_preferences(self):
        self.config.write_bytes(b'personal settings unchanged')
        layout = WindowLayout(self.config)
        values = {**DEFAULT, 'width': 650, 'height': 720, 'x': -300, 'y': 80, 'game_x': 45, 'collapsed': True, 'page': 'alchemy'}
        layout.update(values); layout.close()
        reopened = WindowLayout(self.config); self.addCleanup(reopened.close)
        self.assertEqual(reopened.values, values)
        self.assertEqual(self.config.read_bytes(), b'personal settings unchanged')

    def test_external_changes_are_preserved_until_explicit_layout_reset(self):
        self.path.write_text(json.dumps(DEFAULT), encoding='utf8')
        layout = WindowLayout(self.config)
        original = b'{externally damaged layout'
        self.path.write_bytes(original)
        layout.update({**DEFAULT, 'width': 700}); layout.close()
        self.assertEqual(self.path.read_bytes(), original); self.assertTrue(layout.error)
        reset = WindowLayout(self.config); reset.update(DEFAULT, reset=True); reset.close()
        self.assertEqual(json.loads(self.path.read_bytes()), DEFAULT)
        preserved = list(self.path.parent.glob('companion-window.before-reset-*.json'))
        self.assertEqual(len(preserved), 1); self.assertEqual(preserved[0].read_bytes(), original)

    def test_startup_alone_does_not_create_or_replace_geometry(self):
        layout = WindowLayout(self.config); layout.close(); self.assertFalse(self.path.exists())

    def test_bad_dimensions_and_pages_cannot_publish_partial_layout(self):
        for patch in ({'width': True}, {'height': 0}, {'page': 'unknown'}, {'collapsed': 1}, {'x': '20'}, {'x': 20}):
            with self.subTest(patch=patch), self.assertRaises(ValueError): validate({**DEFAULT, **patch})
