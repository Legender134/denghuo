"""Route repeated desktop entry points to the most recently connected panel."""
import re
import threading
import time
import webbrowser

PAGES = {'overview','inventory','library','backups','manual','settings','workspace','help','play-settings','alchemy','migration'}


class BrowserOpenError(ValueError):
    """The operating system could not open the requested browser entry."""


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

    def request(self, page='overview', plan_id=None):
        if page not in PAGES:
            raise ValueError('不支持的面板页面')
        if plan_id is not None and (page != 'workspace' or not isinstance(plan_id, str) or not re.fullmatch(r'[a-f0-9]{32}', plan_id)):
            raise ValueError('所选方案身份不正确，请重新打开方案列表')
        with self.lock:
            now = self.clock()
            alive = [key for key, stamp in self.clients.items() if now-stamp < 90]
            target = max(alive, key=self.clients.get) if alive else None
            self.serial += 1
            self.pending = {'serial':self.serial,'page':page,'client':target,'time':now, 'plan_id':plan_id}
            if target is None and now-self.last_open >= 6:
                try:
                    self._open(page, plan_id)
                except Exception:
                    self.pending = None
                    raise

    def _open(self, page, plan_id=None):
        if not self.url:
            raise ValueError('完整面板地址尚未就绪')
        url = self.url+('?' + 'plan=' + plan_id if plan_id else '')+('#'+page if page!='overview' else '')
        try:
            opened = (self.opener or webbrowser.open)(url)
        except Exception as exc:
            raise BrowserOpenError('浏览器未能打开完整面板：'+url) from exc
        if not opened:
            raise BrowserOpenError('浏览器未能打开完整面板：'+url)
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
                    return {'serial':self.pending['serial'],'page':self.pending['page'], **({'plan_id':self.pending['plan_id']} if self.pending.get('plan_id') else {})}
            return None

    def tick(self):
        with self.lock:
            if self.pending and self.clock()-self.pending['time'] >= 6 and self.clock()-self.last_open >= 6:
                page, plan_id = self.pending['page'], self.pending.get('plan_id')
                self.pending = None
                self._open(page, plan_id)
