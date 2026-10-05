"""Route repeated desktop entry points to the most recently connected panel."""
import re
import threading
import time
import webbrowser

PAGES = {'overview','inventory','library','backups','manual','settings'}


class PanelBridge:
    def __init__(self, clock=time.monotonic, opener=None):
        self.clock, self.opener = clock, opener
        self.lock = threading.RLock()
        self.url = ''
        self.clients = {}
        self.pending = None
        self.serial = 0
        self.last_open = -1000

    def bind(self, url):
        self.url = url.rstrip('/')+'/'

    def request(self, page='overview'):
        if page not in PAGES:
            raise ValueError('不支持的面板页面')
        with self.lock:
            now = self.clock()
            alive = [key for key, stamp in self.clients.items() if now-stamp < 90]
            target = max(alive, key=self.clients.get) if alive else None
            self.serial += 1
            self.pending = {'serial':self.serial,'page':page,'client':target,'time':now}
            if target is None and now-self.last_open >= 6:
                self._open(page)

    def _open(self, page):
        if not self.url:
            return
        (self.opener or webbrowser.open)(self.url+('#'+page if page!='overview' else ''))
        self.last_open = self.clock()

    def heartbeat(self, client, acknowledged=None):
        if not isinstance(client,str) or not re.fullmatch(r'[a-zA-Z0-9-]{16,64}',client):
            raise ValueError('面板连接编号无效')
        with self.lock:
            now = self.clock()
            self.clients = {key: stamp for key,stamp in self.clients.items() if now-stamp < 180}
            self.clients[client] = now
            if len(self.clients)>16:
                del self.clients[min(self.clients,key=self.clients.get)]
            if self.pending and self.pending['client'] is None:
                self.pending['client'] = client
            if self.pending and self.pending['client']==client:
                if type(acknowledged) is int and acknowledged == self.pending['serial']:
                    self.pending = None
                else:
                    return {'serial':self.pending['serial'],'page':self.pending['page']}
            return None

    def tick(self):
        with self.lock:
            if self.pending and self.clock()-self.pending['time'] >= 6 and self.clock()-self.last_open >= 6:
                page = self.pending['page']
                self.pending = None
                self._open(page)
