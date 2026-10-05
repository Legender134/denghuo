# Third-party notices

`data/catalog.json` contains Chinese names and descriptions derived from the official Shattered Pixel Dungeon translation resources. Equipment tiers, artifact level caps, class armor metadata and the standard strength requirement formula were checked against that game's source code.

`data/numeric_rules.json` also contains the complete indexed members of 1,301 Java files in the game's core and SPD-classes engine, including original comments and copyright notices where present. It is a derivative source reference under the same GPL-3.0-or-later license. Runtime tables are based on these rules; unsupported dynamic conditions remain in the original source rather than being approximated.

- Source: https://github.com/00-Evan/shattered-pixel-dungeon
- Revision: `e9defd0444c96d2fce3de5ec297c3398be8b7c55`
- Version: 4.0.1 (version code 920)
- Pixel Dungeon: Copyright (C) 2012–2015 Oleg Dolya
- Shattered Pixel Dungeon: Copyright (C) 2014–2026 Evan Debenham
- Chinese translation: Shattered Pixel Dungeon translation contributors
- License: GNU General Public License, version 3 or later

The development checkout at `.research/upstream` retains the original source and notices. It is not included in the local delivery ZIP; the pinned source is available at the repository and revision above. The full license is in `LICENSE.txt`. No endorsement by the original game's author is implied.

## Independent Windows package

The frozen application includes unmodified Python 3.13, Tcl/Tk, Pillow 12.0.0,
pystray 0.19.5 and six 1.17.0. It is built using PyInstaller 6.22.0; its bootloader
exception permits embedding the unmodified bootloader. The installer is built
using Inno Setup 7.1.0. Original copyright and license texts are in `licenses/`:
Python (PSF and included notices), Tcl/Tk (BSD-style), Pillow (MIT-CMU and included
component notices), pystray (LGPL-3.0), six (MIT), OpenSSL (Apache-2.0),
PyInstaller (GPL with bootloader exception), and Inno Setup (author license).

`corresponding-source/` contains this application's complete source ZIP and build
scripts, the unchanged pystray 0.19.5 source distribution, and the pinned official
Shattered Pixel Dungeon 4.0.1 source archive. These files are for license and
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
