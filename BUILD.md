# Windows 开发与构建

玩家可直接下载 Releases。开发入门与隔离调试见 [CONTRIBUTING.md](CONTRIBUTING.md)。命令在 Windows x64、项目根目录的 PowerShell 中执行，使用带 Tk 的 Python 3.13、Git；前端检查使用 Node.js 24。

## 环境

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-desktop.txt
.venv/Scripts/python.exe -m unittest discover -s tests -v
node tools/verify_frontend.js
```

无需 npm 安装、Java 编译器或修改游戏。仅使用现有 `data/` 开发时，可跳过游戏源码和资料生成步骤。

## 获取固定游戏源码

资料固定为官方 Shattered Pixel Dungeon 4.0.2（版本码922），提交 `57a4e06a4caf162446d1c28caa7983f0493fecf0`。普通运行不依赖本地源码镜像。

以下初始化仅在 `.research/player-upstream-4.0.2` **尚不存在**时执行。已有镜像先检查提交和变更，不要 reset 或覆盖自己的改动。关闭换行转换保证生成与核对的原文一致。

```powershell
New-Item -ItemType Directory -Force .research, .local | Out-Null
git init .research/player-upstream-4.0.2
git -C .research/player-upstream-4.0.2 remote add origin https://github.com/00-Evan/shattered-pixel-dungeon.git
git -C .research/player-upstream-4.0.2 config core.autocrlf false
git -C .research/player-upstream-4.0.2 fetch --depth 1 origin 57a4e06a4caf162446d1c28caa7983f0493fecf0
git -C .research/player-upstream-4.0.2 checkout --detach 57a4e06a4caf162446d1c28caa7983f0493fecf0
git -C .research/player-upstream-4.0.2 rev-parse HEAD
git -C .research/player-upstream-4.0.2 status --porcelain
```

最后两行应分别给出上述提交与空的变更列表。源码镜像不提交到本仓库。

## 重新生成数值资料

```powershell
.venv/Scripts/python.exe tools/build_catalog.py
.venv/Scripts/python.exe tools/verify_rules.py
git diff --stat -- data/catalog.json data/numeric_rules.json
.venv/Scripts/python.exe -m unittest discover -s tests -v
node tools/verify_frontend.js
```

`build_catalog.py` 同时生成中文目录、配方元数据与规则索引。独立核对会检查源码提交、文件、内容哈希和字面量覆盖，把证据写入 `.local/`。未修改生成器且使用固定源码时，资料应无差异；有差异先检查版本、源码与换行，不直接接受批量数据变化。

参数化计算在 `companion/values*.py` 和 `game_math.py`；修改索引不会自动实现新计算。更新游戏版本要同时核对固定提交、元数据、兼容判断、计算逻辑及测试。

## 源码包

```powershell
.venv/Scripts/python.exe tools/build_release.py
$sourceVersion = .venv/Scripts/python.exe -c "from companion import __version__; print(__version__)"
.venv/Scripts/python.exe tools/verify_release.py "dist/denghuo-$sourceVersion.zip"
```

源码包只使用 `tools/build_release.py` 的 `FILES` 白名单，附清单与 SHA-256。验证会完整解压、运行测试、核对哈希，检查 HTTP 启动/停止、中文和空格路径以及可重复生成。新增必需文件要同步白名单，不递归打包工作区。

## 原生窗口构建输入

标准桌面窗口使用项目自有 `native/NativeCompanion.cs`，按 C# 4 与 Framework 4.0 API 编译。构建者从 Microsoft 的 [NuGet 固定包 Microsoft.NETFramework.ReferenceAssemblies.net40 1.0.3](https://www.nuget.org/packages/Microsoft.NETFramework.ReferenceAssemblies.net40/1.0.3) 下载 `.nupkg`（ZIP 格式）并解压。包的 SHA-256 应为 `54d6e20a1b61caf79395d6d71d091265e81f5a5705ac4ae52af45ca143c3c694`；引用目录是其中的 `build/.NETFramework/v4.0`。

```powershell
$net40References = '.local/net40-referenceassemblies/build/.NETFramework/v4.0'
.venv/Scripts/python.exe tools/build_native_helper.py --references "$net40References" --output native
```

源码桌面调试需先执行这一构建，默认读取 `native/NativeCompanion.exe` 与相邻运行配置。编译器默认使用 Windows 的 `Framework64/v4.0.30319/csc.exe`，可用 `--compiler` 指定构建者已有编译器。脚本只引用显式指定的 Framework 4.0 程序集；引用包不作为运行时程序发给玩家。严格 API 编译不代替旧系统或实际读屏验证。

## 独立程序

```powershell
.venv/Scripts/python.exe tools/build_desktop.py --references "$net40References"
```

最后输出 `dist/desktop-时间编号/灯火/灯火.exe`。下面的“时间编号”需换成实际目录：

```powershell
$application = 'dist/desktop-时间编号/灯火'
.venv/Scripts/python.exe tools/verify_desktop.py "$application/灯火.exe"
```

验证使用隔离存档，检查计算、自动备份、校验、恢复/撤回及退出，程序运行时从 PATH 移除 Python。它不代替真实游戏、设备/DPI与视觉验收。完整使用版本保留 EXE 旁的 `_internal/`。

## 完整免安装包与安装包

先安装官方 [Inno Setup 7.1.0](https://jrsoftware.org/isinfo.php)。需要编译器与原始许可文件；示例路径按自己机器调整。将固定游戏源码归档到 `.local/`：

```powershell
$gameSourceArchive = Join-Path (Get-Location) '.local/Shattered-Pixel-Dungeon-4.0.2-source.zip'
git -C .research/player-upstream-4.0.2 archive --format=zip --output="$gameSourceArchive" 57a4e06a4caf162446d1c28caa7983f0493fecf0
$pythonRoot = .venv/Scripts/python.exe -c "import sys; print(sys.base_prefix)"
$innoDirectory = 'C:/Program Files (x86)/Inno Setup 7'
.venv/Scripts/python.exe tools/package_desktop.py "$application" --python-root "$pythonRoot" --build-env .venv --inno "$innoDirectory"
.venv/Scripts/python.exe tools/build_installer.py "$application" --compiler "$innoDirectory/ISCC.exe"
```

打包脚本复制依赖原始许可，下载未修改的 pystray 对应源码及 Tcl/OpenSSL 许可，纳入本项目源码包和固定游戏源码，再生成含逐文件清单的免安装 ZIP。先打包后制作安装包，保证两者均含许可与对应源码。下载需要访问官方 GitHub 域名；失败时检查网络，不关闭证书验证。

默认输出在 `dist/`：`灯火免安装-版本.zip`、`灯火安装-版本.exe`。GitHub 附件可改名为 `denghuo-portable-版本.zip`、`denghuo-setup-版本.exe`，校验列表使用实际下载文件名。每次发行使用新版本与标签，不覆盖已发布包或重写旧标签。

应用版本在 `companion/__init__.py`，安装脚本和源码包读取它。相同 Python/zlib 与相同输入字节下源码 ZIP 可复现；独立 PE 和安装包不声称逐字节可复现。

## 替换 LGPL 托盘库

pystray 使用未修改的 LGPL 源码。替换时在上述虚拟环境安装兼容许可的修改版，再构建目录程序；字节码未签名或锁定。依赖版本变化也要核对打包脚本的安装目录与许可路径，并保留署名。
