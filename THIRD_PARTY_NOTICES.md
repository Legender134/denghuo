# Third-party notices

`data/catalog.json` contains Chinese names and descriptions derived from the official Shattered Pixel Dungeon translation resources. Equipment tiers, artifact level caps, class armor metadata and the standard strength requirement formula were checked against that game's source code.

`data/numeric_rules.json` also contains the complete indexed members of 1,301 Java files in the game's core and SPD-classes engine, including original comments and copyright notices where present. It is a derivative source reference under the same GPL-3.0-or-later license. Runtime tables are based on these rules; unsupported dynamic conditions remain in the original source rather than being approximated.

- Source: https://github.com/00-Evan/shattered-pixel-dungeon
- Revision: `57a4e06a4caf162446d1c28caa7983f0493fecf0`
- Version: 4.0.2 (version code 922)
- Pixel Dungeon: Copyright (C) 2012–2015 Oleg Dolya
- Shattered Pixel Dungeon: Copyright (C) 2014–2026 Evan Debenham
- Chinese translation: Shattered Pixel Dungeon translation contributors
- License: GNU General Public License, version 3 or later

`companion/values_resources.py` ports the dew-consumption and recovery branches from `Waterskin.execute`, `Dewdrop.consumeDew`, `VialOfBlood` and `Healing.setHeal` at the fixed revision above. Its arithmetic follows the original Java single-precision operations before rounding and is a GPL-3.0-or-later derivative. Player-facing provenance links point to the same commit. Other reviewed calculation tables retain the same source and license obligations.

`companion/public_source_data.py`, `public_talents.py`, `public_item_levels.py`, `public_item_state.py`, `character_scene.py`, `character_comparison.py` and `alchemy_flow.py` reuse or translate public type constants, talent eligibility, known item levels, strength and recipe branches from that same pinned game source. `tools/alchemy_catalog.py` records recipe provenance in `data/catalog.json`. These are GPL-3.0-or-later derivatives with the original game copyrights identified above; unknown or hidden runtime conditions are not inferred as player knowledge.

`companion/engine.py`, `rules.py`, `values.py` and `values_decisions.py` also translate the fifteen ordinary missile strength, damage, throwing-delay and accuracy branches, plus type-specific upgrade-curse branches, from the same pinned `MissileWeapon`, item subclasses, `Weapon`, `Item`, `Armor`, `Wand`, `Ring` and `ScrollOfUpgrade` sources. These are GPL-3.0-or-later derivatives; player-facing conditions and provenance retain the source distinctions.

Workflow design was informed by official Ludusavi, Path of Building Community, Teamcraft and FactorioLab documentation and their MIT main repositories, and by other assistants' public documentation. No Ludusavi, Path of Building, Teamcraft, FactorioLab, Hearthstone Deck Tracker, Destiny Item Manager or Blish HUD application code was copied into this implementation; their names identify design comparisons, not bundled dependencies or endorsements. The game arithmetic identified above is the actual code-derived reuse.

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
