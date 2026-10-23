"""Captured floor items stay independent of the current hero and backpack."""
from .native_workspace import plan_updated_text


def item_reference(item, floor):
    params = {target: item[key] for key, target in (
        ('level', 'level'), ('tier', 'tier'), ('volume', 'dew_volume')) if item.get(key) is not None}
    source = floor['source']
    label = f"槽位 {source['slot']} · 第 {floor['depth']} 层"+(
        f" / 支线 {floor['branch']}" if floor['branch'] else '')+' · 已主动揭示的楼层物品'
    label += ' · '+plan_updated_text(source['floor_modified'])
    conditions = '楼层保存参考；游戏鉴定状态未改变，未加入背包。未合并当前角色、装备或临时状态。'
    states = []
    if item.get('cursed') is True:
        states.append('有诅咒')
    augment = {'SPEED': '速度强化', 'DAMAGE': '伤害强化', 'EVASION': '闪避强化', 'DEFENSE': '防御强化'}.get(item.get('augmentation'))
    if augment:
        states.append(augment)
    if item.get('mastery') is True:
        states.append('已用精通药剂')
    scope = f"第 {floor['depth']} 层"+(f" / 支线 {floor['branch']}" if floor['branch'] else '')+' · 主动揭示'
    notice = scope+(' · '+' · '.join(states)+'\n基础参考未计上述物品修正' if states else ' · 基础参考')
    details = ' · '.join(item.get('details', []))
    if details:
        conditions += '\n物品保存属性：'+details
    if source['version'] != 922:
        conditions += ' 数值手册按4.0.2参考，请核对版本差异。'
    return {'entry': item['key'], 'params': params, 'source': {'mode': 'example'},
        'source_label': item['name']+' · '+label, 'conditions': conditions, 'item_notice': notice,
        'level_origin': 'not_applicable' if item.get('level_applicable') is False else 'unknown' if item.get('level') is None else 'revealed',
        'field_origins': {key: label for key in params}}
