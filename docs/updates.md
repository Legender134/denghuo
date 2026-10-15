# 灯火更新

每次启动在后台检查一次。失败不阻塞启动，也不会自动下载或安装。
随行窗口的「更多 → 软件更新」及网页的「检查更新」提供同一入口。
有新版时先下载，核对文件长度与 SHA-256 后才出现「退出并安装」。
安装沿用原有的草稿确认与最后备份流程；取消退出不会在之后的普通退出中安装。
正式 Windows 版调用交互式安装器，保留当前程序位置。设置、草稿和备份位于独立用户数据目录。

检查只发送常规 HTTPS 请求与灯火版本，不上传存档、个人路径或排查日志。
更新来源固定为 `https://room.riftbuddy.dpdns.org/denghuo/`，拒绝重定向。
HTTPS 验证服务器身份，清单中的 SHA-256 验证下载完整性；该校验不是独立代码签名。
本地仅缓存一个已校验安装包，下载中的临时文件在完成、取消或失败时移除。

## 服务器

复用现有 Caddy HTTPS 进程，在已有 `room.riftbuddy.dpdns.org` 站点加入独立路由：

```caddyfile
handle_path /denghuo/* {
    root * /srv/denghuo-updates
    header Cache-Control no-store
    header X-Content-Type-Options nosniff
    @installer path /Denghuo-Setup.exe
    header @installer Content-Disposition attachment
    @public {
        method GET HEAD
        path /latest.json /Denghuo-Setup.exe
    }
    handle @public {
        file_server
    }
    handle {
        respond 404
    }
}
```

只允许公开两个发布文件。此目录只存当前 `Denghuo-Setup.exe` 和 `latest.json`，
不存源码、历史版本、游戏数据、运行日志或密钥。没有灯火常驻进程或定时任务。
路由在现有房间代理之前匹配；保留现有配置，校验通过后只 reload Caddy。
版本清单包含灯火标识、版本、更新说明、文件大小与 SHA-256。

## 发布

先完成三份独立功能审查、回归和正式安装包验证；不要发布开发预览包。
使用 Windows 已配置的 SSH 别名和已核对的 EC2 实例 ID，密钥留在本机。

```powershell
.venv/Scripts/python.exe tools/publish_update.py dist/灯火安装-0.7.0.exe --manifest latest.json
.venv/Scripts/python.exe tools/publish_update.py dist/灯火安装-0.7.0.exe --host EXISTING_SSH_ALIAS --expected-instance VERIFIED_INSTANCE_ID --notes "本版更新说明"
```

第二条会替换上述专属目录的当前两文件；不会遍历或清理其他服务。
先上传临时文件并在服务器核验，再替换安装包，最后替换版本清单。
跨越切换瞬间的旧客户端下载若校验不符，会要求重新检查；不会运行不匹配的文件。
临时上传随后移除，服务器不保留旧包。回滚来源和审查证据留在本地及 GitHub Release。
发布后从公网 HTTPS 读取清单并核对实际下载 SHA-256，同时检查原有服务健康状态。
