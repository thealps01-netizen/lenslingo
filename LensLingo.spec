# -*- mode: python ; coding: utf-8 -*-

# LensLingo, EasyOCR + Torch yığınını kullanır. Bu ağır paketlerin veri
# dosyalarını, ikili bağımlılıklarını ve gizli importlarını PyInstaller'ın
# otomatik toplaması için collect_all kullanıyoruz.
from PyInstaller.utils.hooks import collect_all

datas = [('lenslingo.ico', '.')]
binaries = []
hiddenimports = []

for _pkg in ('easyocr', 'torch', 'torchvision', 'cv2', 'scipy', 'skimage',
             'shapely', 'pyclipper', 'bidi', 'numpy', 'PIL'):
    try:
        _d, _b, _h = collect_all(_pkg)
        datas += _d
        binaries += _b
        hiddenimports += _h
    except Exception:
        pass


a = Analysis(
    ['lenslingo.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'tkinter', 'PyQt6.QtBluetooth', 'PyQt6.QtDBus', 'PyQt6.QtLocation', 'PyQt6.QtMultimedia', 'PyQt6.QtMultimediaWidgets', 'PyQt6.QtNfc', 'PyQt6.QtPdf', 'PyQt6.QtPositioning', 'PyQt6.QtPrintSupport', 'PyQt6.QtQml', 'PyQt6.QtQuick', 'PyQt6.QtQuick3D', 'PyQt6.QtRemoteObjects', 'PyQt6.QtSensors', 'PyQt6.QtSerialPort', 'PyQt6.QtSql', 'PyQt6.QtSvg', 'PyQt6.QtSvgWidgets', 'PyQt6.QtTest', 'PyQt6.QtWebChannel', 'PyQt6.QtWebEngine', 'PyQt6.QtWebEngineCore', 'PyQt6.QtWebEngineWidgets', 'PyQt6.QtWebSockets', 'PyQt6.QtXml', 'PyQt6.Qt3DAnimation', 'PyQt6.Qt3DCore', 'PyQt6.Qt3DExtras', 'PyQt6.Qt3DInput', 'PyQt6.Qt3DLogic', 'PyQt6.Qt3DRender', 'PyQt6.QtCharts', 'PyQt6.QtDataVisualization', 'PyQt6.QtOpenGL', 'PyQt6.QtOpenGLWidgets'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='LensLingo',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['lenslingo.ico'],
    # Embedded application manifest (DPI awareness, UAC, OS compatibility)
    manifest='lenslingo.manifest',
    # Windows file version info (shown in exe Properties dialog)
    version='file_version_info.txt',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='LensLingo',
)
