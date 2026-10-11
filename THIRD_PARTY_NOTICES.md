# Third-party notices

`data/catalog.json` contains Chinese names and descriptions derived from the official Shattered Pixel Dungeon translation resources. Equipment tiers, artifact level caps, class armor metadata and the standard strength requirement formula were checked against that game's source code.

`data/numeric_rules.json` also contains the complete indexed members of 1,301 Java files in the game's core and SPD-classes engine, including original comments and copyright notices where present. It is a derivative source reference under the same GPL-3.0-or-later license. Runtime tables are based on these rules; unsupported dynamic conditions remain in the original source rather than being approximated.

`data/monster_reference.json`, `tools/build_monster_reference.py` and `companion/monster_reference.py` derive the official Bestiary roster, normal enemy statistics, generation-depth branches, ordinary loot pools, limited-drop counters and fixed rewards from the same pinned game sources below, under GPL-3.0-or-later with the same original game copyrights. The generated reference records the original file paths and normalized UTF-8 SHA-256 hashes; player calculations separate unconditional rewards from level-gated and count-dependent drops. It does not predict an individual random death drop or assume that the initial artifact pool remains unchanged in a played game.

- Source: https://github.com/00-Evan/shattered-pixel-dungeon
- Revision: `57a4e06a4caf162446d1c28caa7983f0493fecf0`
- Version: 4.0.2 (version code 922)
- Pixel Dungeon: Copyright (C) 2012–2015 Oleg Dolya
- Shattered Pixel Dungeon: Copyright (C) 2014–2026 Evan Debenham
- Chinese translation: Shattered Pixel Dungeon translation contributors
- License: GNU General Public License, version 3 or later

`companion/values_resources.py` ports the dew-consumption and recovery branches from `Waterskin.execute`, `Dewdrop.consumeDew`, `VialOfBlood` and `Healing.setHeal` at the fixed revision above. Its arithmetic follows the original Java single-precision operations before rounding and is a GPL-3.0-or-later derivative. Player-facing provenance links point to the same commit. Other reviewed calculation tables retain the same source and license obligations.

`companion/game_math.py`, `decisions.py` and `engine.py` also translate the public remaining-healing projection, `Healing.healingThisTick` / `setHeal`, `PotionOfHealing` pool and `VialOfBlood` limit branches from that same revision under GPL-3.0-or-later. `global_progress.py` checks the two byte-preserved global file structures against `Badges`, `Rankings`, `Bundle` and `FileUtils`; it does not instantiate game objects or edit their statistics. The game copyrights above apply to the translated arithmetic.

`companion/public_source_data.py`, `public_talents.py`, `public_item_levels.py`, `public_item_state.py`, `character_scene.py`, `character_comparison.py` and `alchemy_flow.py` reuse or translate public type constants, talent eligibility, known item levels, strength and recipe branches from that same pinned game source. `tools/alchemy_catalog.py` records recipe provenance in `data/catalog.json`. These are GPL-3.0-or-later derivatives with the original game copyrights identified above; unknown or hidden runtime conditions are not inferred as player knowledge.

`companion/public_build.py` also translates the pinned `Talent` initialization and replacement rules and the nineteen `ArmorAbility.talents` mappings. Ring comparisons in `combat_context.py`, `values.py` and `values_investment.py` distinguish the original `Ring.getBonus` and `getBuffedBonus` channels, including `EnhancedRings` and `SpiritForm`. These GPL-3.0-or-later derivatives retain the same game revision and copyrights above.

`companion/engine.py`, `rules.py`, `values.py` and `values_decisions.py` also translate the fifteen ordinary missile strength, damage, throwing-delay and accuracy branches, plus type-specific upgrade-curse branches, from the same pinned `MissileWeapon`, item subclasses, `Weapon`, `Item`, `Armor`, `Wand`, `Ring` and `ScrollOfUpgrade` sources. These are GPL-3.0-or-later derivatives; player-facing conditions and provenance retain the source distinctions.

`companion/values_investment.py` also translates the displayed-level, resin, curse-infusion and hardening upgrade branches from those fixed `Item`, `Weapon`, `Armor`, `Wand` and `ScrollOfUpgrade` sources. `values.py` follows `ScrollOfRetribution` single-precision damage arithmetic. `engine.py` reads existing player records according to `Notes` and `Item.customNote`; these GPL-3.0-or-later derivatives retain the same game copyrights and source revision. Stored hidden infusion flags and base levels are not automatically treated as player knowledge.

Workflow design was informed by official Ludusavi, Path of Building Community, Teamcraft and FactorioLab documentation and their MIT main repositories, and by other assistants' public documentation. No Ludusavi, Path of Building, Teamcraft, FactorioLab, Hearthstone Deck Tracker, Destiny Item Manager or Blish HUD application code was copied into this implementation; their names identify design comparisons, not bundled dependencies or endorsements. The game arithmetic identified above is the actual code-derived reuse.

`companion/scouting.py` interprets the pinned 4.0.2 `Level`, `Terrain`, `Heap`, `Trap`, `Mimic`, `Statue`, `ArmoredStatue` and `Thief` save fields under the same game copyright and GPL-3.0-or-later terms. The common Bundle layout was also checked against the official [v4.0.1 source](https://github.com/00-Evan/shattered-pixel-dungeon/tree/v4.0.1). It exposes only explicitly requested, already generated saved floors; it does not generate future levels or treat hidden saved information as in-game identification.

`companion/combat_context.py` translates bounded ordinary melee branches from `Hero.attackSkill` / `damageRoll`, `Weapon.delayFactor`, `Char.hit` and the Force, Furor and Accuracy rings at the same pinned revision under GPL-3.0-or-later. It preserves Java single-precision boundaries and the infinite-evasion precedence; its manual target model does not simulate damage distributions, procs, mean DPS or time-to-kill. `public_skills.py` and `public_talents.py` check publicly saved skill eligibility against `Talent`, `HeroClass`, `HeroSubClass`, armor abilities and the corresponding spells. The original game copyrights above apply. Destiny Item Manager's MIT repository also informed refresh continuity; no application code from that repository is bundled.

The optional development checkout at `.research/player-upstream-4.0.2` retains the original source and notices. It is excluded from the source-only ZIP; the pinned source is available at the repository and revision above, with fetch/archive commands in `BUILD.md`. Player packages include it in `corresponding-source/`. The full license is in `LICENSE.txt`. No endorsement by the original game's author is implied.

## Independent Windows package

The frozen application includes unmodified Python, Tcl/Tk, Pillow 12.0.0,
pystray 0.19.5 and six 1.17.0. It is built using PyInstaller 6.22.0; its bootloader
exception permits embedding the unmodified bootloader. The installer is built
using Inno Setup 7.1.0. Original copyright and license texts are in `licenses/`:
Python (PSF and included notices), Tcl/Tk (BSD-style), Pillow (MIT-CMU and included
component notices), pystray (LGPL-3.0), six (MIT), OpenSSL (Apache-2.0),
PyInstaller (GPL with bootloader exception), and Inno Setup (author license).

`corresponding-source/` contains this application's complete source ZIP and build
scripts, the unchanged pystray 0.19.5 source distribution, and the pinned official
Shattered Pixel Dungeon 4.0.2 source archive. These files are for license and
development purposes; gameplay screens do not require reading them. To replace
the LGPL library, use its source and the application build instructions to
rebuild the directory package. No third-party code or runtime binary was patched.

- Python: https://www.python.org/
- Tcl/Tk: https://www.tcl-lang.org/
- Pillow: https://github.com/python-pillow/Pillow
- pystray: https://github.com/moses-palmer/pystray
- six: https://github.com/benjaminp/six
- OpenSSL: https://www.openssl.org/
- PyInstaller: https://pyinstaller.org/
- Inno Setup: https://jrsoftware.org/isinfo.php

The standard Windows desktop controls helper is this project's own C# source in
`native/`, compiled against Microsoft's fixed Framework 4.0 reference assemblies
from `Microsoft.NETFramework.ReferenceAssemblies.net40` 1.0.3. The reference
assemblies are build inputs only and are not redistributed as runtime files.
The player package includes the compiled helper and its adjacent runtime config
under `_internal/native/`; players do not need a compiler or development SDK.
The complete helper source, manifest, config and build script are included in
this application's corresponding source ZIP.


## Offline seed reference engine

`web/forecast.wasm` includes the unmodified Rust core of [Shattered Pixel Dungeon Seed Seeker](https://github.com/akhial/shpd-seed-seeker/tree/b3596f5c0d26852acc20bb6de4f2169ebcbdd24a), commit `b3596f5c0d26852acc20bb6de4f2169ebcbdd24a`, and this project's small browser adapter. Seed Seeker is GPL-3.0-or-later; its original `COPYING` and `NOTICE` are in `third_party/seed_seeker/`. Its pinned Shattered Pixel Dungeon target is 4.0.2 build 922, game commit `57a4e06a4caf162446d1c28caa7983f0493fecf0`, with the original game attribution above.

The exact corresponding Rust source, build manifests, dependency lockfile, original notices, compatibility document and upstream regression fixtures are supplied in `third_party/seed_seeker/engine-source.zip`. The adjacent `source.json` lists the source-file and compiled-module hashes. `tools/build_forecast.py` verifies and builds that source; `BUILD.md` explains the toolchain. The application source archive also includes these files. Exact Cargo dependency copyright and license texts are supplied in `third_party/seed_seeker/CARGO-NOTICES.txt` and in the source archive. Rust standard-library copyright and referenced licenses are retained under `rust-runtime/` in that archive. Dependency package versions/checksums remain pinned in Cargo.lock. No runtime network access or Rust installation is required.

The canonical new-run reference is explicitly separate from actual save inspection. It is not a reconstruction of a played run's generator state, consumable inventory or random monster death loot. `data/forecast_items.json` maps the 117 engine equipment/candidate IDs to this application's game-derived Chinese catalog; the forecast interface uses no upstream artwork. The corresponding source archive retains the original source resources, including upstream artwork and its original attribution.
