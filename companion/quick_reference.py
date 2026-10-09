"""Concise evaluated reference cards, using only already-redacted inventory."""
from .play_state import source_label


def value_text(row):
    text = f"{row['label']}  {row['value']} {row.get('unit', '')}".rstrip()
    if row.get('condition'):
        text += '\n  ' + row['condition']
    return text


def detail_text(detail):
    sections = []
    for block in detail.get('blocks', []):
        lines = [block['title']]
        lines.extend(value_text(v) for v in block.get('values', []))
        if block.get('columns'):
            lines.append(' / '.join(block['columns']))
            lines.extend(' / '.join(str(x) for x in row) for row in block.get('rows', []))
        if block.get('note'):
            lines.append(block['note'])
        sections.append('\n'.join(lines))
    if not sections:
        sections.append('此条目是阅读资料或场景对象，没有独立战斗数值。' if detail.get('non_numeric')
                        else '此条目暂无已核对的独立数值，请查看说明。')
    if detail.get('notice'):
        sections.append(detail['notice'])
    return '\n\n'.join(sections)


def peek_reference(session, snap, pinned=None):
    data = snap.get('data') or {}
    if pinned:
        identity, params = pinned
        detail = session.values.detail(identity, params)
        selected = next((b for b in detail['blocks'] if b.get('values')), None)
        lines = ([value_text(v) for v in selected['values'][:3]] if selected else [])
        if lines:
            if detail['inputs']:
                lines.insert(0, '参考参数：' + ' / '.join(f"{f['label']} {f['value']}" for f in detail['inputs']))
            if selected.get('note'):
                lines.append(selected['note'])
        return {'title': '固定参考 · ' + detail['name'], 'source': '百科 ' + detail['version'] + ' · 按所填参数',
                'text': '\n'.join(lines) or '此条目包含数值表或较长条件，打开完整速查查看。',
                'note': '仅列部分数值；完整条件与表格见手册。未识别当前对象。'}
    if snap.get('waiting_for_save'):
        return {'title': '灯火速查', 'source': source_label(snap),
                'text': '开始或继续一局，游戏保存后会自动显示装备与局势。现在也能打开数值手册查询。',
                'note': '自动连接和备份监控已准备好，无需先配置。'}
    if not data or snap.get('error'):
        return {'title': '灯火速查', 'source': source_label(snap),
                'text': '可打开数值手册查询，或在管理窗口确认存档连接。',
                'note': '备份与读档设置在完整面板。'}
    hero = data['hero']
    tips = data.get('tips', [])
    item = next((v for v in data.get('items', []) if v['location'] == '主武器'), None)
    if item is None:
        item = next((v for v in data.get('items', []) if v['location'] == '护甲'), None)
    lines = [f"生命 {hero['hp']:g}/{hero['ht']:g} · 基础力量 {hero['strength']:g}"]
    strength_note = ''
    if item:
        lines.append(item['name'])
        if item.get('available') is False:
            lines.append('遗落行囊：未确认可用，以下仅作基础参考。')
        if not item['known']:
            lines.append('尚未鉴定，隐藏效果与真实身份不展开。')
        else:
            from .values_decisions import equipment_metrics
            level = item['level'] if item.get('level_known') else 0
            if item['key'].startswith('items.armor.') and item.get('tier') is None:
                metrics = {}
                lines.append('原护甲阶数未知，不能推算减伤与力量需求。')
            else:
                metrics = equipment_metrics(session.values, item['key'], level, item.get('tier') or 3)
            labels = [('最低基础伤害', '最高基础伤害', '基础伤害', ' HP'),
                      ('力量需求', None, '力量需求', ' 点'), ('攻击耗时', None, '基础攻击耗时', ' 回合'),
                      ('命中倍率', None, '基础命中倍率', ' 倍'), ('常规减伤', None, '基础减伤', ' HP')]
            for low, high, label, unit in labels:
                if low in metrics:
                    value = metrics[low] + '–' + metrics[high] if high and high in metrics else metrics[low]
                    lines.append(label + ' ' + value + unit)
            if item.get('level_known') and '力量需求' in metrics and float(metrics['力量需求']) > hero['strength']:
                strength_note = ' 基础力量低于装备基础需求；若总力量仍不足，上述基础值未计力量不足惩罚。'
            if not item.get('level_known'):
                lines.append('等级未知：以上为+0基础参考。')
            if item.get('augmentation') not in (None, 'NONE') or item.get('mastery'):
                lines.append('有强化/精通修正：此卡只列未修正基础值。')
    if tips:
        lines.append('局势建议：' + tips[0]['title'])
    return {'title': '装备与局势快照', 'source': source_label(snap), 'text': '\n'.join(lines),
            'note': '基础参考，非此刻局势；未计挑战、戒指、天赋、临时状态与敌方防御。'
                    + strength_note
                    + (' 存档版本与百科不同。' if data.get('compatibility_warning') else '')}
