# PyInstaller spec for the Windows build: python -m PyInstaller SoundscapePreviewer.spec
# Produces dist/SoundscapePreviewer/SoundscapePreviewer.exe (one folder, fast startup).

# Qt modules the app never uses; leaving them out keeps the download small.
QT_EXCLUDES = [
    "PySide6.Qt3DAnimation", "PySide6.Qt3DCore", "PySide6.Qt3DExtras", "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic", "PySide6.Qt3DRender", "PySide6.QtBluetooth", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtLocation", "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets", "PySide6.QtNetworkAuth", "PySide6.QtNfc", "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets", "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtPositioning",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets", "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtSensors",
    "PySide6.QtSerialBus", "PySide6.QtSerialPort", "PySide6.QtSpatialAudio", "PySide6.QtSql",
    "PySide6.QtStateMachine", "PySide6.QtSvg", "PySide6.QtSvgWidgets", "PySide6.QtTest",
    "PySide6.QtTextToSpeech", "PySide6.QtWebChannel", "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick", "PySide6.QtWebEngineWidgets", "PySide6.QtWebSockets",
    "PySide6.QtWebView", "PySide6.QtHttpServer", "PySide6.QtDesigner", "PySide6.QtHelp",
    "PySide6.QtUiTools", "PySide6.QtXml", "PySide6.QtConcurrent", "PySide6.QtDBus",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("LICENSE", "."), ("README.md", ".")],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=QT_EXCLUDES + ["tkinter", "unittest", "pydoc_data"],
    noarchive=False,
)

# Qt pulls these in through plugins we don't need (virtual keyboard, PDF images,
# TLS/networking, software OpenGL, translations of Qt's own dialogs).
DROP = (
    "opengl32sw.dll", "qtvirtualkeyboardplugin", "qpdf.dll", "qt6pdf", "qt6quick", "qt6qml",
    "qt6virtualkeyboard", "plugins/tls", "plugins/networkinformation", "libcrypto", "libssl",
    "pyside6/translations",
)


def _keep(entry):
    dest = entry[0].replace("\\", "/").lower()
    return not any(d in dest for d in DROP)


a.binaries = [b for b in a.binaries if _keep(b)]
a.datas = [d for d in a.datas if _keep(d)]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SoundscapePreviewer",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="SoundscapePreviewer")
