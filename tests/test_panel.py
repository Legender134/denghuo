import unittest
from unittest.mock import Mock
from companion.panel import PanelBridge


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.now=100
        self.open=Mock()
        self.bridge=PanelBridge(lambda:self.now,self.open)
        self.bridge.bind('http://127.0.0.1:123/')
        self.client='0123456789abcdef'

    def test_connected_panel_receives_requests_without_new_tabs(self):
        self.bridge.heartbeat(self.client)
        for page in ('library','backups','overview'):
            self.bridge.request(page)
            command=self.bridge.heartbeat(self.client)
            self.assertEqual(command['page'],page)
            self.bridge.heartbeat(self.client,command['serial'])
        self.open.assert_not_called()

    def test_rapid_clicks_before_browser_connects_route_to_first_tab(self):
        self.bridge.request('library');self.bridge.request('backups')
        self.open.assert_called_once_with('http://127.0.0.1:123/#library')
        self.assertEqual(self.bridge.heartbeat(self.client)['page'],'backups')

    def test_closed_or_nonresponsive_panel_falls_back_once(self):
        self.bridge.heartbeat(self.client);self.bridge.request('backups')
        self.now+=7;self.bridge.tick();self.bridge.tick()
        self.open.assert_called_once_with('http://127.0.0.1:123/#backups')

    def test_other_tab_cannot_acknowledge_target_request(self):
        self.bridge.heartbeat(self.client);self.bridge.request('library')
        command=self.bridge.heartbeat(self.client)
        self.assertIsNone(self.bridge.heartbeat('abcdef0123456789',command['serial']))
        self.assertEqual(self.bridge.heartbeat(self.client)['page'],'library')

    def test_invalid_page_or_client_rejected(self):
        with self.assertRaises(ValueError):self.bridge.request('https://example.com')
        with self.assertRaises(ValueError):self.bridge.heartbeat('../settings')
