"""Read-only, bounded readers for Shattered Pixel Dungeon's Bundle saves."""

from __future__ import annotations

import gzip
import io
import json
import math
import os
from pathlib import Path
import zlib

MAX_BYTES = 16 * 1024 * 1024
LEVEL_TYPES={'SewerLevel','SewerBossLevel','PrisonLevel','PrisonBossLevel','CavesLevel','CavesBossLevel',
             'CityLevel','CityBossLevel','HallsLevel','HallsBossLevel','LastLevel','LastShopLevel',
             'DeadEndLevel','MiningLevel','VaultLevel'}


class SaveError(ValueError):
    pass


def file_stamp(stat):
    return stat.st_mtime_ns, stat.st_size, stat.st_ino


def bundle_integer(text):
    value = int(text)
    if not -(2**63) <= value < 2**63:
        raise SaveError("存档包含超出范围的整数，等待新的完整保存")
    return value


def bundle_float(text):
    value = float(text)
    if not math.isfinite(value):
        raise SaveError("存档包含无效数值，等待新的完整保存")
    return value


def invalid_constant(_):
    raise SaveError("存档包含无效数值，等待新的完整保存")


def validate_hero(game):
    hero = game.get("hero")
    if not isinstance(hero, dict) or not isinstance(hero.get("class"), str):
        raise SaveError("未找到角色信息")
    for field in ("HP", "HT"):
        value = hero.get(field)
        # Real game HP is a Java int; reject malformed values before float coercion.
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not -2_147_483_648 <= value <= 2_147_483_647 or not math.isfinite(value)):
            raise SaveError("角色生命数据不完整，稍后重试")
    if hero["HT"] <= 0:
        raise SaveError("角色最大生命数据不正确")
    for field in ("STR", "lvl"):
        value = hero.get(field)
        if type(value) is not int or not 1 <= value <= 2_147_483_647:
            raise SaveError("角色力量或等级数据不完整，稍后重试")
    for field in ("inventory", "buffs"):
        if field in hero and not isinstance(hero[field], list):
            raise SaveError("角色背包或状态结构不完整，稍后重试")


def validate_location(game):
    depth, branch = game.get("depth"), game.get("branch", 0)
    if type(depth) is not int or not 0 <= depth <= 999 or type(branch) is not int or not 0 <= branch <= 20:
        raise SaveError("不支持的楼层信息")
    return depth, branch


def validate_level(bundle):
    level = bundle.get('level')
    if not isinstance(level, dict):
        raise SaveError('楼层存档缺少完整地图结构，尚未操作存档')
    width,height=level.get('width'),level.get('height')
    if (type(width) is not int or type(height) is not int
            or not 1<=width<=1024 or not 1<=height<=1024):
        raise SaveError('楼层地图尺寸无效，尚未操作存档')
    if not isinstance(level.get('__className'),str) or level['__className'] not in {'com.shatteredpixel.shatteredpixeldungeon.levels.'+name for name in LEVEL_TYPES}:
        raise SaveError('楼层类型缺失或尚未支持，尚未操作存档')
    if type(level.get('version')) is not int or not 1<=level['version']<=2147483647:
        raise SaveError('楼层版本数据缺失或无效，尚未操作存档')
    length=width*height
    for name in ('map','visited','mapped'):
        cells=level.get(name)
        expected=int if name=='map' else bool
        if (not isinstance(cells,list) or len(cells)!=length
                or any(type(cell) is not expected for cell in cells)):
            raise SaveError('楼层地图数组不完整，尚未操作存档')
        if name == 'map' and any(not 0 <= cell < 256 for cell in cells):
            raise SaveError('楼层地形编号无效，尚未操作存档')
    return level


def validate_floor_members(game, names):
    depth,branch=validate_location(game)
    expected={f'depth{depth}'+(f'-branch{branch}' if branch else '')+'.dat'}
    generated=game.get('generated_levels')
    version=game.get('version')
    if version is not None and (type(version) is not int or not 0<=version<=2147483647):
        raise SaveError('存档版本数据无效，尚未操作存档')
    if generated is None and (version or 0)<833:
        # Older/unknown formats may not record this list; never invent prior floors.
        generated=[]
    if not isinstance(generated,list) or len(generated)>128:
        raise SaveError('已生成楼层记录缺失或无效，尚未操作存档')
    for encoded in generated:
        if type(encoded) is not int or not 0<encoded<=20026:
            raise SaveError('已生成楼层编号无效，尚未操作存档')
        floor_branch,floor_depth=divmod(encoded,1000)
        if not 1<=floor_depth<=26 or not 0<=floor_branch<=20:
            raise SaveError('已生成楼层编号无效，尚未操作存档')
        expected.add(f'depth{floor_depth}'+(f'-branch{floor_branch}' if floor_branch else '')+'.dat')
    if not expected.issubset(set(names)):
        raise SaveError('备份缺少已生成的历史楼层，尚未操作存档')


def default_root() -> Path:
    return Path(os.environ.get("APPDATA", str(Path.home()))) / ".shatteredpixel" / "Shattered Pixel Dungeon"


def read_bundle(path: Path) -> dict:
    """No repair, rename, write, or fallback to a different save ever occurs here."""
    try:
        before = path.stat()
        if before.st_size <= 1:
            raise SaveError("空存档（此槽位可能已结束）")
        if before.st_size > MAX_BYTES:
            raise SaveError("存档过大，未读取")
        with path.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        after = path.stat()
        if file_stamp(before) != file_stamp(after):
            raise SaveError("游戏正在写入存档，稍后重试")
        return read_bundle_data(raw)
    except SaveError:
        raise
    except (OSError, ValueError, EOFError, RecursionError, OverflowError, zlib.error) as exc:
        raise SaveError("存档暂时无法读取，可能正在保存或格式不兼容") from exc


def read_bundle_data(raw: bytes) -> dict:
    """Apply the same bounded decoder to a verified archive member."""
    try:
        if len(raw) <= 1:
            raise SaveError("空存档（此槽位可能已结束）")
        if len(raw) > MAX_BYTES:
            raise SaveError("存档过大，未读取")
        if raw.startswith(b"\x1f\x8b"):
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise SaveError("解压后的存档过大，未读取")
        bundle = json.loads(raw.decode("utf-8-sig"), parse_int=bundle_integer,
                            parse_float=bundle_float, parse_constant=invalid_constant)
        if not isinstance(bundle, dict):
            raise SaveError("不支持的存档结构")
        return bundle
    except SaveError:
        raise
    except (OSError, ValueError, EOFError, RecursionError, OverflowError, zlib.error) as exc:
        raise SaveError("存档暂时无法读取，可能正在保存或格式不兼容") from exc


def list_slots(root: Path) -> list[dict]:
    result = []
    for number in range(1, 7):
        path = root / f"game{number}" / "game.dat"
        if not path.is_file():
            continue
        row = {"id": number, "path": str(path), "modified": 0, "valid": False}
        try:
            row["modified"] = path.stat().st_mtime
            game = read_bundle(path)
            validate_hero(game)
            validate_location(game)
            hero = game.get("hero")
            row.update(valid=True, hero_class=hero["class"], depth=game.get("depth"),
                       level=hero.get("lvl"), hp=hero["HP"], version=game.get("version"))
        except (SaveError, OSError) as exc:
            row["error"] = str(exc)
        result.append(row)
    return result


def read_slot(root: Path, number: int) -> tuple[dict, dict | None, float, str]:
    if number not in range(1, 7):
        raise SaveError("无效的槽位")
    path = root / f"game{number}" / "game.dat"
    try:
        game_stat = path.stat()
    except FileNotFoundError as exc:
        raise SaveError("此槽位尚未保存，请先在游戏中保存，或在连接设置中选择其他槽位") from exc
    except OSError as exc:
        raise SaveError("暂时无法访问此槽位，请检查存档目录的访问权限") from exc
    game = read_bundle(path)
    validate_hero(game)
    modified = game_stat.st_mtime
    depth, branch = validate_location(game)
    level_path = path.parent / (f"depth{depth}.dat" if branch == 0 else f"depth{depth}-branch{branch}.dat")
    level, warning = None, ""
    level_stat = None
    if level_path.exists():
        try:
            level_stat = level_path.stat()
            level = read_bundle(level_path).get("level")
            if not isinstance(level, dict):
                level = None
                warning = "当前地图结构不完整，地图暂不展示"
            elif (level_stat.st_mtime_ns < game_stat.st_mtime_ns
                  or level_stat.st_mtime_ns - game_stat.st_mtime_ns > 10_000_000_000):
                warning = "地图与角色保存时间不一致，地图暂不展示"
                level = None
            elif file_stamp(level_stat) != file_stamp(level_path.stat()):
                warning = "地图正在保存，稍后自动重读"
                level = None
        except (SaveError, OSError):
            warning = "当前地图暂时无法读取"
            level = None
    else:
        warning = "当前楼层地图尚未保存"
    # The hero can be replaced while the depth file is being decoded. Never label
    # that earlier hero with the new file's timestamp or combine the two saves.
    try:
        final_stamp = file_stamp(path.stat())
    except OSError as exc:
        raise SaveError("角色存档在读取期间无法访问，稍后自动重试") from exc
    if file_stamp(game_stat) != final_stamp:
        raise SaveError("游戏正在写入存档，稍后重试")
    if level is not None and level_stat is not None:
        try:
            if file_stamp(level_stat) != file_stamp(level_path.stat()):
                level, warning = None, "地图正在保存，稍后自动重读"
        except OSError:
            level, warning = None, "当前地图暂时无法读取"
    return game, level, modified, warning
