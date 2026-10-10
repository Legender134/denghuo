"""Optional provenance linking calculations to the bundled fixed game revision."""
import re
from urllib.parse import quote

REPOSITORY='https://github.com/00-Evan/shattered-pixel-dungeon'


def provenance(values,identity,owner):
    version=values.catalog.data['version']
    commit=values.catalog.data.get('commit','')
    links=[]
    if re.fullmatch(r'[a-f0-9]{40}',commit):
        related=[]
        if owner:related.append(owner)
        if identity in ('items.waterskin','items.potions.potionofhealing','actors.buffs.healing'):
            related.extend('com.shatteredpixel.shatteredpixeldungeon.'+tail for tail in
                           ('actors.buffs.healing','items.trinkets.vialofblood'))
        if identity=='items.waterskin':
            related.extend('com.shatteredpixel.shatteredpixeldungeon.'+tail for tail in ('items.dewdrop','actors.buffs.barrier'))
        if identity.startswith('items.food.'):
            related.append('com.shatteredpixel.shatteredpixeldungeon.actors.buffs.hunger')
        if identity=='items.scrolls.scrollofupgrade':
            related.extend('com.shatteredpixel.shatteredpixeldungeon.'+tail for tail in
                           ('items.weapon.weapon','items.weapon.missiles.missileweapon','items.armor.armor','items.wands.wand','items.rings.ring'))
        seen=set()
        for initial in related:
            current=initial
            for _ in range(8):
                entry=values.rules.classes.get(current)
                if not entry or current in seen:break
                seen.add(current)
                path=entry.get('path','')
                if path and '..' not in path.split('/'):
                    key=current.removeprefix('com.shatteredpixel.shatteredpixeldungeon.')
                    name=values.rules.entries.get(key,{}).get('name') or values.rules.title(entry).split(' · ')[0]
                    line=entry.get('line')
                    suffix='#L'+str(line) if type(line) is int and line>0 else ''
                    links.append({'label':name+'参考依据','url':REPOSITORY+'/blob/'+commit+'/'+quote(path,safe='/')+suffix,
                                  'kind':'official-game-source'})
                current=entry.get('base')
                if not current:break
        if not links:links.append({'label':'此版本原游戏资料','url':REPOSITORY+'/tree/'+commit,'kind':'official-game-source'})
    return {'version':version,'revision':commit,'kind':'official-game-text-and-reviewed-calculation',
            'summary':'玩法说明来自此版游戏中文资料；输入后的数值由灯火按已核对规则计算。参数来源、随机范围和排除条件见各表。',
            'limits':['这是对应资料版本的参考，不是当前游戏内存状态。','未知物品不会被资料查询鉴定；未知等级和未填写条件仍需在游戏中核对。',
                      '特殊分支和其他装备、天赋、挑战、敌方防御与临时状态只在明确注明时计入。'],
            'links':links}
