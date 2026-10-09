"""Run the actual frozen application with only Windows system commands on PATH."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.request import Request, urlopen
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))
from tools.build_desktop import native_resources


def request(info, path, value=None, token=None):
    headers = {'Origin': info['url'].rstrip('/')}
    if token: headers['X-Companion-Token'] = token
    if value is not None: headers['Content-Type'] = 'application/json'
    req = Request(info['url']+path, headers=headers,
                  data=None if value is None else json.dumps(value).encode())
    with urlopen(req, timeout=25) as response:
        return json.load(response)


def verify(exe):
    native = native_resources(Path(exe).parent)
    work = ROOT/'.local'/('独立程序 验收 '+str(time.time_ns()))
    work.mkdir(parents=True)
    saves = work/'测试存档'
    folder = saves/'game1'; folder.mkdir(parents=True)
    game = {'depth':2, 'version':920, 'seed':99,'generated_levels':[2],
            'hero':{'class':'MAGE','HP':20,'HT':30,'STR':10,'lvl':2,'inventory':[],'buffs':[]}}
    def write(hp):
        game['hero']['HP']=hp
        (folder/'game.dat').write_bytes(gzip.compress(json.dumps(game).encode()))
        level={'__className':'com.shatteredpixel.shatteredpixeldungeon.levels.SewerLevel','version':920,'width':4,'height':4,
               'map':[4]*16,'visited':[False]*16,'mapped':[False]*16}
        (folder/'depth2.dat').write_bytes(gzip.compress(json.dumps({'level':level}).encode()))
    write(20)
    config = work/'设置.json'
    config.write_text(json.dumps({'save_root':str(saves),'slot':1,'mode':'save','reveal':False}),encoding='utf-8')
    env = os.environ.copy()
    for key in ('PYTHONPATH', 'LAMP_NATIVE_HELPER'):
        env.pop(key, None)
    env['APPDATA'] = str(work / 'appdata')
    env['LOCALAPPDATA'] = str(work / 'localappdata')
    env['PATH'] = str(Path(env.get('SystemRoot') or env.get('WINDIR') or 'C:/Windows')/'System32')
    process = subprocess.Popen([str(exe),'--no-overlay','--no-browser','--config',str(config)],
                               cwd=work, env=env)
    info = None
    try:
        runtime = config.with_suffix('.runtime.json')
        deadline = time.monotonic()+20
        while not runtime.exists() and process.poll() is None and time.monotonic()<deadline: time.sleep(.1)
        assert runtime.exists(), 'Frozen service did not start'
        info = json.loads(runtime.read_text())
        state = request(info,'api/status')
        assert state['data']['hero']['hp']==20 and not state['error'], state
        for resource in ('', 'backups.js', 'compare.js', 'rules.js', 'icon.svg'):
            with urlopen(info['url']+resource,timeout=5) as response: assert response.status==200
        values = request(info,'api/values?id=actors.buffs.combo%24combomove.slam&combo=4&armor_roll=10&damage=20')
        metrics={r['label']:r['value'] for block in values['blocks'] for r in block.get('values',[])}
        assert metrics['未计目标减伤的攻击伤害']=='28', 'Numeric calculation missing from frozen build'
        comparison=request(info,'api/compare?id_a=items.weapon.melee.longsword&id_b=items.weapon.melee.shortsword&level_a=4&level_b=10&augment_a=SPEED&augment_b=SPEED&strength=20')
        assert all(c['current']['最高基础伤害']=='32' for c in comparison['choices'])
        armor=request(info,'api/compare?id_a=items.armor.warriorarmor&tier_a=1&level_a=4&augment_a=EVASION&id_b=items.armor.platearmor&strength=12')
        assert armor['choices'][0]['current']['常规减伤']=='2–2'
        risk=request(info,'api/values?id=items.scrolls.scrollofupgrade&level=6')
        risks={r['label']:r['value'] for b in risk['blocks'] for r in b.get('values',[])}
        assert risks['硬化保护消失']=='10' and risks['无附魔 / 刻印时硬化保护消失']=='0'
        for hero_level,energy,points,expected_vigor in ((14,7.5,3,'是'),(20,12,2,'否'),(20,12.5,2,'是')):
            monk=request(info,f'api/values?id=actors.buffs.monkenergy$monkability$dragonkick&hero_level={hero_level}&power={energy}')
            thresholds=next(b['rows'] for b in monk['blocks'] if b['title']=='武道振兴强化门槛')
            assert thresholds[points-1][-1]==expected_vigor
        backups = request(info,'api/backups')
        deadline=time.monotonic()+12
        while not backups['history'] and time.monotonic()<deadline:
            time.sleep(.2);backups=request(info,'api/backups')
        assert backups['history'][0]['hp']==20
        write(5)
        expected={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
        deadline=time.monotonic()+15
        while not any(r['hp']==5 for r in backups['history']) and time.monotonic()<deadline:
            time.sleep(.3);backups=request(info,'api/backups')
        assert any(r['hp']==5 for r in backups['history']), 'Automatic backup did not capture the changed save'
        request(info,'api/backups',{'action':'validate','context':backups['context']},state['token'])
        assert all(r['integrity']['valid'] for r in request(info,'api/backups')['history'])
        assert expected=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
        before=next(r for r in backups['history'] if r['hp']==20)
        preview=request(info,'api/backups/preview?'+urlencode({'slot':1,'id':before['id'],'context':backups['context']}))
        request(info,'api/backups',{'action':'restore','slot':1,'id':before['id'],'context':preview['context'],
                                 'expected_current':preview['expected_current'],'confirm':'恢复槽位 1'},state['token'])
        assert json.loads(gzip.decompress((folder/'game.dat').read_bytes()))['hero']['HP']==20
        undo=request(info,'api/backups')['undo'][0]
        undo_preview=request(info,'api/backups/undo-preview?'+urlencode({'slot':1,'id':undo['id'],'context':backups['context']}))
        assert undo_preview['current']['hp']==20 and undo_preview['target']['hp']==5
        request(info,'api/backups',{'action':'undo','slot':1,'id':undo['id'],'context':undo_preview['context'],
                                 'expected_current':undo_preview['expected_current'],'confirm':'撤回槽位 1'},state['token'])
        assert expected=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()},'Undo failed to recover the complete previous directory'
        game['hero']['class']='\ud800';write(5)
        malformed_original={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
        preview=request(info,'api/backups/preview?'+urlencode({'slot':1,'id':before['id'],'context':backups['context']}))
        request(info,'api/backups',{'action':'restore','slot':1,'id':before['id'],'context':preview['context'],
                                 'expected_current':preview['expected_current'],'confirm':'恢复槽位 1'},state['token'])
        unicode_undo=request(info,'api/backups')['undo'][0]
        assert unicode_undo['before']['class']=='\ud800'
        undo_preview=request(info,'api/backups/undo-preview?'+urlencode({'slot':1,'id':unicode_undo['id'],'context':backups['context']}))
        assert undo_preview['target']['class']=='\ud800'
        request(info,'api/backups',{'action':'undo','slot':1,'id':unicode_undo['id'],'context':undo_preview['context'],
                                 'expected_current':undo_preview['expected_current'],'confirm':'撤回槽位 1'},state['token'])
        assert malformed_original=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()}
        assert request(info,'api/status')['data']['hero']['hp']==5
        request(info,'api/shutdown',{},state['token']);process.wait(timeout=10)
        assert process.returncode==0
        report={'executable':str(exe),'fixture':str(work),'python_absent_from_path':True,
                'chinese_space_path':True,'different_working_directory':True,'numeric_tables':True,
                'automatic_changed_save_capture':True,'archives_verified':True,'save_bytes_unchanged':True,
                'equipment_augmentation_rounding':True,'class_armor_original_tier':True,'upgrade_risk_conditions':True,
                'controlled_restore_undo':True,'undo_preview_contract':True,'native_game_closed_check':True,
                'monk_fractional_energy':True,'unicode_undo_api_roundtrip':True,
                'normal_shutdown':True,'prebundled_native_helper':True,
                'native_helper_sha256':native['sha256'],'native_gui_exercised':False}
        (work/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))
        return report
    finally:
        if process.poll() is None:
            if info:
                try:
                    state=request(info,'api/status');request(info,'api/shutdown',{},state['token'])
                    process.wait(timeout=10)
                except Exception:
                    process.terminate();process.wait(timeout=10)
            else: process.terminate();process.wait(timeout=10)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('executable',type=Path)
    verify(parser.parse_args().executable.resolve())
