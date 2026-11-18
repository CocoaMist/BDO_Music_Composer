# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_dynamic_libs,
    get_package_paths,
)


project_root = Path(SPECPATH).parents[1]
diagnostic_console = (
    os.environ.get("BDO_DIAGNOSTIC_CONSOLE", "").strip() == "1"
)
license_inventory_value = os.environ.get(
    "BDO_TRANSCRIPTION_LICENSE_DIR",
    "",
).strip()
if not license_inventory_value:
    raise SystemExit(
        "Missing generated dependency/license inventory. "
        "Run packaging/windows/build.ps1."
    )
license_inventory_dir = Path(license_inventory_value)
if not license_inventory_dir.is_dir():
    raise SystemExit(
        "Missing generated dependency/license inventory. "
        "Run packaging/windows/build.ps1."
    )

_basic_pitch_parent, basic_pitch_package = get_package_paths("basic_pitch")
basic_pitch_package = Path(basic_pitch_package)
onnx_model = (
    basic_pitch_package
    / "saved_models"
    / "icassp_2022"
    / "nmp.onnx"
)
if not onnx_model.is_file():
    raise SystemExit(
        "Basic Pitch ONNX model is missing. "
        "Run scripts/install_transcription.ps1 first."
    )

# BDO Music Composer ships one Windows package with the CPU ONNX backend.
# Upstream's unused TensorFlow, TFLite, and Core ML backends and alternate
# model formats stay excluded from that package.
non_onnx_backend_excludes = [
    "tensorflow",
    "tensorflow_cpu",
    "tensorflow_intel",
    "tensorflow_macos",
    "keras",
    "tensorboard",
    "coremltools",
    "tflite_runtime",
]

datas = [
    (str(project_root / "assets" / "ui" / "timeline_background.png"), "assets/ui"),
    (str(project_root / "assets" / "ui" / "timeline_background_v2.webp"), "assets/ui"),
    (str(project_root / "assets" / "ui" / "score_agent_portrait.webp"), "assets/ui"),
    (str(project_root / "assets" / "ui" / "home" / "home_moonlit_atelier_v3.webp"), "assets/ui/home"),
    (str(project_root / "assets" / "ui" / "about" / "chatgpt_avatar.webp"), "assets/ui/about"),
    (str(project_root / "assets" / "ui" / "about" / "cocoamist_avatar.webp"), "assets/ui/about"),
    (str(project_root / "assets" / "instruments" / "ai_v1"), "assets/instruments/ai_v1"),
    (str(project_root / "assets" / "icons" / "app_icon.png"), "assets/icons"),
    (str(project_root / "assets" / "icons" / "indicators"), "assets/icons/indicators"),
    (str(project_root / "assets" / "icons" / "shai_ensemble_mark.png"), "assets/icons"),
    (str(project_root / "assets" / "fonts"), "assets/fonts"),
    (str(project_root / "data" / "mappings" / "bdo_wwise_midi_map.json"), "data/mappings"),
    (str(project_root / "data" / "profiles" / "bdo_global_v9.json"), "data/profiles"),
    (
        str(onnx_model),
        "basic_pitch/saved_models/icassp_2022",
    ),
    (
        str(project_root / "LICENSE"),
        "licenses",
    ),
    (
        str(project_root / "THIRD_PARTY_NOTICES.md"),
        "licenses",
    ),
    (
        str(project_root / "packaging" / "transcription_release_policy.json"),
        "licenses/transcription",
    ),
    (
        str(license_inventory_dir),
        "licenses/transcription",
    ),
]

hiddenimports = [
    "PySide6.QtMultimedia",
    "basic_pitch",
    "basic_pitch.constants",
    "basic_pitch.inference",
    "basic_pitch.note_creation",
    "onnxruntime",
    "onnxruntime.capi._pybind_state",
    "onnxruntime.capi.onnxruntime_pybind11_state",
    "soundfile",
    "soxr",
]

# QtWebView loads its Windows backend as a plugin at runtime.
webview_backend = collect_dynamic_libs(
    "PySide6", search_patterns=["qtwebview_webview2.dll"]
)

a = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root / "src"), str(project_root)],
    binaries=[*collect_dynamic_libs("onnxruntime"), *webview_backend],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", *non_onnx_backend_excludes],
    noarchive=False,
    optimize=1,
)

# Qt's generic image-format hook collects the PDF rasterizer. Composer accepts
# raster artwork and displays web documents through the system WebView2.
unused_qt_pdf_binaries = {
    "pyside6/qt6pdf.dll",
    "pyside6/plugins/imageformats/qpdf.dll",
}
a.binaries = [
    entry for entry in a.binaries
    if entry[0].replace("\\", "/").casefold() not in unused_qt_pdf_binaries
]

# Keep the Qt catalogs for the languages exposed by the desktop application.
qt_locale_suffixes = ("_en.qm", "_zh_cn.qm", "_zh_tw.qm", "_ja.qm", "_ko.qm")
a.datas = [
    entry for entry in a.datas
    if not entry[0].replace("\\", "/").casefold().startswith("pyside6/translations/")
    or entry[0].casefold().endswith(qt_locale_suffixes)
]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="BDO-Music-Composer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[
        "onnxruntime.dll",
        "onnxruntime_providers_shared.dll",
    ],
    console=diagnostic_console,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / "assets" / "icons" / "app_icon.ico"),
)
