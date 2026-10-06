# 继续开发灯火

仓库包含应用源码、前端、数值资料、测试和 Windows 构建脚本。拉取即可修改和运行；`data/` 已有生成好的资料，普通开发不需要先下载游戏源码。安装包在 Releases 下载。

## 拉取与安装环境

建议使用 Windows 10/11 x64、Git、带 Tk 的 Python 3.13，以及 Node.js 24。Node 仅用于前端检查，不用于运行灯火。基础服务只用 Python 标准库；托盘和独立程序构建所需包固定在 `requirements-desktop.txt`。

以下命令在 PowerShell、仓库根目录执行。直接调用虚拟环境解释器，不需要修改 PowerShell 执行策略。

```powershell
git -c core.autocrlf=false clone https://github.com/Legender134/denghuo.git
cd denghuo
git config core.autocrlf false
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-desktop.txt
```

若 `python` 不是所需版本，可用 `py -3.13 -m venv .venv`。依赖版本有意固定，不要为了安装方便批量升级。

## 使用隔离目录调试

先指向空的测试目录，与真实游戏和已安装灯火的数据分开。空目录会正常提示未找到存档：

```powershell
New-Item -ItemType Directory -Force .local/dev, .local/dev-saves | Out-Null
$devSettings = @{
    save_root = (Resolve-Path .local/dev-saves).Path
    slot = 1
    mode = 'save'
    reveal = $false
    always_on_top = $false
    stop_at = ''
}
$devSettings | ConvertTo-Json | Set-Content -Encoding UTF8 .local/dev/settings.json
.venv/Scripts/python.exe -m companion --config .local/dev/settings.json
```

只启动服务可增加 `--no-overlay --no-browser`。自定义配置的地址写入同目录 `settings.runtime.json`，设置、备份与日志也在该开发目录。关闭窗口会继续监控，调试结束请使用“退出灯火”或面板“结束本次辅助”。

自动测试和受控验证自建临时存档，不需要真实存档。尝试回档时只使用可丢弃的测试副本，并完整退出游戏。

## 修改后验证

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -v
node tools/verify_frontend.js
.venv/Scripts/python.exe tools/smoke_runtime.py
```

Python 检查覆盖读档、信息遮蔽、数值边界、备份/恢复/撤回、HTTP、启动退出与窗口状态。前端组件检查不代替真实窗口的视觉和操作验收。符号链接权限不足或快捷键被其他应用占用时，会说明跳过原因。

提交与 Pull Request 自动运行 [Windows CI](https://github.com/Legender134/denghuo/actions/workflows/ci.yml)，检查 Python 3.10/3.13、前端和源码包的独立解压运行。CI 不发布安装包，不修改游戏。

## 模块位置

| 位置 | 职责 |
| --- | --- |
| `companion/__main__.py`、`desktop.pyw` | 启动、监控及退出协调 |
| `companion/saves.py`、`engine.py` | 解析快照、玩家已知信息与局势分析 |
| `companion/service.py`、`server.py` | 会话、设置与本地 HTTP 接口 |
| `companion/values*.py`、`game_math.py` | 数值、装备计算与游戏舍入 |
| `companion/backups.py`、`backup_archive.py` | 捕获、历史、校验、恢复和撤回 |
| `companion/overlay.py`、`tray.py`、`hotkeys.py`、`panel.py` | 窗口、托盘、快捷键与面板入口 |
| `companion/play_overlay.py`、`play_settings.py`、`play_state.py`、`quick_reference.py`、`windows.py` | 游玩显示、数值速查、来源与提醒、Windows窗口能力 |
| `web/` | 无需 npm 编译的 HTML/CSS/JavaScript |
| `data/` | 图标、中文目录和固定版本生成资料 |
| `tests/`、`tools/verify_*.py` | 回归测试与受控验收 |
| `tools/build_*.py`、`package_desktop.py` | 资料、源码包、独立程序与安装包构建 |

## 数值更新和安装包

见 [BUILD.md](BUILD.md)：官方固定源码的获取、资料重新生成与核对、安装包和对应源码/许可的完整打包步骤。修改数值同时核对条件、真实数字和舍入边界；字面量覆盖率不代表所有游戏组合的计算正确率。

## 提交改进

可以 fork 后提交 Pull Request，说明用户行为变化、复现步骤及验证结果。修复错误时优先添加能区分修复前后的回归用例；文档和小型可逆修改不需要为了增加数量而编造测试。

- 日常读取和备份不写游戏存档。恢复/撤回必须校验归档、完整退出游戏、确认槽位，并保留原进度。
- 默认遮蔽未鉴定、未探索信息，未知资源不能当作已确认资源推荐。
- 明确区分快照和手填数据，保留过期、来源和修改后未计算的提示。
- 服务仅监听本机，保留修改接口的 Host/Origin/token 校验。
- 不提交令牌、个人设置、存档、备份、日志或研究镜像。发布使用显式白名单；新增必需文件时更新 `tools/build_release.py` 的 `FILES`。
- 保留 GPL-3.0-or-later 与第三方许可和署名。
