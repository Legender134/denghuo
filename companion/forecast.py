"""Read-only seed handoff to a separate, explicitly hypothetical 4.0.2 scout.

Generation runs in a disposable local WebAssembly worker, never in the save
reader. The canonical profile does not reconstruct a played run's RNG state.
"""
from datetime import date, timedelta
import json
from pathlib import Path

from .scouting import ScoutingConflict, VERSIONS, read_snapshot
from .saves import SaveError, validate_hero, validate_location
from .backups import unlinked
from .engine import ROOT, clean_text

TOTAL_SEEDS = 26 ** 9


def seed_text(raw):
    if type(raw) is not int or raw < 0:
        raise SaveError('此存档种子不在已支持的九字母种子或 UTC 每日种子范围，未作取模或猜测。')
    if raw >= TOTAL_SEEDS:
        milliseconds = raw - TOTAL_SEEDS
        if milliseconds % 86_400_000 or milliseconds > 253402214400000:
            raise SaveError('此每日种子不对应受支持的 UTC 日期，未作取模或猜测。')
        return (date(1970, 1, 1) + timedelta(days=milliseconds // 86_400_000)).isoformat()
    letters = []
    for _ in range(9):
        raw, digit = divmod(raw, 26)
        letters.append(chr(65 + digit))
    code = ''.join(reversed(letters))
    return '-'.join(code[i:i+3] for i in range(0, 9, 3))


def information(catalog):
    data = json.loads((ROOT/'data/forecast_items.json').read_text(encoding='utf-8'))
    items = []
    for item in data['items']:
        reference = catalog.entry_index.get(item['key'])
        items.append({**item, **({'name': reference['name'], 'description': reference['description']} if reference else {})})
    effects = {'Weapon': {}, 'Armor': {}}
    for key, name in catalog.messages.items():
        if key.endswith('.name') and any(part in key for part in ('.enchantments.', '.glyphs.', '.curses.')):
            kind = 'Weapon' if key.startswith('items.weapon.') else 'Armor' if key.startswith('items.armor.') else None
            if kind:
                effects[kind][key.rsplit('.', 2)[-2].replace('-', '').replace('_', '')] = clean_text(name)
    return {**data, 'items': items, 'effects': effects, 'maximum_depth': 24,
        'profile': 'canonical-warrior-no-challenges-no-trinket',
        'note': '官方4.0.2新局参考情景：战士、无挑战、不装备饰品、无遗骸奖励，按顺序生成主楼层；'
                '教程已完成，日志采用引擎基准（除地狱国王的损耗页外均已读），不含游玩造成的物品或随机数变化。'
                '只列静态装备、初始饰品候选和房间类型，不是整层全部物品，也不是当前冒险的实际未来。'}


def read_seed(session, payload):
    if (not isinstance(payload, dict) or set(payload) != {'action', 'reveal'}
            or payload.get('action') != 'seed' or payload.get('reveal') is not True):
        raise ValueError('请主动选择读取本局种子，再确认独立的4.0.2参考情景。')
    with session._backup_operation() as context:
        with session.lock:
            if (context.config_error or context.settings['mode'] != 'save'
                    or context.active_slot not in range(1, 7) or session.error
                    or session._shutdown_requested.is_set() or session.stop.is_set()):
                raise ValueError('请先连接有效存档；也可直接手填九字母种子或 UTC 每日日期。')
        path = unlinked(Path(context.settings['save_root']) / f'game{context.active_slot}' / 'game.dat')
        game, digest, _, modified = read_snapshot(path)
        validate_hero(game)
        hero = game['hero']
        depth, branch = validate_location(game)
        version = game.get('version')
        if type(version) is not int or version not in VERSIONS:
            raise SaveError('仅已核对官方4.0.1与4.0.2的种子保存方式；此版本请手填独立参考种子。')
        raw = game.get('seed')
        code = seed_text(raw)
        if read_snapshot(path)[1] != digest:
            raise ScoutingConflict('游戏在读取种子期间保存，旧结果未发布；请重新读取。')
        with session.lock:
            if not session._context_current(context) or session.active_slot != context.active_slot:
                raise ScoutingConflict('存档连接已变化，旧种子未发布；请重新读取。')
        return {'seed': str(raw), 'seed_code': code,
            'source': {'slot': context.active_slot, 'version': version, 'version_name': VERSIONS[version],
                'hero_class': hero.get('class'), 'challenges': game.get('challenges', 0),
                'depth': depth, 'branch': branch, 'modified': modified, 'sha256': digest},
            'actual_future_supported': False,
            'note': '仅读取了本局种子。接下来的结果仍是官方4.0.2的独立新局参考情景，'
                    '未恢复本局的职业、挑战、饰品、掉落计数、生成器牌堆或日志状态；不可作为本局未来的确定结果。'}
