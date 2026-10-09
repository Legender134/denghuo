import copy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from companion.engine import Catalog, PREFIX, analyze, known_map, strength_requirement
from companion.saves import SaveError, read_bundle, read_slot, list_slots, open_save
from companion.service import Session, manual_game, validate_settings
from companion.server import Server


def item(relative, **kwargs):
    return {"__className": PREFIX+relative, "quantity": 1, "level": 0, "levelKnown": False, "cursedKnown": False, **kwargs}


def game(**kwargs):
    value = {"depth": 4, "branch": 0, "version": 920, "hero": {"class": "WARRIOR", "HP": 20, "HT": 30,
             "STR": 12, "lvl": 5, "buffs": [], "inventory": []}, "challenges": 0}
    value.update(kwargs)
    value.setdefault('generated_levels',[value['depth']+1000*value.get('branch',0)])
    return value


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog()

    def test_unknown_potion_has_no_identity_in_serialized_output(self):
        save = game(PotionOfHealing_label="ivory")
        save["hero"]["inventory"] = [item("items.potions.PotionOfHealing")]
        state = analyze(save, self.catalog)
        self.assertEqual(state["items"][0]["name"], "乳白药剂")
        self.assertNotIn("PotionOfHealing", json.dumps(state))
        self.assertFalse(state["items"][0]["known"])

    def test_unknown_equipment_hides_level_curse_and_enchantment(self):
        source = item("items.armor.LeatherArmor", level=7, cursed=True, glyph=item("items.armor.glyphs.Brimstone"))
        row = self.catalog.item(source, game())
        self.assertIsNone(row["level"])
        self.assertIsNone(row["cursed"])
        self.assertNotIn("+7", row["name"])
        self.assertNotIn("Brimstone", json.dumps(row))
        self.assertEqual(row["strength_requirement"], 12)

    def test_reveal_is_explicit_and_separate_from_known(self):
        row = self.catalog.item(item("items.potions.PotionOfHealing"), game(), reveal=True)
        self.assertEqual(row["kind"], "PotionOfHealing")
        self.assertIn("治疗", row["name"])
        self.assertFalse(row["known"])

    def test_exotic_identification_uses_regular_potion(self):
        source = item("items.potions.exotic.PotionOfShielding")
        row = self.catalog.item(source, game(PotionOfHealing_known=True))
        self.assertTrue(row["known"])
        self.assertEqual(row["kind"], "PotionOfShielding")

    def test_crafted_brews_are_not_randomized_potions(self):
        row = self.catalog.item(item("items.potions.brews.CausticBrew"), game())
        self.assertTrue(row["known"])

    def test_unknown_healing_never_generates_known_healing_advice(self):
        save = game()
        save["hero"]["HP"] = 4
        save["hero"]["inventory"] = [item("items.potions.PotionOfHealing")]
        tips = analyze(save, self.catalog)["tips"]
        self.assertNotIn("背包中有已鉴定的治疗药剂", str(tips))

    def test_pharmacophobia_disables_healing_recommendation(self):
        save = game(challenges=4, PotionOfHealing_known=True)
        save["hero"]["HP"] = 4
        save["hero"]["inventory"] = [item("items.potions.PotionOfHealing")]
        tips = analyze(save, self.catalog)["tips"]
        self.assertTrue(any(t["id"]=="pharmacophobia" for t in tips))
        self.assertNotIn("背包中有已鉴定的治疗药剂", str(tips))

    def test_known_healing_in_nested_bag_is_available(self):
        save = game(PotionOfHealing_known=True)
        save["hero"]["HP"] = 4
        save["hero"]["inventory"] = [item("items.bags.PotionBandolier", inventory=[item("items.potions.PotionOfHealing", quantity=3)])]
        result = analyze(save, self.catalog)
        self.assertEqual(len(result["items"]), 2)
        self.assertIn("背包中有已鉴定的治疗药剂", str(result["tips"]))

    def test_lost_inventory_is_not_a_source_of_rescue_or_growth_resources(self):
        save=game(PotionOfHealing_known=True,PotionOfStrength_known=True,ScrollOfUpgrade_known=True)
        save['hero']['HP']=4
        save['hero']['buffs']=[item('actors.buffs.LostInventory')]
        save['hero']['armor']=item('items.armor.PlateArmor',cursed=True,cursedKnown=True)
        save['hero']['inventory']=[item('items.bags.PotionBandolier',inventory=[item('items.potions.PotionOfHealing')]),
                                   item('items.potions.PotionOfStrength'),item('items.scrolls.ScrollOfUpgrade')]
        for reveal in (False,True):
            data=analyze(save,self.catalog,reveal=reveal)
            self.assertTrue(all(not row['available'] for row in data['items']))
            self.assertNotIn('背包中有已鉴定的治疗药剂',str(data['tips']))
            ids={row['id'] for row in data['tips']}
            self.assertIn('lost_inventory',ids)
            self.assertTrue(ids.isdisjoint({'strength_potion','upgrade_scroll','strength_护甲','curse_护甲','boss_next','class'}))
        save['hero']['buffs']=[]
        data=analyze(save,self.catalog)
        self.assertTrue(all(row['available'] for row in data['items']))
        self.assertIn('背包中有已鉴定的治疗药剂',str(data['tips']))

    def test_retained_items_still_require_identification_and_manual_counts_are_available(self):
        save=game();save['hero']['HP']=4
        save['hero']['buffs']=[item('actors.buffs.LostInventory')]
        save['hero']['inventory']=[item('items.potions.PotionOfHealing',kept_lost=True)]
        data=analyze(save,self.catalog)
        self.assertTrue(data['items'][0]['available'])
        self.assertNotIn('PotionOfHealing',json.dumps(data))
        self.assertNotIn('背包中有已鉴定的治疗药剂',str(data['tips']))
        save['PotionOfHealing_known']=True
        self.assertIn('背包中有已鉴定的治疗药剂',str(analyze(save,self.catalog)['tips']))
        data=analyze(manual_game({'hp':4,'ht':30,'healing':1,'buffs':['LostInventory']}),self.catalog)
        self.assertTrue(data['items'][0]['available'])
        self.assertIn('lost_inventory',{row['id'] for row in data['tips']})
        self.assertIn('背包中有已鉴定的治疗药剂',str(data['tips']))

    def test_pickaxe_mining_exception_requires_a_known_mining_level(self):
        save=game();save['hero']['buffs']=[item('actors.buffs.LostInventory')]
        save['hero']['inventory']=[item('items.quest.Pickaxe')]
        self.assertFalse(analyze(save,self.catalog)['items'][0]['available'])
        data=analyze(save,self.catalog,{'__className':PREFIX+'levels.MiningLevel'})
        self.assertTrue(data['items'][0]['available'])

    def test_paralysis_overrides_actionable_healing(self):
        save = manual_game({"hp":4,"ht":30,"buffs":["Paralysis"],"healing":1})
        tips = analyze(save, self.catalog)["tips"]
        self.assertIn("暂时不能使用物品或移动", str(tips))
        self.assertNotIn("背包中有已鉴定的治疗药剂", str(tips))

    def test_all_action_locks_suppress_inapplicable_advice(self):
        for kind in ('Paralysis','Frost','MagicalSleep','TimeStasis'):
            with self.subTest(kind=kind):
                save=game(PotionOfHealing_known=True,PotionOfStrength_known=True)
                save['hero']['HP']=4
                save['hero']['buffs']=[item('actors.buffs.'+kind),item('actors.buffs.Burning')]
                save['hero']['inventory']=[item('items.potions.PotionOfHealing'),item('items.potions.PotionOfStrength')]
                tips=analyze(save,self.catalog)['tips']
                self.assertNotIn('背包中有已鉴定的治疗药剂',str(tips))
                self.assertFalse(any(t['id'] in ('class','boss_next','strength_potion','low_hp') for t in tips))
                self.assertIn('当前不能正常移动',str(tips))

    def test_flying_and_rooted_water_advice_is_conditional(self):
        for limitation, expected in (('Levitation','漂浮'),('Roots','不能正常移动')):
            save=game()
            save['hero']['buffs']=[item('actors.buffs.'+kind) for kind in (limitation,'Burning','Ooze')]
            tips={t['id']:t for t in analyze(save,self.catalog)['tips']}
            self.assertIn(expected,tips['burning']['body'])
            self.assertIn(expected,tips['ooze']['body'])

    def test_zero_hp_does_not_suggest_ordinary_actions(self):
        save=game();save['hero']['HP']=0
        save['hero']['buffs']=[item('actors.buffs.Burning'),item('actors.buffs.Hunger',level=450)]
        tips=analyze(save,self.catalog)['tips']
        self.assertEqual([t['id'] for t in tips],['zero_hp'])
        save['hero']['buffs'].append(item('actors.buffs.Berserk',state='BERSERK'))
        tips=analyze(save,self.catalog)['tips']
        self.assertEqual([t['id'] for t in tips],['berserk_zero'])
        self.assertIn('不能仅凭 0 生命',tips[0]['body'])

    def test_version_difference_notice_does_not_affect_manual(self):
        self.assertIn('833',analyze(game(version=833),self.catalog)['compatibility_warning'])
        self.assertEqual(analyze(game(version=self.catalog.data['version_code']),self.catalog)['compatibility_warning'],'')
        self.assertEqual(analyze(manual_game({}),self.catalog)['compatibility_warning'],'')

    def test_manual_branch_and_all_supported_states(self):
        buffs=['Frost','MagicalSleep','TimeStasis','Levitation','Berserk','DeferedDamage']
        save=manual_game({'depth':4,'branch':1,'buffs':buffs+['Frost'],'challenges':511})
        data=analyze(save,self.catalog)
        self.assertEqual(data['branch'],1)
        self.assertFalse(any(t['id']=='boss_next' for t in data['tips']))
        self.assertEqual(len(data['challenges']),9)
        self.assertEqual({b['kind'] for b in data['buffs']},set(buffs))
        self.assertEqual(len(data['buffs']),len(buffs))
        self.assertIn('dot',[t['id'] for t in data['tips']])

    def test_only_active_berserk_can_be_copied_as_berserking(self):
        for state in ('NORMAL','RECOVERING','BERSERK'):
            save=game();save['hero']['buffs']=[item('actors.buffs.Berserk',state=state)]
            buff=analyze(save,self.catalog)['buffs'][0]
            self.assertEqual(buff['active'],state=='BERSERK')
            self.assertNotEqual(buff['name'],'Berserk')

    def test_hunger_boundaries(self):
        for hunger, expected in ((299,"尚未饥饿"),(300,"饥肠辘辘"),(449,"饥肠辘辘"),(450,"饥饿")):
            save = manual_game({"hunger":hunger})
            self.assertEqual(analyze(save,self.catalog)["hero"]["hunger_label"],expected)

    def test_unknown_manual_hunger_remains_unknown_and_invalid_values_are_rejected(self):
        for payload in ({},{'hunger':None}):
            data=analyze(manual_game(payload),self.catalog)
            self.assertIsNone(data['hero']['hunger'])
            self.assertEqual(data['hero']['hunger_label'],'未知')
            self.assertFalse(any(row['id'] in ('hungry','starving') for row in data['tips']))
        for hunger in (True,'unknown',-1,451,1.5):
            with self.subTest(hunger=hunger):
                with self.assertRaises(ValueError):manual_game({'hunger':hunger})

    def test_low_health_rest_advice_respects_unknown_and_starving_hunger(self):
        for hunger,expected in ((None,'饱食状态未知'),(450,'不能依靠普通休息回血'),(0,'没有进入饥饿')):
            data=analyze(manual_game({'hp':12,'ht':30,'hunger':hunger}),self.catalog)
            tip=next(row for row in data['tips'] if row['id']=='low_hp')
            self.assertIn(expected,tip['body'])
        save=game();save['hero']['buffs']=[item('actors.buffs.Hunger',level='invalid')]
        self.assertIsNone(analyze(save,self.catalog)['hero']['hunger'])

    def test_acid_and_ooze_are_distinct(self):
        save = manual_game({"buffs":["Corrosion","Ooze"]})
        tips={t["id"]:t for t in analyze(save,self.catalog)["tips"]}
        self.assertIn("用水清洗",tips["ooze"]["title"])
        self.assertIn("不能照搬",tips["corrosion"]["body"])

    def test_branch_does_not_trigger_main_boss_advice(self):
        tips=analyze(game(depth=14,branch=1),self.catalog)["tips"]
        self.assertFalse(any(t["id"]=="boss_next" for t in tips))

    def test_strength_upgrade_thresholds(self):
        self.assertEqual([strength_requirement(3,lvl) for lvl in (0,1,2,3,5,6,9,10)], [14,13,13,12,12,11,11,10])
        self.assertEqual(strength_requirement(4,3,True),12)
        self.assertEqual(strength_requirement(1,-2),10)

    def test_greataxe_uses_special_strength_requirement(self):
        for level, mastery, expected in ((0,False,20),(3,False,18),(3,True,16)):
            source=item('items.weapon.melee.Greataxe',level=level,levelKnown=True,mastery_potion_bonus=mastery)
            self.assertEqual(self.catalog.item(source,game())['strength_requirement'],expected)

    def test_artifact_display_level_matches_game_scaling(self):
        for kind, level, expected in (('EtherealChains',3,6),('TimekeepersHourglass',5,10),
                                      ('SandalsOfNature',1,3),('SandalsOfNature',2,7),
                                      ('LloydsBeacon',3,10),('ChaliceOfBlood',4,4)):
            with self.subTest(kind=kind,level=level):
                source=item('items.artifacts.'+kind,level=level,levelKnown=True,cursedKnown=True)
                row=self.catalog.item(source,game())
                self.assertEqual(row['level'],expected)
                self.assertTrue(row['name'].endswith(f'+{expected}'))
                self.assertIn('已知无诅咒',row['details'])

    def test_unknown_artifact_level_does_not_leak_through_scaling(self):
        a=self.catalog.item(item('items.artifacts.EtherealChains',level=1),game())
        b=self.catalog.item(item('items.artifacts.EtherealChains',level=5),game())
        self.assertEqual(a,b)
        self.assertIsNone(a['level'])
        self.assertIn('等级未知',a['details'])

    def test_class_armor_uses_saved_original_tier(self):
        for kind in ('WarriorArmor','MageArmor','RogueArmor','HuntressArmor','DuelistArmor','ClericArmor'):
            with self.subTest(kind=kind):
                source=item('items.armor.'+kind,armortier=2,level=3,levelKnown=True)
                row=self.catalog.item(source,game())
                self.assertEqual(row['tier'],2)
                self.assertEqual(row['strength_requirement'],10)
                self.assertIn('+3',row['name'])
                source['levelKnown']=False
                row=self.catalog.item(source,game())
                self.assertEqual(row['strength_requirement'],12)
                self.assertIsNone(row['level'])
                source.pop('armortier')
                self.assertIsNone(self.catalog.item(source,game())['strength_requirement'])

    def test_unknown_equipment_advice_uses_only_reference_requirement(self):
        first=game()
        first['hero']['armor']=item('items.armor.PlateArmor',level=1)
        second=copy.deepcopy(first);second['hero']['armor']['level']=10
        a=analyze(first,self.catalog);b=analyze(second,self.catalog)
        self.assertEqual(a,b)
        tip=next(t for t in a['tips'] if t['id']=='strength_护甲')
        self.assertIn('实际等级未知',tip['body'])
        self.assertIn('不能据此断定超重',tip['body'])
        self.assertIn('总力量',tip['body'])

    def test_growth_resources_require_known_identity(self):
        save=game()
        save['hero']['inventory']=[item('items.potions.PotionOfStrength'),item('items.scrolls.ScrollOfUpgrade')]
        tips=analyze(save,self.catalog)['tips']
        self.assertFalse(any(t['id'] in ('strength_potion','upgrade_scroll') for t in tips))
        save.update(PotionOfStrength_known=True,ScrollOfUpgrade_known=True)
        tips=analyze(save,self.catalog)['tips']
        self.assertEqual(sum(t['id'] in ('strength_potion','upgrade_scroll') for t in tips),2)
        save['hero']['buffs']=[item('actors.buffs.Paralysis')]
        self.assertFalse(any(t['id'] in ('strength_potion','upgrade_scroll') for t in analyze(save,self.catalog)['tips']))

    def test_nested_deferred_damage_buff_is_recognized(self):
        save=game()
        save['hero']['buffs']=[item('items.armor.glyphs.Viscosity$DeferedDamage',damage=15)]
        self.assertIn('dot',[t['id'] for t in analyze(save,self.catalog)['tips']])

    def test_remove_curse_advice_requires_known_scroll(self):
        save=game()
        save['hero']['armor']=item('items.armor.LeatherArmor',cursedKnown=True,cursed=True)
        save['hero']['inventory']=[item('items.scrolls.ScrollOfRemoveCurse')]
        self.assertNotIn('背包里有已鉴定的祛邪卷轴',str(analyze(save,self.catalog)['tips']))
        save['ScrollOfRemoveCurse_known']=True
        self.assertIn('背包里有已鉴定的祛邪卷轴',str(analyze(save,self.catalog)['tips']))

    def test_secret_and_unexplored_map_tiles_stay_hidden(self):
        level={"width":3,"height":2,"map":[16,17,18,8,29,7],"visited":[True,True,True,False,False,False],"mapped":[False]*6}
        self.assertEqual(known_map(level,0)["tiles"],[4,1,18,-1,-1,-1])
        self.assertEqual(level["map"][0],16)

    def test_malformed_map_is_ignored(self):
        self.assertIsNone(known_map({"width":10000,"height":20},0))
        self.assertIsNone(known_map({"width":2,"height":2,"map":[1]},0))

    def test_catalog_search_chinese_and_classname(self):
        self.assertEqual(self.catalog.search("蛇")["entries"][0]["name"],"下水道巨蛇")
        self.assertGreater(self.catalog.search("PotionOfHealing")["total"],0)


class SaveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="dungeon-companion-test-")
        self.root = Path(self.temp.name).resolve()
        self.addCleanup(self.temp.cleanup)

    def write(self, data, slot=1, compressed=True):
        folder=self.root/f"game{slot}"
        folder.mkdir(exist_ok=True)
        path=folder/"game.dat"
        raw=json.dumps(data).encode()
        path.write_bytes(gzip.compress(raw) if compressed else raw)
        return path

    def test_reads_gzip_and_plain_without_modifying(self):
        for compressed in (True,False):
            path=self.write(game(),compressed=compressed)
            original=hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(read_bundle(path)["hero"]["HP"],20)
            self.assertEqual(original,hashlib.sha256(path.read_bytes()).hexdigest())

    def test_read_handle_allows_game_to_replace_save(self):
        path = self.write(game())
        old = path.read_bytes()
        replacement = path.with_suffix('.spdtmp')
        new = gzip.compress(json.dumps(game(depth=7)).encode())
        replacement.write_bytes(new)
        with open_save(path) as stream:
            # Match upstream FileUtils.bundleToFile: delete, then move .spdtmp.
            path.unlink()
            replacement.replace(path)
            self.assertEqual(stream.read(), old)
            with self.assertRaises(io.UnsupportedOperation):
                stream.write(b'not writable')
        self.assertEqual(path.read_bytes(), new)

    def test_save_replaced_while_reader_is_open_is_rejected(self):
        path = self.write(game())
        replacement = path.with_suffix('.spdtmp')
        replacement.write_bytes(gzip.compress(json.dumps(game(depth=7)).encode()))
        def interleaved(file):
            stream = open_save(file)
            try:
                file.unlink()
                replacement.replace(file)
            except BaseException:
                stream.close()
                raise
            return stream
        with patch('companion.saves.open_save', side_effect=interleaved):
            with self.assertRaisesRegex(SaveError, '正在写入'):
                read_bundle(path)
        self.assertEqual(read_bundle(path)['depth'], 7)

    def test_one_byte_deleted_slot_is_not_valid_game(self):
        path=self.write(game());path.write_bytes(b" ")
        with self.assertRaises(SaveError):read_bundle(path)

    def test_truncated_gzip_is_reported(self):
        path=self.write(game());path.write_bytes(path.read_bytes()[:-9])
        with self.assertRaises(SaveError):read_bundle(path)

    def test_corrupt_deflate_is_reported_as_read_error(self):
        path=self.write(game())
        # A valid gzip header followed by the reserved DEFLATE block type.
        path.write_bytes(b'\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\xff\x07' + b'\x00'*8)
        with self.assertRaises(SaveError):read_bundle(path)

    def test_invalid_json_numbers_are_rejected_before_analysis_or_api_output(self):
        path=self.write(game())
        for value in ('NaN','Infinity','-Infinity','1e999','9'*1000):
            with self.subTest(value=value[:20]):
                raw=json.dumps(game()).replace('"lvl": 5','"lvl": '+value)
                path.write_bytes(gzip.compress(raw.encode()))
                with self.assertRaises(SaveError):read_bundle(path)
                self.assertFalse(list_slots(self.root)[0]['valid'])
                session=self.session();session.update_settings({'slot':1})
                self.assertIsNone(session.data)
                self.assertTrue(session.error)
                json.dumps(session.snapshot(),allow_nan=False)
        # The game's signed long seeds remain valid at both boundaries.
        for seed in (-(2**63),2**63-1):
            self.assertEqual(read_bundle(self.write(game(seed=seed)))['seed'],seed)

    def test_malformed_core_fields_are_not_presented_as_valid_defaults(self):
        for field,value in (('STR',None),('STR',10**20),('STR',True),('lvl',1.5),('lvl',0),
                            ('inventory',None),('buffs',{'unexpected':1})):
            with self.subTest(field=field):
                save=game();save['hero'][field]=value
                self.write(save)
                self.assertFalse(list_slots(self.root)[0]['valid'])
                with self.assertRaises(SaveError):read_slot(self.root,1)

    def test_boolean_floor_is_not_a_floor_number(self):
        for values in ({'depth':True},{'branch':False}):
            self.write(game(**values))
            self.assertFalse(list_slots(self.root)[0]['valid'])
            with self.assertRaisesRegex(SaveError,'楼层信息'):read_slot(self.root,1)

    def test_oversized_decompression_is_bounded(self):
        path=self.write(game());path.write_bytes(gzip.compress(b" "*(17*1024*1024)))
        with self.assertRaises(SaveError):read_bundle(path)

    def test_branch_filename_matches_game_contract(self):
        path=self.write(game(depth=12,branch=1))
        (path.parent/'depth12-branch1.dat').write_text(json.dumps({"level":{"width":2}}))
        self.assertEqual(read_slot(self.root,1)[1],{"width":2})

    def test_outdated_map_is_not_combined(self):
        path=self.write(game())
        level=path.parent/'depth4.dat';level.write_text(json.dumps({"level":{"width":2}}))
        os.utime(level,(time.time()-100,time.time()-100))
        _,level,_,warning=read_slot(self.root,1)
        self.assertIsNone(level);self.assertIn('不一致',warning)

    def test_map_even_fractionally_older_than_hero_is_suppressed(self):
        path=self.write(game());os.utime(path,(100.5,100.5))
        level=path.parent/'depth4.dat';level.write_text(json.dumps({'level':{'width':2}}))
        os.utime(level,(100.4,100.4))
        _,data,modified,warning=read_slot(self.root,1)
        self.assertIsNone(data);self.assertEqual(modified,100.5)
        self.assertIn('不一致',warning)

    def test_hero_replaced_during_map_read_rejects_mixed_pair(self):
        path=self.write(game());os.utime(path,(100,100))
        level=path.parent/'depth4.dat';level.write_text(json.dumps({'level':{'width':2}}));os.utime(level,(101,101))
        original=read_bundle
        def interleaved(file):
            result=original(file)
            if file==level:
                self.write(game(depth=7))
            return result
        with patch('companion.saves.read_bundle',side_effect=interleaved):
            with self.assertRaisesRegex(SaveError,'正在写入'):read_slot(self.root,1)

    def test_map_replaced_during_read_is_suppressed(self):
        path=self.write(game());os.utime(path,(100,100))
        level=path.parent/'depth4.dat';level.write_text(json.dumps({'level':{'width':2}}));os.utime(level,(101,101))
        original=read_bundle
        def interleaved(file):
            result=original(file)
            if file==level:
                level.write_text(json.dumps({'level':{'width':3}}));os.utime(level,(102,102))
            return result
        with patch('companion.saves.read_bundle',side_effect=interleaved):
            _,data,_,warning=read_slot(self.root,1)
        self.assertIsNone(data);self.assertIn('正在保存',warning)

    def test_partial_hero_is_not_a_valid_slot(self):
        for hp, ht in ((None,30),(True,30),(20,0),(float('nan'),30),(10**1000,30)):
            save=game();save['hero'].update(HP=hp,HT=ht);self.write(save)
            self.assertFalse(list_slots(self.root)[0]['valid'])
            with self.assertRaises(SaveError):read_slot(self.root,1)

    def session(self):
        session=Session(self.root/'config.json')
        session.update_settings({"save_root":str(self.root)})
        return session

    def test_auto_follows_new_save_and_not_old_after_deletion(self):
        old=self.write(game(),slot=2);os.utime(old,(100,100))
        current=self.write(game(depth=8),slot=1)
        session=self.session();self.assertEqual(session.active_slot,1)
        current.write_bytes(b' ');session.refresh()
        self.assertIsNone(session.data)
        self.assertEqual(session.active_slot,1)
        new=self.write(game(depth=1),slot=6);os.utime(new,(time.time()+1,time.time()+1))
        session.refresh();self.assertEqual(session.active_slot,6)

    def test_explicit_slot_does_not_switch(self):
        self.write(game(),slot=2)
        session=self.session();session.update_settings({"slot":1})
        self.assertIsNone(session.data);self.assertEqual(session.active_slot,1)
        self.assertIn('槽位 1：此槽位尚未保存',session.error)
        self.assertNotIn('WinError',session.error)
        self.write(game(depth=7),slot=1);session.refresh()
        self.assertEqual(session.data['depth'],7)
        self.assertEqual(session.active_slot,1)
        self.assertEqual(session.error,'')

    def test_auto_reports_latest_unreadable_slot_and_recovers(self):
        session=self.session()
        self.assertTrue(session.waiting_for_save)
        self.assertEqual(session.error,'')

    def test_auto_tolerates_save_replacement_gap_without_following_old_run(self):
        old=self.write(game(depth=2),slot=1);os.utime(old,(100,100))
        current=self.write(game(depth=7),slot=2)
        session=self.session();self.assertEqual(session.active_slot,2)
        original=current.read_bytes();current.unlink()
        with patch('companion.service.time.monotonic',return_value=10):session.refresh()
        self.assertEqual(session.active_slot,2)
        self.assertTrue(session.waiting_for_save)
        self.assertEqual(session.error,'')
        current.write_bytes(original)
        with patch('companion.service.time.monotonic',return_value=11):session.refresh()
        self.assertEqual(session.active_slot,2)
        self.assertEqual(session.data['depth'],7)
        self.assertFalse(session.waiting_for_save)

    def test_auto_reselects_latest_remaining_slot_after_run_is_removed(self):
        old=self.write(game(depth=2),slot=1);os.utime(old,(100,100))
        current=self.write(game(depth=7),slot=2)
        session=self.session();current.unlink()
        with patch('companion.service.time.monotonic',return_value=10):session.refresh()
        with patch('companion.service.time.monotonic',return_value=12):session.refresh()
        self.assertEqual(session.active_slot,1)
        self.assertEqual(session.data['depth'],2)
        self.assertEqual(session.error,'')
        self.assertEqual(session.settings['slot'],'auto')

    def test_auto_returns_to_ready_waiting_after_all_runs_are_removed(self):
        current=self.write(game(),slot=2)
        session=self.session()
        session.backups.health_root=str(self.root)
        session.backups.last_success=session.backups.last_saved=time.time()
        current.unlink()
        with patch('companion.service.time.monotonic',return_value=10):session.refresh()
        with patch('companion.service.time.monotonic',return_value=12):session.refresh()
        self.assertIsNone(session.active_slot)
        self.assertIsNone(session.data)
        self.assertTrue(session.waiting_for_save)
        self.assertEqual(session.error,'')
        self.assertEqual(session.backup_health()['state'],'waiting')
        self.assertEqual(session.backup_health()['saved'],0)
        self.assertEqual(session.backup_status()['health'],'waiting')
        old=self.write(game(),slot=2);old.write_bytes(b' ');os.utime(old,(100,100))
        broken=game();broken['hero']['STR']=None
        self.write(broken,slot=3);session.refresh()
        self.assertIsNone(session.active_slot)
        self.assertIsNone(session.data)
        self.assertIn('最近更新的槽位 3',session.error)
        self.assertIn('力量或等级数据不完整',session.error)
        self.write(game(depth=9),slot=3);session.refresh()
        self.assertEqual(session.active_slot,3)
        self.assertEqual(session.data['depth'],9)
        self.assertEqual(session.error,'')

    def test_first_launch_waits_for_standard_root_and_connects_without_settings(self):
        standard=self.root/'standard-saves'
        config=self.root/'first-launch.json'
        with patch.dict('companion.service.DEFAULTS',{'save_root':str(standard)}):
            session=Session(config);session.refresh()
        state=session.snapshot()
        self.assertTrue(state['waiting_for_save'])
        self.assertEqual(state['error'],'')
        self.assertEqual(state['backup_health']['state'],'waiting')
        self.assertEqual(session.backup_status()['health'],'waiting')
        self.assertTrue(session.backups.enabled)
        self.assertEqual(session.settings['slot'],'auto')
        self.assertFalse(session.settings['reveal'])
        self.assertFalse(session.settings['always_on_top'])
        self.assertEqual(session.settings['stop_at'],'')
        self.assertFalse(config.exists())
        path=standard/'game4'/'game.dat'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(game(depth=8)))
        session.refresh()
        self.assertFalse(session.waiting_for_save)
        self.assertEqual(session.active_slot,4)
        self.assertEqual(session.data['depth'],8)
        self.assertFalse(config.exists())

    def test_waiting_does_not_hide_backup_failures_or_pause(self):
        session=self.session()
        self.assertTrue(session.waiting_for_save)
        session.backups.error='受控备份目录错误'
        self.assertEqual(session.snapshot()['backup_health']['state'],'blocked')
        session.backups.set_enabled(False)
        self.assertEqual(session.snapshot()['backup_health']['state'],'paused')

    def test_default_settings_can_be_saved_before_game_creates_its_directory(self):
        standard=self.root/'not-created-yet'
        config=self.root/'first-settings.json'
        with patch.dict('companion.service.DEFAULTS',{'save_root':str(standard)}):
            session=Session(config);session.refresh()
            session.update_settings({'save_root':str(standard),'slot':'auto','always_on_top':True})
            self.assertTrue(session.waiting_for_save)
            self.assertEqual(session.error,'')
            self.assertTrue(session.settings['always_on_top'])
            self.assertFalse(standard.exists())
            self.assertEqual(json.loads(config.read_text(encoding='utf-8'))['save_root'],str(standard))
            with self.assertRaisesRegex(ValueError,'目录不存在'):
                session.update_settings({'save_root':str(self.root/'missing-custom-directory')})
            standard.write_text('not a directory')
            with self.assertRaisesRegex(ValueError,'目录不存在'):
                session.update_settings({'save_root':str(standard)})

    def test_manual_input_does_not_leave_next_launch_waiting_for_form(self):
        self.write(game(depth=7),slot=3)
        session=self.session()
        session.update_settings({'slot':3,'reveal':True,'always_on_top':True})
        session.update_manual({'hp':4,'ht':30})
        config=session.config_path.read_bytes()
        restarted=Session(session.config_path);restarted.refresh()
        self.assertEqual(restarted.settings['mode'],'save')
        self.assertEqual(restarted.settings['slot'],3)
        self.assertTrue(restarted.settings['reveal'])
        self.assertTrue(restarted.settings['always_on_top'])
        self.assertEqual(restarted.data['depth'],7)
        self.assertEqual(session.config_path.read_bytes(),config)

    def test_invalid_floor_does_not_replace_readable_auto_slot(self):
        old=self.write(game(depth=7),slot=2);os.utime(old,(100,100))
        self.write(game(depth=True),slot=3)
        session=self.session()
        self.assertEqual(session.active_slot,2)
        self.assertEqual(session.data['depth'],7)
        self.assertEqual(session.error,'')
        self.write(game(depth=9),slot=3);session.refresh()
        self.assertEqual(session.active_slot,3)
        self.assertEqual(session.data['depth'],9)
        self.write(game(depth=True),slot=3);session.refresh()
        self.assertIsNone(session.data)
        self.assertEqual(session.active_slot,3)
        self.assertIn('楼层信息',session.error)
        self.assertEqual(session.warning,'')

    def test_missing_saved_directory_does_not_fall_back_and_recovers(self):
        self.write(game(),slot=2)
        selected=self.root/'offline-saves'
        config=self.root/'config.json'
        config.write_text(json.dumps({'save_root':str(selected),'slot':3,'always_on_top':False}))
        with patch.dict('companion.service.DEFAULTS',{'save_root':str(self.root)}):
            session=Session(config)
        session.refresh()
        self.assertEqual(session.settings['save_root'],str(selected))
        self.assertEqual(session.settings['slot'],3)
        self.assertFalse(session.settings['always_on_top'])
        self.assertIn('目录暂时不可用',session.error)
        self.assertIsNone(session.data)
        path=selected/'game3'/'game.dat'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(game(depth=7)))
        session.refresh()
        self.assertEqual(session.data['depth'],7)
        self.assertEqual(session.active_slot,3)
        self.assertEqual(session.error,'')

    def test_bad_configuration_pauses_reading_without_overwriting(self):
        self.write(game())
        config=self.root/'config.json'
        for raw in (b'{',b'\xff',b'[]',b'{"slot":true}',b'{"unexpected":1}',b' ' * 65537):
            with self.subTest(raw=raw[:30]):
                config.write_bytes(raw)
                with patch.dict('companion.service.DEFAULTS',{'save_root':str(self.root)}):
                    session=Session(config)
                with patch('companion.service.list_slots') as reads:
                    session.refresh();session.refresh()
                    reads.assert_not_called()
                self.assertIn('设置无法读取',session.error)
                self.assertIsNone(session.data)
                with self.assertRaisesRegex(ValueError,'确认存档目录和槽位'):
                    session.update_settings({'always_on_top':False})
                self.assertEqual(config.read_bytes(),raw)

    def test_configuration_recovery_keeps_original_bytes_and_selected_slot(self):
        self.write(game(depth=7),slot=3)
        config=self.root/'config.json'
        raw=b'{"slot":3,"save_root":'
        config.write_bytes(raw)
        session=Session(config);session.refresh()
        session.update_settings({'save_root':str(self.root),'slot':3})
        backups=list(self.root.glob('config.recovery-*.json'))
        self.assertEqual(len(backups),1)
        self.assertEqual(backups[0].read_bytes(),raw)
        self.assertEqual(session.error,'')
        self.assertEqual(session.data['depth'],7)
        self.assertEqual(session.active_slot,3)
        self.assertIn(backups[0].name,session.snapshot()['configuration_notice'])
        reloaded=Session(config);reloaded.refresh()
        self.assertEqual(reloaded.active_slot,3)
        self.assertEqual(reloaded.config_error,'')

    def test_failed_recovery_backup_does_not_replace_configuration(self):
        config=self.root/'config.json';config.write_bytes(b'broken settings')
        session=Session(config)
        original=Path.open
        def deny_backup(path,*args,**kwargs):
            if path.name.startswith('config.recovery-'):raise PermissionError('controlled denied backup')
            return original(path,*args,**kwargs)
        with patch.object(Path,'open',new=deny_backup):
            with self.assertRaisesRegex(ValueError,'备份失败'):
                session.update_settings({'save_root':str(self.root),'slot':'auto'})
        self.assertEqual(config.read_bytes(),b'broken settings')
        session.refresh()
        self.assertIsNone(session.data)
        self.assertTrue(session.config_error)

    def test_utf8_bom_settings_are_accepted(self):
        self.write(game())
        config=self.root/'config.json'
        config.write_text(json.dumps({'save_root':str(self.root),'slot':1}),encoding='utf-8-sig')
        session=Session(config);session.refresh()
        self.assertEqual(session.config_error,'')
        self.assertEqual(session.active_slot,1)

    def test_directory_outage_clears_advice_and_recovers_unchanged_snapshot(self):
        self.write(game());session=self.session()
        with patch.object(Path,'is_dir',return_value=False):
            session.refresh()
        self.assertIsNone(session.data)
        self.assertIn('目录暂时不可用',session.error)
        session.refresh()
        self.assertEqual(session.data['depth'],4)
        self.assertEqual(session.error,'')
        self.assertEqual(len(session.history),1)
        with self.assertRaisesRegex(ValueError,'目录不存在'):
            session.update_settings({'save_root':str(self.root/'missing')})

    def test_auto_switch_does_not_compare_different_runs(self):
        old=self.write(game(seed=11,duration=200));os.utime(old,(100,100))
        session=self.session()
        new=game(seed=22,depth=1,duration=1);new['hero']['HP']=7
        self.write(new,slot=2);session.refresh()
        self.assertEqual(session.active_slot,2)
        self.assertEqual(len(session.history),1)
        self.assertIn('槽位 2',session.history[0]['text'])
        self.assertNotIn('生命',str(session.history))

    def test_seed_change_or_same_seed_replay_resets_history(self):
        for seed, duration in ((22,201),(11,1)):
            with self.subTest(seed=seed,duration=duration):
                old=self.write(game(seed=11,duration=200));os.utime(old,(100,100))
                session=self.session()
                previous_run=session.snapshot()['run_id']
                new=game(seed=seed,duration=duration,depth=1);new['hero']['HP']=7
                self.write(new);session.refresh()
                self.assertNotEqual(session.snapshot()['run_id'],previous_run)
                self.assertEqual(len(session.history),1)
                self.assertNotIn('生命',str(session.history))

    def test_transient_read_failure_keeps_same_run_history_baseline(self):
        old=self.write(game(seed=11,duration=200));os.utime(old,(100,100))
        session=self.session()
        previous_run=session.snapshot()['run_id']
        self.assertEqual(len(previous_run),24)
        self.assertNotIn('seed',previous_run)
        old.write_bytes(b'{');session.refresh();self.assertIsNone(session.data)
        self.assertEqual(session.snapshot()['run_id'],previous_run)
        new=game(seed=11,duration=201);new['hero']['HP']=7
        self.write(new);session.refresh()
        self.assertEqual(session.snapshot()['run_id'],previous_run)
        self.assertIn('生命 -13',session.history[0]['text'])
        self.assertEqual(len(session.history),2)

    def test_source_change_clears_history_and_manual_does_not_inherit(self):
        self.write(game());session=self.session()
        self.assertEqual(len(session.history),1)
        session.update_manual({'hp':3})
        self.assertEqual(session.history,[])
        session.update_settings({'mode':'save'})
        self.assertEqual(len(session.history),1)
        self.assertNotIn('生命',str(session.history))

    def test_branch_transition_is_recorded(self):
        old=self.write(game(seed=11,depth=14));os.utime(old,(100,100))
        session=self.session()
        self.write(game(seed=11,depth=14,branch=1));session.refresh()
        self.assertIn('楼层 14 → 14（支线 1）',session.history[0]['text'])

    def test_half_written_save_recovers(self):
        path=self.write(game());session=self.session()
        path.write_bytes(b'{"hero":');session.refresh()
        self.assertIsNone(session.data)
        self.write(game(depth=7));session.refresh()
        self.assertEqual(session.data['depth'],7)
        self.assertEqual(session.error,'')

    def test_late_map_arrival_updates_without_new_hero_file(self):
        save=game();save['hero']['pos']=0
        path=self.write(save)
        level_path=path.parent/'depth4.dat'
        level={'width':2,'height':2,'map':[1,1,1,1],'visited':[True,False,False,False],'mapped':[False]*4}
        level_path.write_text(json.dumps({'level':level}))
        session=self.session()
        self.assertEqual(session.data['map']['explored'],1)
        level['visited'][1]=True
        level_path.write_text(json.dumps({'level':level}))
        session.refresh()
        self.assertEqual(session.data['map']['explored'],2)

    def test_manual_timestamp_and_revision_are_stable(self):
        session=self.session();session.update_manual({"hp":4,"ht":30})
        first=session.snapshot();session.refresh();second=session.snapshot()
        self.assertGreater(first['modified'],0)
        self.assertFalse(first['stale'])
        self.assertEqual(first['revision'],second['revision'])
        self.assertEqual(first['modified'],second['modified'])

    def test_failed_manual_submission_does_not_apply_on_later_poll(self):
        self.write(game());session=self.session()
        for starting_mode in ('save','manual'):
            with self.subTest(mode=starting_mode):
                if starting_mode=='manual':session.update_manual({'hp':4,'ht':30})
                before=session.snapshot()
                config=session.config_path.read_bytes()
                with patch.object(Path,'replace',side_effect=PermissionError('controlled read-only settings')):
                    with self.assertRaises(PermissionError):session.update_manual({'hp':1,'ht':30})
                session.refresh()
                after=session.snapshot()
                self.assertEqual(after['data'],before['data'])
                self.assertEqual(after['modified'],before['modified'])
                self.assertEqual(after['settings'],before['settings'])
                self.assertEqual(session.config_path.read_bytes(),config)

    def test_changed_content_with_preserved_timestamp_updates(self):
        path=self.write(game());os.utime(path,(100,100))
        session=self.session();revision=session.revision
        save=game();save['hero']['HP']=7
        self.write(save);os.utime(path,(100,100));session.refresh()
        self.assertEqual(session.data['hero']['hp'],7)
        self.assertGreater(session.revision,revision)
        self.assertEqual(session.modified,100)
        self.assertIn('生命 -13',session.history[0]['text'])

    def test_version_warning_persists_on_unchanged_poll(self):
        self.write(game(version=833));session=self.session()
        first=session.warning;session.refresh()
        self.assertIn('833',first);self.assertEqual(session.warning,first)

    def test_unexpected_poll_failure_clears_advice_and_recovers(self):
        self.write(game());session=self.session()
        with patch.object(session,'refresh',side_effect=RuntimeError('controlled test failure')):
            with patch.object(session.stop,'wait',side_effect=lambda _:session.stop.set()):
                with self.assertLogs(level='ERROR'):
                    session.run()
        self.assertIsNone(session.data)
        self.assertIsNone(session._fingerprint)
        self.assertIn('自动重试',session.error)
        session.stop.clear();session.refresh()
        self.assertIsNotNone(session.data);self.assertEqual(session.error,'')

    def test_stale_save_and_deadline(self):
        path=self.write(game());os.utime(path,(100,100));session=self.session()
        self.assertTrue(session.snapshot()['stale'])
        from datetime import datetime, timezone
        elapsed = datetime.fromtimestamp(time.time()-1, timezone.utc).isoformat()
        session.update_settings({"stop_at": elapsed})
        status = session.exit_status()
        self.assertEqual(status['initiator'], 'deadline')
        self.assertEqual(status['reason'], '已到达用户设置的结束时间')
        self.assertTrue(session.stop.wait(5), "Coordinated deadline exit did not complete")
        self.assertEqual(session.exit_status()['phase'], 'finished')

    def test_invalid_settings_and_manual_input_do_not_apply(self):
        session=self.session()
        with self.assertRaises(ValueError):session.update_settings({"slot":True})
        with self.assertRaises(ValueError):manual_game({"hp":31,"ht":30})
        with self.assertRaises(ValueError):manual_game({"buffs":["Invented"]})
        self.assertEqual(session.settings['mode'],'save')


class BackupContextTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='lamp-backup-context-test-')
        self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        self.a,self.b=self.base/'A',self.base/'B'
        self.write(self.a,20);self.write(self.b,20)
        self.session=Session(self.base/'settings.json')
        self.session.update_settings({'save_root':str(self.a)})
        self.session.backups.closed_check=lambda:None
        self.session.backup_action({'action':'capture'})
        self.row=self.session.backup_status()['history'][0]

    def write(self,root,hp):
        folder=root/'game1';folder.mkdir(parents=True,exist_ok=True)
        saved=game(depth=2);saved['hero']['HP']=hp
        (folder/'game.dat').write_text(json.dumps(saved),encoding='utf-8')
        level={'__className':PREFIX+'levels.SewerLevel','width':4,'height':4,'version':920,
               'map':[4]*16,'visited':[False]*16,'mapped':[False]*16}
        (folder/'depth2.dat').write_text(json.dumps({'level':level}),encoding='utf-8')

    def bytes(self):
        return {p.relative_to(self.base).as_posix():p.read_bytes() for p in self.base.rglob('*') if p.is_file()}

    def test_old_context_cannot_operate_on_new_directory_or_after_return_and_restart(self):
        session=self.session;context=session.backup_context
        preview=session.backup_transfer('preview',{**self.row,'context':context})
        raw=session.backup_transfer('export',{**self.row,'context':context})[0]
        session.update_settings({'save_root':str(self.b)})
        session.backup_action({'action':'capture'})
        self.assertEqual(session.backup_status()['history'][0]['id'],self.row['id'])
        self.write(self.a,25);self.write(self.b,5)
        before=self.bytes()
        for action in ('restore','undo','manage','remove','rejoin','validate','repair_timeline'):
            with self.subTest(action=action),self.assertRaisesRegex(ValueError,'连接已变化'):
                session.backup_action({**self.row,'action':action,'context':context,
                                       'expected_current':preview['expected_current'],'confirm':'恢复槽位 1'})
            self.assertEqual(self.bytes(),before)
        for action in ('preview','export'):
            with self.subTest(action=action),self.assertRaisesRegex(ValueError,'连接已变化'):
                session.backup_transfer(action,{**self.row,'context':context})
        with self.assertRaisesRegex(ValueError,'连接已变化'):
            session.backup_transfer('import',raw,context=context)
        with self.assertRaisesRegex(ValueError,'连接已变化'):session.backup_status(context)
        self.assertEqual(self.bytes(),before)
        session.update_settings({'save_root':str(self.a)})
        before=self.bytes()
        with self.assertRaisesRegex(ValueError,'连接已变化'):
            session.backup_transfer('preview',{**self.row,'context':context})
        restarted=Session(session.config_path)
        with self.assertRaisesRegex(ValueError,'连接已变化'):
            restarted.backup_transfer('export',{**self.row,'context':session.backup_context})
        self.assertEqual(self.bytes(),before)

    def test_restore_requires_preview_and_rejects_changes_without_writing(self):
        session=self.session
        payload={**self.row,'context':session.backup_context,'action':'restore','confirm':'恢复槽位 1'}
        with self.assertRaisesRegex(ValueError,'先重新预览'):session.backup_action(payload)
        preview=session.backup_transfer('preview',payload)
        self.write(self.a,5);before=self.bytes()
        with self.assertRaisesRegex(ValueError,'变化'):
            session.backup_action({**payload,'expected_current':preview['expected_current']})
        self.assertEqual(self.bytes(),before)
        updated=session.backup_transfer('preview',payload)
        session.backup_action({**payload,'expected_current':updated['expected_current']})
        self.assertEqual(read_slot(self.a,1)[0]['hero']['HP'],20)
        record=session.backup_status()['undo'][0]
        undo_preview=session.backup_transfer('undo-preview',{**record,'context':session.backup_context})
        session.backup_action({'action':'undo','slot':1,'id':record['id'],'context':session.backup_context,
                               'expected_current':undo_preview['expected_current'],'confirm':'撤回槽位 1'})
        self.assertEqual(read_slot(self.a,1)[0]['hero']['HP'],5)

    def prepare_undo(self):
        self.write(self.a,5)
        nested=self.a/'game1'/'nested';nested.mkdir()
        (nested/'original.bin').write_bytes(b'complete original slot\x00\xff')
        original={p.relative_to(self.a/'game1').as_posix():p.read_bytes()
                  for p in (self.a/'game1').rglob('*') if p.is_file()}
        payload={**self.row,'context':self.session.backup_context,'action':'restore','confirm':'恢复槽位 1'}
        preview=self.session.backup_transfer('preview',payload)
        self.session.backup_action({**payload,'expected_current':preview['expected_current']})
        record=self.session.backup_status()['undo'][0]
        return {'action':'undo','slot':1,'id':record['id'],'context':self.session.backup_context,
                'confirm':'撤回槽位 1'},original

    def test_undo_requires_preview_and_rejects_full_slot_changes_without_writing(self):
        payload,original=self.prepare_undo();session=self.session
        before=self.bytes()
        with self.assertRaisesRegex(ValueError,'先重新预览'):session.backup_action(payload)
        self.assertEqual(self.bytes(),before)
        with self.assertRaisesRegex(ValueError,'连接已变化'):
            session.backup_transfer('undo-preview',{k:v for k,v in payload.items() if k!='context'})
        self.assertEqual(self.bytes(),before)
        preview=session.backup_transfer('undo-preview',payload)
        self.assertEqual(preview['context'],session.backup_context)
        self.assertEqual(preview['current']['hp'],20);self.assertEqual(preview['target']['hp'],5)
        self.assertTrue(preview['original_existed']);self.assertEqual(len(preview['expected_current']),64)
        self.assertEqual(self.bytes(),before,'preview must be read-only')
        extra=self.a/'game1'/'nested';extra.mkdir()
        (extra/'after-preview.bin').write_bytes(b'new bytes outside game.dat\x00\xff')
        before=self.bytes()
        with self.assertRaisesRegex(ValueError,'当前进度已变化'):
            session.backup_action({**payload,'expected_current':preview['expected_current']})
        self.assertEqual(self.bytes(),before,'a stale undo must preserve current, original, journals and archives')
        current={p.relative_to(self.a/'game1').as_posix():p.read_bytes()
                 for p in (self.a/'game1').rglob('*') if p.is_file()}
        fresh=session.backup_transfer('undo-preview',payload)
        self.assertNotEqual(fresh['expected_current'],preview['expected_current'])
        session.backup_action({**payload,'expected_current':fresh['expected_current']})
        restored={p.relative_to(self.a/'game1').as_posix():p.read_bytes()
                  for p in (self.a/'game1').rglob('*') if p.is_file()}
        self.assertEqual(restored,original)
        preserved=[{p.relative_to(folder).as_posix():p.read_bytes() for p in folder.rglob('*') if p.is_file()}
                   for folder in self.a.glob('.denghuo-before-1-*') if folder.is_dir()]
        self.assertIn(current,preserved,'the complete current slot must also survive successful undo')

    def test_undo_preview_null_token_can_restore_original_to_currently_empty_slot(self):
        payload,original=self.prepare_undo()
        (self.a/'game1').rename(self.a/'detached-current-for-test')
        preview=self.session.backup_transfer('undo-preview',payload)
        self.assertIsNone(preview['expected_current']);self.assertTrue(preview['current']['empty'])
        self.assertTrue(preview['original_existed']);self.assertEqual(preview['target']['hp'],5)
        self.session.backup_action({**payload,'expected_current':None})
        self.assertEqual({p.relative_to(self.a/'game1').as_posix():p.read_bytes()
                          for p in (self.a/'game1').rglob('*') if p.is_file()},original)

    def test_undo_preview_and_confirmation_expire_when_root_changes_and_returns(self):
        payload,original=self.prepare_undo();session=self.session
        preview=session.backup_transfer('undo-preview',payload)
        for root in (self.b,self.a):
            session.update_settings({'save_root':str(root)})
            before=self.bytes()
            with self.assertRaisesRegex(ValueError,'连接已变化'):
                session.backup_transfer('undo-preview',payload)
            with self.assertRaisesRegex(ValueError,'连接已变化'):
                session.backup_action({**payload,'expected_current':preview['expected_current']})
            self.assertEqual(self.bytes(),before)
        fresh_payload={**payload,'context':session.backup_context}
        fresh=session.backup_transfer('undo-preview',fresh_payload)
        session.backup_action({**fresh_payload,'expected_current':fresh['expected_current']})
        self.assertEqual({p.relative_to(self.a/'game1').as_posix():p.read_bytes()
                          for p in (self.a/'game1').rglob('*') if p.is_file()},original)


class ConnectionSettingsTests(unittest.TestCase):
    def test_stale_forms_cannot_revert_connection_and_reload_preserves_independent_changes(self):
        with tempfile.TemporaryDirectory(prefix='denghuo-settings-cas-') as name:
            root = Path(name).resolve()
            session = Session(root / 'config.json')
            session.update_settings({'save_root': str(root), 'slot': 1})
            server = Server(session)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            def status():
                with urlopen(server.origin + '/api/status') as response:
                    return json.load(response)
            def submit(patch):
                req = Request(server.origin + '/api/settings', data=json.dumps(patch).encode(), headers={
                    'Content-Type': 'application/json', 'X-Companion-Token': server.token, 'Origin': server.origin})
                with urlopen(req) as response:
                    return json.load(response)
            try:
                old = status()
                newer_root = root / 'other'; newer_root.mkdir()
                changed = {**old['settings'], 'save_root': str(newer_root), 'slot': 2, 'reveal': True,
                           'stop_at': '2099-01-01T12:00:00+08:00'}
                first = submit({**changed, 'expected_revision': old['settings_revision']})
                original_bytes = session.config_path.read_bytes()
                with self.assertRaises(HTTPError) as caught:
                    submit({**old['settings'], 'always_on_top': True, 'expected_revision': old['settings_revision']})
                self.assertEqual(caught.exception.code, 409)
                self.assertIn('草稿仍保留', json.load(caught.exception)['error'])
                self.assertEqual(session.config_path.read_bytes(), original_bytes)
                self.assertEqual(status()['settings'], changed)
                self.assertEqual(status()['settings_revision'], first['settings_revision'])
                for missing in ({'always_on_top': True}, {'always_on_top': True, 'expected_revision': None}):
                    with self.assertRaises(HTTPError) as caught:
                        submit(missing)
                    self.assertEqual(caught.exception.code, 400)
                    self.assertEqual(session.config_path.read_bytes(), original_bytes)
                fresh = status()
                final = submit({**fresh['settings'], 'always_on_top': True, 'expected_revision': fresh['settings_revision']})
                self.assertEqual(status()['settings'], {**changed, 'always_on_top': True})
                self.assertNotEqual(final['settings_revision'], first['settings_revision'])
                self.assertNotIn('expected_revision', json.loads(session.config_path.read_text(encoding='utf-8')))
            finally:
                server.shutdown(); server.server_close(); thread.join(5)
                self.assertFalse(thread.is_alive())

    def test_native_targeted_changes_and_new_sessions_invalidate_old_forms(self):
        from companion.service import SettingsConflict
        with tempfile.TemporaryDirectory(prefix='denghuo-settings-session-') as name:
            config = Path(name) / 'settings.json'
            first = Session(config)
            old_revision = first.snapshot()['settings_revision']
            first.update_settings({'always_on_top': True})
            with self.assertRaises(SettingsConflict):
                first.update_settings({'slot': 1}, expected_revision=old_revision)
            self.assertTrue(first.settings['always_on_top'])
            second = Session(config)
            self.assertNotEqual(first.settings_revision, second.settings_revision)
            with self.assertRaises(SettingsConflict):
                second.update_settings({'slot': 1}, expected_revision=first.settings_revision)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='dungeon-companion-api-')
        cls.session=Session(Path(cls.temp.name)/'config.json')
        cls.server=Server(cls.session)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.url=cls.server.origin

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.temp.cleanup()

    def test_static_page_and_security_headers(self):
        with urlopen(self.url) as response:
            self.assertIn('灯火',response.read().decode())
            self.assertIn("frame-ancestors 'none'",response.headers['Content-Security-Policy'])

    def test_player_values_api_and_parameter_errors(self):
        with urlopen(self.url+'/api/values?id=items.potions.potionofhealing&max_hp=100&hp=10') as response:
            detail=json.load(response)
        self.assertEqual(detail['version'],'4.0.2')
        values={v['label']:v['value'] for b in detail['blocks'] for v in b.get('values',[])}
        self.assertEqual(values['最终实际恢复'],'90')
        self.assertNotIn('sections',detail)
        for path,code in [('/api/values?id=missing',404),('/api/values?id=items.potions.potionofhealing&hp=200',400),('/api/values?id=items.weapon.melee.sword&level=1.5',400)]:
            with self.subTest(path=path),self.assertRaises(HTTPError) as caught:urlopen(self.url+path)
            self.assertEqual(caught.exception.code,code)

    def test_post_requires_session_token(self):
        req=Request(self.url+'/api/settings',data=b'{"reveal":true}',headers={'Content-Type':'application/json'})
        with self.assertRaises(HTTPError) as error:urlopen(req)
        self.assertEqual(error.exception.code,403)

    def test_repeated_launch_routes_to_native_manager(self):
        self.session.manager_available=True
        try:
            req=Request(self.url+'/api/panel',data=b'{"action":"show"}',headers={
                'Content-Type':'application/json','X-Companion-Token':self.server.token,'Origin':self.url})
            with patch.object(self.session.panel,'request') as panel:
                with urlopen(req) as response:self.assertEqual(response.status,200)
            self.assertEqual(self.session.manager_commands.get_nowait(),('show',None))
            panel.assert_not_called()
        finally:
            self.session.manager_available=False

    def test_authorized_manual_roundtrip(self):
        req=Request(self.url+'/api/manual',data=json.dumps({'hp':3,'ht':40,'buffs':['Burning']}).encode(),headers={'Content-Type':'application/json','X-Companion-Token':self.server.token,'Origin':self.url})
        with urlopen(req) as response:self.assertEqual(response.status,200)
        with urlopen(self.url+'/api/status') as response:state=json.load(response)
        self.assertEqual(state['data']['hero']['hp'],3)
        self.assertIn('burning',[tip['id'] for tip in state['data']['tips']])
        self.assertFalse(state['stale'])

    def test_wrong_origin_rejected(self):
        req=Request(self.url+'/api/settings',data=b'{"reveal":true}',headers={'Content-Type':'application/json','X-Companion-Token':self.server.token,'Origin':'https://example.com'})
        with self.assertRaises(HTTPError) as error:urlopen(req)
        self.assertEqual(error.exception.code,403)

    def test_path_traversal_not_served(self):
        with self.assertRaises(HTTPError) as error:urlopen(self.url+'/../companion/service.py')
        self.assertEqual(error.exception.code,404)

    def test_complete_reference_api_pagination_and_invalid_requests(self):
        with urlopen(self.url+'/api/rules?offset=40') as response:result=json.load(response)
        self.assertEqual(result['total'],2069);self.assertEqual(result['offset'],40)
        self.assertEqual(len(result['entries']),40)
        with urlopen(self.url+'/api/rule?id=items.weapon.melee.sword') as response:detail=json.load(response)
        self.assertTrue(detail['examples']);self.assertTrue(detail['sections'])
        with urlopen(self.url+'/api/library?offset=80') as response:result=json.load(response)
        self.assertEqual(result['offset'],80)
        for path,code in [('/api/rules?offset=-1',400),('/api/library?offset=no',400),('/api/rule?id=missing',404)]:
            with self.subTest(path=path):
                with self.assertRaises(HTTPError) as error:urlopen(self.url+path)
                self.assertEqual(error.exception.code,code)

    def test_backup_binary_import_requires_token_origin_and_bounded_size(self):
        for headers, code in [({'Content-Type':'application/zip'},403),
            ({'Content-Type':'application/zip','X-Companion-Token':self.server.token,'Origin':'https://example.com'},403),
            ({'Content-Type':'text/plain','X-Companion-Token':self.server.token},415),
            ({'Content-Type':'application/zip','X-Companion-Token':self.server.token},400)]:
            with self.subTest(headers=headers):
                req=Request(self.url+'/api/backups/import',data=b'controlled invalid zip',headers=headers)
                with self.assertRaises(HTTPError) as caught:urlopen(req)
                self.assertEqual(caught.exception.code,code)
        req=Request(self.url+'/api/backups/import',data=b'xx',headers={'Content-Type':'application/zip',
                    'X-Companion-Token':self.server.token,'Content-Length':str(64*1024*1024+1)})
        with self.assertRaises(HTTPError) as caught:urlopen(req)
        self.assertEqual(caught.exception.code,400)

    def test_backup_preview_and_export_reject_unknown_identity(self):
        for path in ('preview','undo-preview','export'):
            with self.subTest(path=path),self.assertRaises(HTTPError) as caught:
                urlopen(self.url+f'/api/backups/{path}?slot=1&id=../bad')
            self.assertEqual(caught.exception.code,400)
        with urlopen(self.url+'/backups.js') as response:
            self.assertIn('openRestore',response.read().decode())

    def test_backup_preview_export_and_import_roundtrip_with_configured_string_path(self):
        with tempfile.TemporaryDirectory(prefix='denghuo-api-backups-') as directory:
            root=Path(directory)/'存档';folder=root/'game1';folder.mkdir(parents=True)
            (folder/'game.dat').write_text(json.dumps(game(depth=2)),encoding='utf-8')
            level={'__className':'com.shatteredpixel.shatteredpixeldungeon.levels.SewerLevel','version':920,'width':4,'height':4,
                   'map':[4]*16,'visited':[False]*16,'mapped':[False]*16}
            (folder/'depth2.dat').write_text(json.dumps({'level':level}),encoding='utf-8')
            session=Session(Path(directory)/'config.json')
            session.update_settings({'save_root':str(root),'slot':1})
            session.backup_action({'action':'capture'})
            row=session.backup_status()['history'][0]
            with patch.object(self.server,'session',session):
                query=f"?slot=1&id={row['id']}&context={session.backup_context}"
                with urlopen(self.url+'/api/backups/preview'+query) as response:preview=json.load(response)
                self.assertEqual(preview['current']['hp'],preview['target']['hp'])
                with urlopen(self.url+'/api/backups/export'+query) as response:
                    raw=response.read();self.assertEqual(response.headers['Content-Type'],'application/zip')
                    self.assertIn('.zip',response.headers['Content-Disposition'])
                request=Request(self.url+'/api/backups/import',data=raw,headers={'Content-Type':'application/zip',
                                'X-Companion-Token':self.server.token,'Origin':self.url,
                                'X-Companion-Backup-Context':session.backup_context})
                with urlopen(request) as response:self.assertTrue(json.load(response)['ok'])
                self.assertEqual(len(session.backup_status()['history']),1)

    def test_restore_with_malformed_unicode_keeps_http_undo_accessible(self):
        with tempfile.TemporaryDirectory(prefix='denghuo-api-unicode-') as directory:
            root=Path(directory)/'存档';folder=root/'game1';folder.mkdir(parents=True)
            saved=game(depth=2);(folder/'game.dat').write_text(json.dumps(saved),encoding='utf-8')
            level={'__className':'com.shatteredpixel.shatteredpixeldungeon.levels.SewerLevel','version':920,
                   'width':4,'height':4,'map':[4]*16,'visited':[False]*16,'mapped':[False]*16}
            (folder/'depth2.dat').write_text(json.dumps({'level':level}),encoding='utf-8')
            session=Session(Path(directory)/'config.json');session.update_settings({'save_root':str(root),'slot':1})
            session.backup_action({'action':'capture'});row=session.backup_status()['history'][0]
            saved['hero'].update(HP=2,**{'class':'\ud800'})
            (folder/'game.dat').write_text(json.dumps(saved),encoding='utf-8')
            original={p.name:p.read_bytes() for p in folder.iterdir()}
            session.backups.closed_check=lambda:None
            with patch.object(self.server,'session',session):
                def post(payload):
                    request=Request(self.url+'/api/backups',data=json.dumps(payload).encode(),
                                    headers={'Content-Type':'application/json','X-Companion-Token':self.server.token,'Origin':self.url})
                    with urlopen(request) as response:return json.load(response)
                preview=session.backup_transfer('preview',{**row,'context':session.backup_context})
                self.assertTrue(post({'action':'restore','slot':1,'id':row['id'],'context':session.backup_context,
                                      'expected_current':preview['expected_current'],'confirm':'恢复槽位 1'})['ok'])
                with urlopen(self.url+'/api/backups') as response:record=json.load(response)['undo'][0]
                self.assertEqual(record['before']['class'],'\ud800')
                with urlopen(self.url+f"/api/backups/undo-preview?slot=1&id={record['id']}&context={session.backup_context}") as response:
                    undo_preview=json.load(response)
                self.assertEqual(undo_preview['target']['class'],'\ud800')
                self.assertTrue(post({'action':'undo','slot':1,'id':record['id'],'context':session.backup_context,
                                      'expected_current':undo_preview['expected_current'],'confirm':'撤回槽位 1'})['ok'])
                self.assertEqual({p.name:p.read_bytes() for p in folder.iterdir()},original)
                with urlopen(self.url+'/api/status') as response:self.assertEqual(json.load(response)['data']['hero']['hp'],2)

    def test_http_undo_requires_fresh_full_slot_preview_and_current_root_context(self):
        with tempfile.TemporaryDirectory(prefix='denghuo-api-undo-preview-') as directory:
            base=Path(directory);root=base/'A';folder=root/'game1';folder.mkdir(parents=True)
            (base/'B').mkdir()
            saved=game(depth=2);(folder/'game.dat').write_text(json.dumps(saved),encoding='utf-8')
            level={'__className':PREFIX+'levels.SewerLevel','version':920,'width':4,'height':4,
                   'map':[4]*16,'visited':[False]*16,'mapped':[False]*16}
            (folder/'depth2.dat').write_text(json.dumps({'level':level}),encoding='utf-8')
            session=Session(base/'config.json');session.update_settings({'save_root':str(root),'slot':1})
            session.backups.closed_check=lambda:None
            session.backup_action({'action':'capture'});row=session.backup_status()['history'][0]
            saved['hero']['HP']=5;(folder/'game.dat').write_text(json.dumps(saved),encoding='utf-8')
            (folder/'original.bin').write_bytes(b'original complete slot\x00\xff')
            original={p.name:p.read_bytes() for p in folder.iterdir()}
            def all_bytes():
                return {p.relative_to(base).as_posix():p.read_bytes() for p in base.rglob('*') if p.is_file()}
            with patch.object(self.server,'session',session):
                def post(payload):
                    request=Request(self.url+'/api/backups',data=json.dumps(payload).encode(),headers={
                        'Content-Type':'application/json','X-Companion-Token':self.server.token,'Origin':self.url})
                    with urlopen(request) as response:return json.load(response)
                restore=session.backup_transfer('preview',{**row,'context':session.backup_context})
                self.assertTrue(post({'action':'restore','slot':1,'id':row['id'],'context':restore['context'],
                                     'expected_current':restore['expected_current'],'confirm':'恢复槽位 1'})['ok'])
                with urlopen(self.url+'/api/backups') as response:record=json.load(response)['undo'][0]
                payload={'action':'undo','slot':1,'id':record['id'],'context':session.backup_context,'confirm':'撤回槽位 1'}
                def preview(context):
                    query=f"?slot=1&id={record['id']}"+(f'&context={context}' if context is not None else '')
                    with urlopen(self.url+'/api/backups/undo-preview'+query) as response:return json.load(response)
                before=all_bytes()
                with self.assertRaises(HTTPError) as caught:post(payload)
                self.assertEqual(caught.exception.code,400)
                self.assertIn('先重新预览',json.load(caught.exception)['error'])
                with self.assertRaises(HTTPError) as caught:preview(None)
                self.assertEqual(caught.exception.code,400)
                self.assertIn('连接已变化',json.load(caught.exception)['error'])
                self.assertEqual(all_bytes(),before)
                first=preview(payload['context'])
                self.assertEqual(first['current']['hp'],20);self.assertEqual(first['target']['hp'],5)
                self.assertTrue(first['original_existed']);self.assertEqual(first['context'],payload['context'])
                self.assertEqual(all_bytes(),before,'HTTP preview must not alter any files')
                (folder/'new-after-preview.bin').write_bytes(b'new current sidecar\x00\xff')
                before=all_bytes()
                with self.assertRaises(HTTPError) as caught:post({**payload,'expected_current':first['expected_current']})
                self.assertEqual(caught.exception.code,400)
                self.assertIn('当前进度已变化',json.load(caught.exception)['error'])
                self.assertEqual(all_bytes(),before)
                for changed_root in (base/'B',root):
                    session.update_settings({'save_root':str(changed_root)})
                    before=all_bytes()
                    with self.assertRaises(HTTPError) as caught:preview(payload['context'])
                    self.assertEqual(caught.exception.code,400)
                    self.assertIn('连接已变化',json.load(caught.exception)['error'])
                    with self.assertRaises(HTTPError) as caught:post({**payload,'expected_current':first['expected_current']})
                    self.assertEqual(caught.exception.code,400)
                    self.assertIn('连接已变化',json.load(caught.exception)['error'])
                    self.assertEqual(all_bytes(),before)
                fresh=preview(session.backup_context)
                self.assertNotEqual(fresh['expected_current'],first['expected_current'])
                current={p.name:p.read_bytes() for p in folder.iterdir()}
                self.assertTrue(post({**payload,'context':fresh['context'],'expected_current':fresh['expected_current']})['ok'])
                self.assertEqual({p.name:p.read_bytes() for p in folder.iterdir()},original)
                preserved=[{p.relative_to(preserved).as_posix():p.read_bytes() for p in preserved.rglob('*') if p.is_file()}
                           for preserved in root.glob('.denghuo-before-1-*') if preserved.is_dir()]
                self.assertIn(current,preserved)


if __name__=='__main__':unittest.main()
