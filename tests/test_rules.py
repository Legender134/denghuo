import json
from pathlib import Path
import unittest

from companion.engine import Catalog
from companion.rules import Formula, NumericRules, PREFIX, Range, UnknownFormula
from tools.build_numeric_rules import NUMBER, mask_java, parse_file, resolve_bases


class ParserTests(unittest.TestCase):
    def test_numbers_ignore_strings_comments_identifiers_and_preserve_offsets(self):
        source = '''package test; /* 99 */ class Sample { // 88
          String text="77\\\"66"; char digit='5'; int a=0x1F; long b=0b10L;
          float c=2f, d=.25F, e=1e-3f; int field42=7_000;
          int min(int lvl){return lvl+3;}
          class Inner { int probability(){ return 1; } }
        }'''
        masked = mask_java(source)
        self.assertEqual(len(masked), len(source))
        self.assertEqual([i for i,c in enumerate(masked) if c=='\n'], [i for i,c in enumerate(source) if c=='\n'])
        self.assertEqual([m[0] for m in NUMBER.finditer(masked)], ['0x1F','0b10L','2f','.25F','1e-3f','7_000','3','1'])
        rows, coverage = parse_file(source, 'test/Sample.java', 'Sample.java')
        self.assertEqual(coverage['numeric_literals'], 8)
        self.assertEqual(coverage['fallback_literals'], 0)
        self.assertEqual(coverage['uncovered_literals'], 0)
        self.assertEqual(rows[1]['parent'], 'test.sample')
        self.assertIn('lvl+3', next(r for r in rows[0]['rules'] if r['name']=='min')['body'])

    def test_overloads_arrays_switch_and_superclass_are_preserved(self):
        source='''package test; class Parent { int min(int lvl){return 1+lvl;} }
          class Child extends Parent { int[] weights={1,2,3};
          int min(){return min(0);}
          int max(int lvl){switch(lvl){case 1:return 2;default:return 3;}}
          }'''
        rows, coverage=parse_file(source,'Child.java','Child.java')
        classes={r['id']:r for r in rows}; resolve_bases(classes)
        self.assertEqual(classes['test.child']['base'],'test.parent')
        self.assertEqual(coverage['fallback_literals'],0)
        self.assertTrue(any('switch' in r['code'] for r in rows[1]['rules']))


class FormulaTests(unittest.TestCase):
    def test_java_numeric_types_division_modulo_and_math(self):
        for expression, expected in [('5/2',2),('-5/2',-2),('-5%2',-1),('5/2f',2.5),
                                     ('0x1F+0b10L',33),('Math.pow(1.15, 2)',1.3225),
                                     ('Math.round(-1.5)',-1),('(int) 3.8',3),('1e-3f',.001)]:
            self.assertAlmostEqual(Formula().evaluate(expression),expected)
        value=Formula().evaluate('1+Random.NormalIntRange(2,5)')
        self.assertIsInstance(value,Range);self.assertEqual((value.low,value.high),(3,6))

    def test_unknown_state_branches_and_arbitrary_execution_are_rejected(self):
        for expression in ['hero.HP*2','x?1:2','__import__("os").system("whoami")','[1,2][0]',
                           'Math.pow(10,10000)','1/0','true','(int)(3.8)/2']:
            with self.subTest(expression=expression):
                with self.assertRaises(UnknownFormula):Formula().evaluate(expression)

    def test_explicit_conditional_expression_keeps_java_branch_semantics(self):
        self.assertEqual(Formula({'tier':1,'lvl':3}).evaluate('6*tier+(tier==1?2*lvl:tier*lvl)'),12)
        self.assertEqual(Formula({'tier':2,'lvl':3}).evaluate('6*tier+(tier==1?2*lvl:tier*lvl)'),18)
        self.assertEqual(Formula().evaluate('1>2 ? 8 : 3>2 ? 7 : 6'),7)
        with self.assertRaises(UnknownFormula):Formula().evaluate('1?2:3')


class ReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog=Catalog();cls.rules=NumericRules(cls.catalog)

    def test_all_numeric_source_files_and_catalog_links_have_coverage(self):
        data=self.rules.data;coverage=data['coverage']
        self.assertEqual(coverage['file_count'],1301)
        self.assertEqual(coverage['class_count'],2069)
        self.assertEqual(coverage['numeric_literals'],36299)
        self.assertEqual(coverage['uncovered_literals'],0)
        self.assertEqual(coverage['fallback_literals'],0)
        self.assertEqual(len({r['path'] for r in coverage['files']}),1301)
        self.assertEqual(sum(r['numeric_literals'] for r in coverage['files']),36299)
        self.assertEqual(data['entry_coverage']['indexed'],961)
        self.assertEqual(data['entry_coverage']['total'],len(self.catalog.entries))
        self.assertEqual(len(data['entry_coverage']['legacy']),6)
        for entry in self.catalog.entries:
            for ref in entry['numeric_refs']:
                owner=data['classes'][ref['class']]
                self.assertTrue(set(ref.get('rules',[])) <= {r['id'] for r in owner['rules']})

    def test_sword_dagger_greataxe_and_lightning_tables(self):
        for identity, first, last in [('items.weapon.melee.sword',['0','3','20'],['10','13','60']),
                                      ('items.weapon.melee.dagger',['0','1','8'],['10','11','28']),
                                      ('items.weapon.melee.greataxe',['0','5','45'],['10','15','105']),
                                      ('items.wands.wandoflightning',['0','5','10'],['10','15','60'])]:
            detail=self.rules.detail(identity)
            table=next(t for t in detail['examples'] if t['title']=='装备等级数值表')
            self.assertEqual(table['rows'][0],first);self.assertEqual(table['rows'][-1],last)
        strength=next(t for t in self.rules.detail('items.weapon.melee.greataxe')['examples'] if t['title']=='力量需求')
        self.assertEqual(strength['rows'][0],['0','20'])

    def test_conditional_fireblast_does_not_receive_generic_damage(self):
        detail=self.rules.detail('items.wands.wandoffireblast')
        table=next(t for t in detail['examples'] if t['title'].startswith('焰浪'))
        self.assertEqual(table['rows'][0],['0','1–2','2–8','3–18'])
        self.assertEqual(table['rows'][3],['3','4–8','8–20','12–36'])
        self.assertFalse(any(t['title']=='装备等级数值表' for t in detail['examples']))
        self.assertTrue(any('switch' in r['code'] for s in detail['sections'] for r in s['rules']))

    def test_ring_normal_cursed_and_armor_constructor_tiers(self):
        detail=self.rules.detail('items.rings.ringofhaste')
        table=next(t for t in detail['examples'] if t['title']=='戒指效果表')
        self.assertEqual(table['rows'][0],['0','1.15','0.756144'])
        self.assertEqual(table['rows'][2],['2','1.52087','1'])
        plate=next(t for t in self.rules.detail('items.armor.platearmor')['examples'] if t['title']=='护甲基础减伤')
        self.assertEqual(plate['rows'][0],['0','0–10','0–6','18'])
        self.assertEqual(plate['rows'][3],['3','3–25','0–9','16'])

    def test_enemy_inherited_fields_talent_cap_and_legacy_boundary(self):
        rat=self.rules.detail('actors.mobs.rat')
        fields={v['label']:v['value'] for t in rat['examples'] for v in t.get('values',[])}
        self.assertEqual(fields['初始生命'],'8');self.assertEqual(fields['基础经验'],'1')
        self.assertEqual(fields['基础伤害范围'],'1–4')
        self.assertTrue(any(s['inherited'] for s in rat['sections']))
        hearty=self.rules.entries['actors.hero.talent.hearty_meal']
        self.assertEqual(hearty['numbers'][0]['value'],'2')
        self.assertTrue(self.rules.detail(hearty['id'])['sections'])
        old=self.rules.detail('items.weapon.missiles.boomerang')
        self.assertEqual(old['status'],'legacy');self.assertFalse(old['sections'])
        with self.assertRaises(KeyError):self.rules.detail('missing')

    def test_search_pagination_and_rule_text_search(self):
        first=self.rules.search(limit=40);second=self.rules.search(offset=40,limit=40)
        self.assertEqual(first['total'],2069)
        self.assertFalse({r['id'] for r in first['entries']} & {r['id'] for r in second['entries']})
        self.assertTrue(self.rules.search('getBuffedBonus',group='物品')['total'])
        self.assertTrue(self.rules.search('焰浪')['total'])
        for entry in self.catalog.entries:
            if entry['numeric_status']=='indexed':
                # Every translated numerical entry can be opened offline.
                detail=self.rules.detail(entry['id'])
                self.assertTrue(detail['sections'],entry['id'])

    def test_custom_level_and_qualified_food_duration_constants(self):
        sword=self.rules.detail('items.weapon.melee.sword',20)
        table=next(t for t in sword['examples'] if t['title']=='装备等级数值表')
        self.assertEqual(table['rows'][-1],['20','23','100'])
        food=self.rules.detail('items.food.food')
        values={v['label']:v['value'] for t in food['examples'] for v in t.get('values',[])}
        self.assertEqual(values['基础饱食恢复量'],'300');self.assertEqual(values['基础进食时间'],'3')
        haste=self.rules.detail('actors.buffs.haste')
        values={v['label']:v['value'] for t in haste['examples'] for v in t.get('values',[])}
        self.assertEqual(values['基础持续时间'],'20')
        knife=self.rules.detail('items.weapon.missiles.throwingknife')
        table=next(t for t in knife['examples'] if t['title']=='装备等级数值表')
        self.assertEqual(table['rows'][0],['0','2','6'])
        self.assertEqual(table['rows'][3],['3','5','12'])


if __name__=='__main__':unittest.main()
