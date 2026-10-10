from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import logging
import os
from pathlib import Path
import signal
import threading
import time
from urllib.request import urlopen, Request
import webbrowser

from .server import Server
from .service import Session, ROOT
from .paths import data_directory, migrate_data
from .panel import BrowserOpenError
import sys


def port_number(value):
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('端口应为 0–65535 的整数') from exc
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError('端口应为 0–65535 的整数')
    return port


def open_existing(runtime_path, timeout=3, *, web=False, no_overlay=False):
    """A second click can precede the first process publishing its address."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            info = json.loads(runtime_path.read_text(encoding='utf-8'))
            port = int(info['port'])
            if not 1 <= port <= 65535:
                raise ValueError('invalid runtime port')
            url = f'http://127.0.0.1:{port}'
            with urlopen(url + '/api/status', timeout=.4) as response:
                state = json.load(response)
            if not isinstance(state, dict) or 'catalog_version' not in state or state.get('stopped'):
                raise ValueError('助手服务尚未就绪')
            if state.get('manager_reuse') or state.get('panel_reuse'):
                native = state.get('settings', {}).get('startup_surface', 'panel') == 'native'
                action = 'show' if native and state.get('manager_reuse') and not (web or no_overlay) else 'open'
                request = Request(url+'/api/panel', data=json.dumps({'action':action}).encode(),
                                  headers={'Content-Type':'application/json','X-Companion-Token':state['token']})
                with urlopen(request, timeout=2) as response:
                    result = json.load(response)
                    if result.get('ok') is not True:
                        raise ValueError('已有助手未能打开入口')
            else:
                if not webbrowser.open(url):
                    raise ValueError('浏览器未能打开完整面板：'+url)
            return
        except (OSError, ValueError, KeyError, TypeError):
            if time.monotonic() >= deadline:
                raise RuntimeError('已有灯火入口未能打开，请稍后重试；可手动访问完整面板：'+url if 'url' in locals() else
                                   '另一个灯火进程正在启动或关闭，请稍后重新双击启动。') from None
            time.sleep(.1)


def main(argv=None):
    parser = argparse.ArgumentParser(description="灯火 · 破碎的像素地牢本地助手")
    parser.add_argument("--web", action="store_true", help="打开完整网页面板（推荐键盘与读屏使用；原生Tk读屏支持有限）")
    parser.add_argument("--no-overlay", action="store_true", help="仅运行网页服务，不启用原生桌面辅助")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--start-hidden", action="store_true", help="后台启动，不自动显示网页或管理窗口；原生辅助启用时保留托盘、快捷键与游玩显示")
    parser.add_argument("--port", type=port_number, default=0)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--stop-at", help="可选的助手停止时间，如 2026-10-03T02:00:00+08:00")
    args = parser.parse_args(argv)
    if args.web and (args.no_browser or args.start_hidden):
        parser.error("--web 不能与 --no-browser 或 --start-hidden 同时使用")
    local = args.config.parent if args.config else data_directory()
    mutex = kernel = session = server = monitor = http = None
    owned_handlers = []
    try:
        if os.name == "nt" and args.config is None:
            name = "Local\\DungeonCompanion_" + hashlib.sha256(str(local).encode()).hexdigest()[:16]
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
            kernel.CreateMutexW.restype = ctypes.c_void_p
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            mutex = kernel.CreateMutexW(None, False, name)
            if not mutex:
                raise ctypes.WinError(ctypes.get_last_error())
            if ctypes.get_last_error() == 183:
                if not args.no_browser and not args.start_hidden:
                    open_existing(local/"runtime.json", web=args.web, no_overlay=args.no_overlay)
                return
        if getattr(sys, 'frozen', False) and args.config is None:
            migrate_data(local, [Path(sys.executable).parent/'.local', Path.cwd()/'.local'])
        local.mkdir(exist_ok=True, parents=True)
        previous_handlers = tuple(logging.getLogger().handlers)
        logging.basicConfig(filename=local/"companion.log", level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
        owned_handlers = [h for h in logging.getLogger().handlers if h not in previous_handlers]
        session = Session(config_path=args.config)
        file_handlers = [h for h in logging.getLogger().handlers if isinstance(h, logging.FileHandler)]
        session.log_path = Path(file_handlers[0].baseFilename) if file_handlers else None
        session.manager_available = not args.no_overlay
        if args.stop_at:
            session.update_settings({"stop_at": args.stop_at})
        session.refresh()
        server = Server(session, args.port)
        url = server.origin + "/"
        runtime_path = args.config.with_suffix(".runtime.json") if args.config else local/"runtime.json"
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        pending = runtime_path.with_suffix(".tmp")
        pending.write_text(json.dumps({"pid": os.getpid(), "port": server.server_port, "url": url}), encoding="utf-8")
        pending.replace(runtime_path)
        logging.info("Started pid=%s url=%s", os.getpid(), url)
        signal.signal(signal.SIGINT, lambda *_: session.stop.set())
        signal.signal(signal.SIGTERM, lambda *_: session.stop.set())
        monitor = threading.Thread(target=session.run, daemon=True, name="save-monitor")
        http = threading.Thread(target=server.serve_forever, daemon=True, name="dashboard")
        monitor.start()
        http.start()
        panel_start = not (args.no_browser or args.start_hidden) and (
            args.web or args.no_overlay or session.settings.get('startup_surface', 'panel') == 'panel')
        if panel_start:
            try:
                session.panel.request()
            except BrowserOpenError as exc:
                if args.web or args.no_overlay:
                    raise RuntimeError('默认浏览器未能打开，助手服务已关闭。请检查默认浏览器后重试，或使用普通启动入口打开管理窗口。') from exc
                notice = '浏览器未能打开，已显示管理窗口。完整面板仍可手动访问：'+url
                session.configuration_notice = ' '.join(filter(None, (session.configuration_notice, notice)))
                logging.warning('Browser unavailable; showing native manager at %s', url)
                panel_start = False
        if args.no_overlay:
            session.stop.wait()
        else:
            from .overlay import Overlay
            try:
                if os.name == "nt":
                    ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except (OSError, AttributeError):
                pass
            Overlay(session, url, start_hidden=args.start_hidden or panel_start).run()
    finally:
        if session is not None:
            session.stop.set()
            session.prepare_shutdown()
        if server is not None:
            # shutdown() must only run after serve_forever has started.
            if http is not None and http.is_alive():
                server.shutdown()
            server.server_close()
        for thread in (monitor, http):
            if thread is not None and thread.ident is not None:
                thread.join(timeout=3)
        if mutex:
            kernel.CloseHandle(mutex)
        if session is not None:
            logging.info("Stopped")
        for handler in owned_handlers:
            logging.getLogger().removeHandler(handler)
            handler.close()


def entrypoint(argv=None):
    try:
        main(argv)
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        logging.exception('Application failed')
        from .diagnostics import report_failure
        report_failure(exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(entrypoint())
