# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


project_dir = Path(SPECPATH)


def _tcl_tk_data() -> list:
    import tkinter

    tcl_dir = Path(tkinter.Tcl().eval("info library"))
    tk_dir = tcl_dir.parent / f"tk{tkinter.TkVersion}"
    datas = []
    for source_root, target_root in ((tcl_dir, "_tcl_data"), (tk_dir, "_tk_data")):
        if not source_root.exists():
            continue
        for path in source_root.rglob("*"):
            if path.is_file():
                if "demos" in path.relative_to(source_root).parts:
                    continue
                target_dir = Path(target_root) / path.parent.relative_to(source_root)
                datas.append((str(path), str(target_dir)))
    return datas


datas = []
datas += collect_data_files("playwright")
datas += collect_data_files("customtkinter")
datas += _tcl_tk_data()
datas += [
    (str(project_dir / "icon" / "app.ico"), "icon"),
    (str(project_dir / "icon" / "app-icon.png"), "icon"),
]

hiddenimports = []
hiddenimports += collect_submodules("playwright")
hiddenimports += collect_submodules("customtkinter")


a = Analysis(
    ["app.py"],
    pathex=[str(project_dir)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["numpy"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NVIDIARegister",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_dir / "icon" / "app.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="NVIDIARegister-Fast",
)
