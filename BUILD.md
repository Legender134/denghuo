# Windows build

Player builds do not require Python. This file describes rebuilding the source
for development or replacing the unmodified LGPL tray library.

Use Windows x64, Python 3.13 with Tk, and the supplied source tree. Create an
isolated venv and install the pinned build requirements:

```powershell
python -m venv .local/desktop-build
.local/desktop-build/Scripts/python.exe -m pip install -r requirements-desktop.txt
python -m unittest discover -s tests
.local/desktop-build/Scripts/python.exe tools/build_desktop.py
```

The final line prints the directory containing `灯火.exe` and `_internal/`.
To replace pystray, install the desired LGPL-compatible modified source into
that venv before building. Python bytecode is not signed or otherwise locked.

`tools/verify_desktop.py <directory>/灯火.exe` tests the frozen service, numeric
results, automatic backup and shutdown with Python removed from PATH. Use a
normal system Python to run that verifier; it does not use Python to run the app.

For a complete distributable, place the supplied pinned
`Shattered-Pixel-Dungeon-4.0.1-source.zip` under `.local/`. The archive can also
be rebuilt with `git archive --format=zip` from official revision
`e9defd0444c96d2fce3de5ec297c3398be8b7c55`.
Install the signed official Inno Setup 7.1.0 compiler, then run:

```powershell
python tools/package_desktop.py <app-directory> --python-root <Python313> --build-env .local/desktop-build --inno <InnoSetup-directory>
python tools/build_installer.py <app-directory> --compiler <InnoSetup-directory>/ISCC.exe
```

The package script downloads unchanged pystray source and license texts from
their authors, includes all application sources and pinned game sources,
and excludes personal settings, saves, logs and research checkouts. It records
per-file hashes in the desktop ZIP. The source-only ZIP is reproducible in the
same Python/zlib environment; the frozen PE and installer builds are not claimed
to be byte-for-byte reproducible. Do not distribute an archive assembled by
recursively copying the workspace.
