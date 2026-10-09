"""In-app help and a strictly allowlisted, local diagnostic summary."""
from __future__ import annotations

import json
import platform

FAQ = (
    {'title':'第一次打开，怎样直接使用？','body':'开始或继续游戏，保存后灯火自动连接最近的角色，并监控自动备份。没有存档时也能查数值手册；需要时再探索其他功能。','page':'overview'},
    {'title':'为什么生命和背包没有跟着每一步变化？','body':'灯火读取最近保存的快照，不会逐回合读取游戏内存。先在游戏中保存，再核对灯火的更新时间；行动前以游戏画面为准。','page':'overview'},
    {'title':'我在其他位置或发行版里玩，怎样连接？','body':'连接设置中选择含 game1、game2 等槽位的存档目录。选择其他目录前核对角色；自动跟随只在你选择的目录内寻找最近保存。','page':'settings'},
    {'title':'怎样找血瓶、力量药水和升级卷？','body':'手册支持常用别称，也能按治疗、升级等需求查找。收藏资料可以在桌面速查和完整面板复用；资料查询不会鉴定游戏里的未知物品。','page':'library'},
    {'title':'计算改了很多参数，怎样下次接着用？','body':'重新计算后命名保存为方案。方案保留当时的参数与资料版本，重启后仍可打开；它是参考，不会自动绑定当前角色。只有明确点击带入最新状态才更新计算条件。','page':'workspace'},
    {'title':'手动局势会跟随游戏吗？','body':'不会。提交后按你填写的条件生成建议，重新填写才能更新时间。保存的局势草稿打开时只填表，需要提交才应用；恢复自动读取后才会跟随存档。','page':'manual'},
    {'title':'游戏里的速查不显示，或快捷键没反应？','body':'先打开设置中的游玩显示与快捷键，确认显示已开启、没有按快捷键临时关闭、按键未被其他软件占用。独占全屏可能遮住窗口，可尝试无边框窗口；桌面数值查询仍可使用。','page':'play-settings'},
    {'title':'“等待新保存”是否表示没有备份？','body':'最后一次成功备份会单独显示。没有新游戏保存时不会重复生成相同备份；在存档时光机里核对已有时间节点。暂停监控不会删除已有备份。','page':'backups'},
    {'title':'恢复或撤回存档前需要做什么？','body':'先保存并关闭游戏，再预览当前进度和目标进度，确认槽位后操作。灯火会保留替换前的完整目录；预览后进度若已变化，会要求重新预览。导入备份只登记历史，不会自动覆盖游戏。','page':'backups'},
    {'title':'计算与游戏版本不同怎么办？','body':'先核对资料版本和游戏版本；版本不一致时，数值只能作为对应版本的参考。未知等级、力量加成、天赋、挑战和正在生效的状态都需要按游戏检查界面核对。','page':'library'},
    {'title':'收藏与方案打不开，会影响游戏或备份吗？','body':'不会。资料查询与自动备份继续运行，原资料库会保留。可以先导出可读记录，或在资料库里确认保留原文件后重建，再导入之前导出的资料。','page':'workspace'},
    {'title':'怎样取得排查信息？会发送出去吗？','body':'下面可以预览、复制或导出本地排查摘要，只包含版本与运行状态，不含个人路径、存档内容、背包、方案参数或连接口令。它不会自动发送；需要分享时由你自己决定。','page':'help'},
)


def help_status(session, snapshot=None):
    from companion import __version__
    from companion.hotkeys import DEFAULT_BINDINGS
    snap = snapshot if snapshot is not None else session.snapshot()
    data = snap.get('data') or {}
    backup = snap.get('backup_health') or {}
    caps = getattr(session,'ui_capabilities',{})
    native_accessibility = caps.get('native_accessibility')
    if not isinstance(native_accessibility, dict):
        native_accessibility = {'verified':False, 'message':native_accessibility or
            '原生桌面窗口的读屏支持有限；完整网页面板提供可用键盘和有名称的表单入口，请按实际辅助技术核对。',
            'page':'play-settings'}
    mode = snap['settings']['mode']
    reading = ('configuration-error' if session.config_error else 'read-error' if snap.get('error') else
               'waiting-for-save' if snap.get('waiting_for_save') else 'manual-stale' if mode=='manual' and snap['stale'] else
               'manual' if mode=='manual' else 'saved-stale' if snap['stale'] else 'saved')
    steps = []
    if reading in ('configuration-error','read-error'):
        steps.append({'title':'核对存档连接','body':'确认选中的目录和槽位，保存游戏后重新读取。损坏的设置会先保留原文件。','page':'settings'})
    elif reading=='waiting-for-save':
        steps.append({'title':'直接开始游戏','body':'游戏保存后会自动连接；现在也能查手册。','page':'library'})
    elif reading.startswith('manual'):
        steps.append({'title':'更新手动局势或恢复自动读取','body':'手填信息不会跟随游戏，局势改变后重新提交。','page':'manual'})
    elif reading=='saved-stale':
        steps.append({'title':'在游戏中保存','body':'当前是旧快照，保存后等待灯火更新，再参考建议。','page':'overview'})
    if backup.get('error') or backup.get('state') in ('failed','blocked'):
        steps.append({'title':'查看备份问题','body':'在存档时光机中查看原因和恢复入口，已有备份会保留。','page':'backups'})
    if data.get('compatibility_warning'):
        steps.append({'title':'核对游戏与资料版本','body':'当前存档版本与资料版本不同，计算按资料版本提供。','page':'library'})
    if caps.get('hotkeys_unavailable'):
        steps.append({'title':'修改被占用的快捷键','body':'打开游玩显示与快捷键，设置其他按键后保存。','page':'play-settings'})
    age = snap.get('age_seconds')
    age = None if age is None else max(0,int(age))
    diagnostic = {
        'format':1, 'application':'灯火', 'application_version':__version__,
        'reference_version':session.catalog.data['version'], 'platform':platform.system(),
        'connection':{'mode':mode,'state':reading,'active_slot':snap.get('active_slot'),
                      'readable_slots':sum(1 for row in snap.get('slots',[]) if row.get('valid')),
                      'snapshot_age_seconds':age,'version_mismatch':bool(data.get('compatibility_warning'))},
        'backup':{'state':backup.get('state','unknown'), 'has_problem':bool(backup.get('error')),
                  'last_save_protected':bool(backup.get('last_save_protected'))},
        'desktop':{'manager_available':bool(snap.get('manager_reuse')),
                   'play_available':caps.get('play_available'), 'tray_available':caps.get('tray_available'),
                   'hotkeys_ready':caps.get('hotkeys_ready'),
                   'hotkeys_unavailable_count':len(caps.get('hotkeys_unavailable',[]))},
        'privacy':'本地摘要；不包含个人路径、存档、背包、方案参数、日志原文或连接口令',
    }
    return {'application_version':__version__,'reference_version':session.catalog.data['version'],
            'native_accessibility':native_accessibility,
            'reading_state':reading,'next_steps':steps,'faq':list(FAQ),
            'shortcuts':caps.get('bindings') or dict(DEFAULT_BINDINGS),
            'shortcut_state':'configured' if caps.get('bindings') else 'defaults-unconfirmed',
            'diagnostic':diagnostic,
            'diagnostic_text':json.dumps(diagnostic,ensure_ascii=False,indent=2,allow_nan=False)}
