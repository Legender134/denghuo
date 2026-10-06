"""Windows tray integration; callbacks only enqueue commands for Tk."""
from queue import Queue


class Tray:
    def __init__(self, commands: Queue):
        import pystray
        from PIL import Image
        from .paths import ROOT
        with Image.open(ROOT/'data/lamp.png') as original:
            image = original.convert('RGBA').resize((64,64))
        def command(name):
            return lambda icon, item: commands.put((name, None))
        self.icon = pystray.Icon('Denghuo', image, '灯火 · 自动备份监控中', menu=pystray.Menu(
            pystray.MenuItem('显示悬浮窗', command('show'), default=True),
            pystray.MenuItem('打开完整面板', command('panel')),
            pystray.MenuItem('立即备份', command('capture')),
            pystray.MenuItem('查看存档历史', command('backups')),
            pystray.MenuItem('数值速查', command('quick')),
            pystray.MenuItem('开关游玩显示', command('play_toggle')),
            pystray.MenuItem('游玩设置', command('play_settings')),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('退出灯火（停止备份）', command('exit'))))
        self.icon.run_detached()
        self.state = None

    def update(self, health):
        state = (health.get('state'), health.get('error'))
        if state == self.state:
            return
        previous = self.state
        self.state = state
        names = {'paused':'自动备份已暂停', 'blocked':'自动备份受阻',
                 'waiting':'等待游戏保存', 'protected':'最近保存已备份'}
        self.icon.title = '灯火 · '+names.get(state[0], '正在检查备份')
        if state[0] == 'blocked' and (previous is None or previous[0] != 'blocked'):
            self.icon.notify(health.get('error') or '请检查存档目录与备份空间', '灯火：自动备份受阻')

    def stop(self):
        self.icon.stop()
