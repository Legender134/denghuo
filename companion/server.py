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
        elif url.path == '/api/migration':
            try:
                self.send_data(self.server.session.migration_status())
            except (OSError, ValueError) as exc:
                self.send_data({'error': str(exc)}, 400)
        elif url.path in ('/api/workspace', '/api/workspace/plan', '/api/workspace/export',
                          '/api/decisions', '/api/help', '/api/help/export', '/api/play-settings'):
            try:
                session = self.server.session
                if url.path == '/api/workspace':
                    result = session.workspace_status()
                elif url.path == '/api/workspace/plan':
                    result = session.knowledge.reopen(parse_qs(url.query).get('id', [''])[0])
                elif url.path == '/api/workspace/export':
                    self.send_data(session.knowledge.export(), filename='denghuo-knowledge.json')
                    return
                elif url.path == '/api/decisions':
                    result = session.decisions()
                elif url.path == '/api/help':
                    result = session.help_status()
                elif url.path == '/api/help/export':
                    raw = session.help_status()['diagnostic_text'].encode('utf-8')
                    self.send_data(raw, filename='denghuo-diagnostic.json')
                    return
                else:
                    result = session.play_settings()
                self.send_data(result)
            except (OSError, ValueError, KeyError, OverflowError) as exc:
                self.send_data({'error': str(exc) if isinstance(exc, ValueError) else '本地资料暂时不可读，请打开帮助与排查'}, 400)
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
            except ValueError as exc:
                self.send_data({'error': str(exc)[:500] or '请核对当前条目的参数'}, 400)
            except OverflowError:
                self.send_data({'error': '数值过大，请核对当前条目的参数'}, 400)
            except OSError:
                self.send_data({"error": "数值资料缺失，请完整解压后启动"}, 503)
        elif url.path == '/api/compare':
            from .values_decisions import compare_equipment
            try:
                self.send_data(compare_equipment(self.server.session.values,
                    {k: v[0] for k, v in parse_qs(url.query).items()}))
            except ValueError as exc:
                self.send_data({'error': str(exc)[:500] or '请核对装备类型和显示的参数范围'}, 400)
            except (KeyError, OverflowError):
                self.send_data({'error': '装备或参数无法计算，请重新选择同类条目并核对显示的范围'}, 400)
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
        elif url.path == '/api/backups/storage':
            try:
                context = parse_qs(url.query).get('context', [''])[0]
                self.send_data(self.server.session.backup_workflow('storage', context=context))
            except (OSError, ValueError) as exc:
                self.send_data({'error': str(exc)}, 400)
        elif url.path == "/api/backups":
            try:
                context = parse_qs(url.query).get('context', [None])[0]
                self.send_data(self.server.session.backup_status(context))
            except (OSError, ValueError) as exc:
                self.send_data({'error': str(exc)}, 400)
        elif url.path in ('/api/backups/preview', '/api/backups/undo-preview', '/api/backups/export'):
            args = parse_qs(url.query)
            try:
                payload = {'slot': int(args.get('slot', ['0'])[0]), 'id': args.get('id', [''])[0][:100],
                           'context': args.get('context', [''])[0]}
                action = url.path.rsplit('/', 1)[-1]
                result = self.server.session.backup_transfer(action, payload)
                if action == 'export':
                    self.send_data(result[0], mime='application/zip', filename=result[1])
                else:
                    self.send_data(result)
            except (OSError, ValueError) as exc:
                self.send_data({'error': str(exc)}, 400)
        elif url.path in ("/", "/index.html", "/app.js", "/backups.js", "/rules.js", "/compare.js", "/workspace.js", "/help.js", "/play.js", "/backup-workflows.js", "/migration.js", "/alchemy.js", "/character.js", "/style.css", "/icon.svg"):
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
        if urlsplit(self.path).path in ('/api/migration/preview', '/api/migration/import'):
            if self.headers.get_content_type() != 'application/zip':
                self.send_data({'error': '请选择灯火统一迁移 ZIP'}, 415)
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 1 < size <= MAX_TOTAL:
                    raise ValueError('统一迁移包大小需要小于64 MiB')
                self.connection.settimeout(15)
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError('上传未完成，尚未导入')
                selection = self.headers.get('X-Companion-Migration-Selection', '[]')
                if len(selection) > 60000:
                    raise ValueError('迁移选择清单过大')
                payload = {'expected': self.headers.get('X-Companion-Migration-Digest'),
                           'selected': json.loads(selection),
                           'confirmed': self.headers.get('X-Companion-Migration-Confirmed') == 'true'}
                result = self.server.session.migration_action(urlsplit(self.path).path.rsplit('/', 1)[-1], payload, raw)
                self.send_data({'ok': True, **result})
            except (ValueError, OSError, RecursionError) as exc:
                self.send_data({'error': str(exc) if isinstance(exc, (ValueError, OSError)) else '迁移请求不正确'}, 400)
            return
        if urlsplit(self.path).path in ('/api/backups/batch-preview', '/api/backups/batch-import'):
            if self.headers.get_content_type() != 'application/zip':
                self.send_data({'error': '请选择灯火导出的备份迁移 ZIP'}, 415)
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 1 < size <= MAX_TOTAL:
                    raise ValueError('迁移包大小需要小于64 MiB')
                self.connection.settimeout(15)
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError('上传未完成，尚未导入')
                action = urlsplit(self.path).path.rsplit('/', 1)[-1]
                selection = self.headers.get('X-Companion-Transfer-Selection', '[]')
                if len(selection) > 8192:
                    raise ValueError('选择清单过大')
                payload = {'expected': self.headers.get('X-Companion-Transfer-Digest'),
                           'selected': json.loads(selection),
                           'confirmed': self.headers.get('X-Companion-Transfer-Confirmed') == 'true'}
                result = self.server.session.backup_workflow(action, payload, raw=raw,
                         context=self.headers.get('X-Companion-Backup-Context'))
                self.send_data({'ok': True, **result})
            except (ValueError, OSError, RecursionError) as exc:
                self.send_data({'error': str(exc) if isinstance(exc, (ValueError, OSError)) else '迁移请求不正确'}, 400)
            return
        if urlsplit(self.path).path == '/api/workspace/import':
            if self.headers.get_content_type() != 'application/json':
                self.send_data({'error': '请选择灯火收藏与方案 JSON'}, 415)
                return
            from .knowledge import MAX_BYTES
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= MAX_BYTES:
                    raise ValueError('资料文件大小需要小于1 MiB')
                self.connection.settimeout(10)
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValueError('上传未完成，尚未导入')
                result = self.server.session.knowledge.import_records(raw)
                self.send_data({'ok': True, **result})
            except (ValueError, OSError) as exc:
                self.send_data({'error': str(exc)}, 400)
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
                self.server.session.backup_transfer('import', raw, context=self.headers.get('X-Companion-Backup-Context'))
                self.send_data({'ok': True})
            except (ValueError, OSError) as exc:
                self.send_data({'error': str(exc)}, 400)
            return
        if self.headers.get_content_type() != "application/json":
            self.send_data({"error": "需要 JSON 请求"}, 415)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            maximum = 73728 if urlsplit(self.path).path == '/api/session-exit' else 16384
            if not 0 < size <= maximum:
                raise ValueError("请求大小不正确")
            self.connection.settimeout(5)
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise ValueError('请求未完成，请重试')
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError('请求格式需要是一个对象')
            path = urlsplit(self.path).path
            if path == '/api/session-exit':
                self.send_data({'ok': True, **self.server.session.exit_action(payload)})
                return
            if path == '/api/backups/workflow':
                action = payload.get('action')
                result = self.server.session.backup_workflow(action, payload)
                if action in ('batch-export', 'preserved-export'):
                    self.send_data(result[0], mime='application/zip', filename=result[1])
                else:
                    self.send_data({'ok': True, **result})
                return
            if path in ('/api/migration/export-preview', '/api/migration/export'):
                result = self.server.session.migration_action(path.rsplit('/', 1)[-1], payload)
                if path.endswith('/export'):
                    self.send_data(result[0], mime='application/zip', filename=result[1])
                else:
                    self.send_data({'ok': True, **result})
                return
            if path in ('/api/workspace', '/api/support', '/api/play-settings', '/api/play-settings/reload'):
                session = self.server.session
                if path == '/api/play-settings/reload':
                    from .workspace_service import reload_play
                    result = reload_play(session, payload)
                else:
                    result = (session.workspace_action(payload) if path == '/api/workspace' else
                              session.support_action(payload) if path == '/api/support' else session.update_play_settings(payload))
                self.send_data({'ok': True, **result})
                return
            if path == '/api/panel':
                if payload.get('action') == 'heartbeat':
                    command = self.server.session.panel.heartbeat(payload.get('client'),payload.get('ack'))
                    self.send_data({'command':command})
                elif payload.get('action') == 'open':
                    self.server.session.panel.request(payload.get('page','overview'), plan_id=payload.get('plan_id'))
                    self.send_data({'ok':True})
                elif payload.get('action') == 'show':
                    if self.server.session.manager_available:
                        self.server.session.manager_commands.put(('show', None))
                    else:
                        self.server.session.panel.request()
                    self.send_data({'ok':True})
                else:
                    raise ValueError('不支持的面板操作')
                return
            if path == "/api/settings":
                self.server.session.update_settings(payload)
            elif path == "/api/manual":
                self.server.session.update_manual(payload)
            elif path == "/api/shutdown":
                self.send_data({"ok": True, "exit": self.server.session.request_exit(payload.get("surface_id", "web"))})
                return
            elif path == "/api/refresh":
                self.server.session.refresh()
            elif path == "/api/backups":
                self.server.session.backup_action(payload)
            else:
                self.send_data({"error": "Not found"}, 404)
                return
            self.send_data({"ok": True})
        except (ValueError, OSError, KeyError, RecursionError, OverflowError) as exc:
            self.send_data({"error": str(exc) if isinstance(exc, (ValueError, OSError)) else '请求参数或资料不正确'}, 400)
