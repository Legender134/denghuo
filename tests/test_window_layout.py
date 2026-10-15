import json
from pathlib import Path
import tempfile
import unittest

from companion.window_layout import DEFAULT, LEGACY_KEYS, WindowLayout, validate


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
        layout.update(values); self.assertTrue(layout.flush(5)); self.assertTrue(layout.close())
        reopened = WindowLayout(self.config); self.addCleanup(reopened.close)
        self.assertEqual(reopened.values, values)
        self.assertEqual(self.config.read_bytes(), b'personal settings unchanged')

    def test_external_changes_are_preserved_until_explicit_layout_reset(self):
        self.path.write_text(json.dumps(DEFAULT), encoding='utf8')
        layout = WindowLayout(self.config)
        original = b'{externally damaged layout'
        self.path.write_bytes(original)
        layout.update({**DEFAULT, 'width': 700}); self.assertTrue(layout.flush(5)); self.assertTrue(layout.close())
        self.assertEqual(self.path.read_bytes(), original); self.assertTrue(layout.error)
        reset = WindowLayout(self.config); reset.update(DEFAULT, reset=True); self.assertTrue(reset.flush(5)); self.assertTrue(reset.close())
        self.assertEqual(json.loads(self.path.read_bytes()), DEFAULT)
        preserved = list(self.path.parent.glob('companion-window.before-reset-*.json'))
        self.assertEqual(len(preserved), 1); self.assertEqual(preserved[0].read_bytes(), original)

    def test_startup_alone_does_not_create_or_replace_geometry(self):
        layout = WindowLayout(self.config); layout.close(); self.assertFalse(self.path.exists())

    def test_bad_dimensions_and_pages_cannot_publish_partial_layout(self):
        for patch in ({'width': True}, {'height': 0}, {'page': 'unknown'}, {'collapsed': 1}, {'x': '20'}, {'x': 20},
                      {'brief_width': 0}, {'brief_height': True}, {'brief_auto': 1}, {'text_scale': 120}):
            with self.subTest(patch=patch), self.assertRaises(ValueError): validate({**DEFAULT, **patch})

    def test_legacy_custom_size_position_and_page_are_preserved(self):
        legacy = {key: DEFAULT[key] for key in LEGACY_KEYS}
        legacy.update(width=620, height=700, x=-310, y=100, page='lookup', collapsed=True)
        original = json.dumps(legacy).encode('utf-8')
        self.path.write_bytes(original)
        layout = WindowLayout(self.config); self.addCleanup(layout.close)
        self.assertEqual({key: layout.values[key] for key in LEGACY_KEYS}, legacy)
        self.assertEqual((layout.values['brief_width'], layout.values['brief_height']), (620, 700))
        self.assertFalse(layout.values['brief_auto'])
        self.assertEqual(self.path.read_bytes(), original)

    def test_brief_and_reader_sizes_and_scale_survive_independently(self):
        values = {**DEFAULT, 'width': 720, 'height': 800, 'brief_width': 330,
                  'brief_height': 210, 'brief_auto': False, 'text_scale': 130, 'page': 'overview'}
        layout = WindowLayout(self.config)
        layout.update(values); self.assertTrue(layout.flush(5)); self.assertTrue(layout.close())
        reopened = WindowLayout(self.config); self.addCleanup(reopened.close)
        self.assertEqual(reopened.values, values)
