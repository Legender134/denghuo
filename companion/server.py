"""Loopback-only dashboard with explicitly confirmed, guarded save restoration."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import mimetypes
from pathlib import Path
import secrets
from urllib.parse import parse_qs, urlsplit
from .backups import MAX_TOTAL

WEB = Path(__file__).resolve().parents[1] / "web"


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, session, port=0):
        self.session = session
        self.token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), Handler)
        self.origin = f"http://127.0.0.1:{self.server_port}"
        session.panel.bind(self.origin)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logging.debug(format, *args)

    def send_data(self, payload, status=200, mime="application/json; charset=utf-8", filename=None):
        raw = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(raw)))
        if filename:
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def valid_host(self):
        return self.headers.get("Host") in (f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}")

    def do_GET(self):
        if not self.valid_host():
            self.send_data({"error": "Invalid host"}, 403)
            return
        url = urlsplit(self.path)
        if url.path == "/api/status":
            self.send_data({**self.server.session.snapshot(), "token": self.server.token})
        elif url.path == "/api/library":
            args = parse_qs(url.query)
            try:
                offset = int(args.get("offset", ["0"])[0])
                if not 0 <= offset <= 100000:
                    raise ValueError()
                self.send_data(self.server.session.catalog.search(args.get("q", [""])[0][:200], args.get("category", ["全部"])[0], offset=offset))
            except ValueError:
                self.send_data({"error": "页码不正确"}, 400)
        elif url.path == "/api/values":
            args = parse_qs(url.query)
            try:
                self.send_data(self.server.session.values.detail(args.get("id", [""])[0][:300],
                    {key: value[0] for key, value in args.items() if key != "id"}))
            except KeyError:
                self.send_data({"error": "暂未收录此条目的数值"}, 404)
            except (ValueError, OverflowError):
                self.send_data({"error": "请核对数值范围；当前生命不能超过最大生命"}, 400)
            except OSError:
                self.send_data({"error": "数值资料缺失，请完整解压后启动"}, 503)
        elif url.path == '/api/compare':
            from .values_decisions import compare_equipment
            try:
                self.send_data(compare_equipment(self.server.session.values,
                    {k: v[0] for k, v in parse_qs(url.query).items()}))
            except (ValueError, KeyError, OverflowError):
                self.send_data({'error': '请选择同类普通装备并核对等级（0–99）；特殊装备请查独立数值页'}, 400)
        elif url.path in ("/api/rules", "/api/rule"):
            args = parse_qs(url.query)
            try:
                rules = self.server.session.rules
                if url.path == "/api/rule":
                    level = int(args.get("level", ["0"])[0])
                    if not 0 <= level <= 100:
                        raise ValueError()
                    result = rules.detail(args.get("id", [""])[0][:300], level)
                else:
                    offset = int(args.get("offset", ["0"])[0])
                    if not 0 <= offset <= 100000:
                        raise ValueError()
                    result = rules.search(args.get("q", [""])[0][:200], args.get("group", ["全部"])[0], offset)
                self.send_data(result)
            except KeyError:
                self.send_data({"error": "没有对应的数值规则"}, 404)
            except ValueError:
                self.send_data({"error": "查询参数或数值资料不正确"}, 400)
            except OSError:
                self.send_data({"error": "数值资料缺失，请完整解压交付包后启动"}, 503)
        elif url.path == "/api/backups":
            self.send_data(self.server.session.backup_status())
        elif url.path in ('/api/backups/preview', '/api/backups/export'):
            args = parse_qs(url.query)
            try:
                payload = {'slot': int(args.get('slot', ['0'])[0]), 'id': args.get('id', [''])[0][:100]}
                action = url.path.rsplit('/', 1)[-1]
                result = self.server.session.backup_transfer(action, payload)
                if action == 'export':
                    self.send_data(result[0], mime='application/zip', filename=result[1])
                else:
                    self.send_data(result)
            except (OSError, ValueError) as exc:
                self.send_data({'error': str(exc)}, 400)
        elif url.path in ("/", "/index.html", "/app.js", "/backups.js", "/rules.js", "/compare.js", "/style.css", "/icon.svg"):
            path = WEB / ("index.html" if url.path == "/" else url.path[1:])
            try:
                mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                self.send_data(path.read_bytes(), mime=mime + "; charset=utf-8")
            except OSError:
                self.send_data({"error": "页面文件缺失"}, 404)
        else:
            self.send_data({"error": "Not found"}, 404)

    def do_POST(self):
        if not self.valid_host() or self.headers.get("X-Companion-Token") != self.server.token:
            self.send_data({"error": "请刷新助手页面后重试"}, 403)
            return
        origin = self.headers.get("Origin")
        if origin and origin != self.server.origin:
            self.send_data({"error": "请求来源不正确"}, 403)
            return
        if urlsplit(self.path).path == '/api/backups/import':
            if self.headers.get_content_type() != 'application/zip':
                self.send_data({'error': '请选择灯火导出的 ZIP 备份'}, 415)
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 1 < size <= MAX_TOTAL:
                    raise ValueError('备份大小需要小于64 MiB')
                self.connection.settimeout(15)
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError('上传未完成，尚未导入')
                self.server.session.backup_transfer('import', raw)
                self.send_data({'ok': True})
            except (ValueError, OSError) as exc:
                self.send_data({'error': str(exc)}, 400)
            return
        if self.headers.get_content_type() != "application/json":
            self.send_data({"error": "需要 JSON 请求"}, 415)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 16384:
                raise ValueError("请求大小不正确")
            self.connection.settimeout(5)
            payload = json.loads(self.rfile.read(size))
            path = urlsplit(self.path).path
            if path == '/api/panel':
                if payload.get('action') == 'heartbeat':
                    command = self.server.session.panel.heartbeat(payload.get('client'),payload.get('ack'))
                    self.send_data({'command':command})
                elif payload.get('action') == 'open':
                    self.server.session.panel.request(payload.get('page','overview'))
                    self.send_data({'ok':True})
                else:
                    raise ValueError('不支持的面板操作')
                return
            if path == "/api/settings":
                self.server.session.update_settings(payload)
            elif path == "/api/manual":
                self.server.session.update_manual(payload)
            elif path == "/api/shutdown":
                self.server.session.stop.set()
            elif path == "/api/refresh":
                self.server.session.refresh()
            elif path == "/api/backups":
                self.server.session.backup_action(payload)
            else:
                self.send_data({"error": "Not found"}, 404)
                return
            self.send_data({"ok": True})
        except (ValueError, OSError) as exc:
            self.send_data({"error": str(exc)}, 400)
