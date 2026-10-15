#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the zip to upload to plugins.qgis.org (or install via "Install from ZIP").

Usage:  python scripts/package.py
Output: dist/inspire_atom_croatia-<version>.zip

Compiles the Croatian translation first if Qt's lrelease is available, adds
the LICENSE, and leaves out caches and other files QGIS does not need.
"""

import configparser
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = "inspire_atom_croatia"
PLUGIN_DIR = os.path.join(ROOT, PLUGIN)
EXCLUDED_DIRS = {"__pycache__", ".pytest_cache"}
EXCLUDED_SUFFIXES = (".pyc", ".pyo", ".ts", ".gfs")


def version():
    config = configparser.ConfigParser(interpolation=None)
    config.read(os.path.join(PLUGIN_DIR, "metadata.txt"), encoding="utf-8")
    return config["general"]["version"]


def compile_translations():
    lrelease = shutil.which("lrelease") or shutil.which("lrelease-qt5")
    i18n = os.path.join(PLUGIN_DIR, "i18n")
    if not lrelease:
        print("lrelease not found; using the .qm files already in i18n/")
        return
    for name in os.listdir(i18n):
        if name.endswith(".ts"):
            subprocess.run([lrelease, "-silent", os.path.join(i18n, name)], check=True)


def main():
    compile_translations()
    dist = os.path.join(ROOT, "dist")
    os.makedirs(dist, exist_ok=True)
    target = os.path.join(dist, f"{PLUGIN}-{version()}.zip")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for dirpath, dirnames, filenames in os.walk(PLUGIN_DIR):
            dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDED_DIRS)
            for filename in sorted(filenames):
                if filename.endswith(EXCLUDED_SUFFIXES):
                    continue
                full = os.path.join(dirpath, filename)
                archive.write(full, os.path.relpath(full, ROOT))
        archive.write(os.path.join(ROOT, "LICENSE"), f"{PLUGIN}/LICENSE")
    print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
