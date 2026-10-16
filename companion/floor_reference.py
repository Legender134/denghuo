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
    if source['version'] != 922:
        conditions += ' 数值手册按4.0.2参考，请核对版本差异。'
    return {'entry': item['key'], 'params': params, 'source': {'mode': 'example'},
        'source_label': item['name']+' · '+label, 'conditions': conditions,
        'level_origin': 'not_applicable' if item.get('level_applicable') is False else 'unknown' if item.get('level') is None else 'revealed',
        'field_origins': {key: label for key in params}}
