"""Build dist/ShadowHeartsRandomizer.exe (one file, no console) with PyInstaller.

usage: .venv/Scripts/python.exe build.py   (installs PyInstaller into the venv if it is missing)
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "-r",
                               os.path.join(HERE, "requirements-build.txt")])
    subprocess.check_call([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", "ShadowHeartsRandomizer",
        # only QtCore/QtGui/QtWidgets are used; keep the rest of Qt out of the exe
        "--exclude-module", "PySide6.QtNetwork", "--exclude-module", "PySide6.QtQml",
        "--exclude-module", "PySide6.QtQuick", "--exclude-module", "PySide6.QtPdf",
        "--exclude-module", "PySide6.QtWebEngineCore", "--exclude-module", "PySide6.QtMultimedia",
        os.path.join(HERE, "run_gui.pyw")], cwd=HERE)
    print("built", os.path.join(HERE, "dist", "ShadowHeartsRandomizer.exe"))


if __name__ == "__main__":
    main()
