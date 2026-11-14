#!/bin/bash
# Build the connector kits that go on the GitHub release page:
#   dist/DSC_Bridge_Connector_Windows_<version>.zip  one-click: embeddable Python 3.11 + the signing libraries inside
#   dist/DSC_Bridge_Connector_Mac_<version>.zip      scripts only (install.command makes a venv with pip)
#
# The Windows kit needs a python/ and a lib/ folder:
#   KIT_PY_DIR  = an unpacked python.org "Windows embeddable package (64-bit)" 3.11.x, with python311._pth pointing
#                 to ..\lib (one line: python311.zip, one line: ., one line: ..\lib, one line: import site)
#   KIT_LIB_DIR = the wheels of requirements-kit.txt unpacked:
#                 pip download -r requirements-kit.txt -d wheels --platform win_amd64 --python-version 311 --only-binary=:all:
#                 for w in wheels/*.whl; do unzip -q -o "$w" -d lib; done
# Point KIT_PY_DIR / KIT_LIB_DIR at them (default: ./kit_parts/python and ./kit_parts/lib).
# `build_kits.sh --download` fetches both parts itself (python.org embeddable 3.11.9 + wheels from PyPI), as the
# release workflow does.
set -e
cd "$(dirname "$0")"
VERSION=$(sed -n 's/^VERSION = "\(.*\)"/\1/p' connector.py)
PY_DIR="${KIT_PY_DIR:-kit_parts/python}"
LIB_DIR="${KIT_LIB_DIR:-kit_parts/lib}"
PY_VERSION="${KIT_PYTHON_VERSION:-3.11.9}"

if [ "$1" = "--download" ]; then
  rm -rf kit_parts && mkdir -p kit_parts/python kit_parts/lib kit_parts/wheels
  curl -fsSL -o kit_parts/python-embed.zip "https://www.python.org/ftp/python/${PY_VERSION}/python-${PY_VERSION}-embed-amd64.zip"
  unzip -q kit_parts/python-embed.zip -d kit_parts/python
  test -f kit_parts/python/pythonw.exe
  python3 -m pip download -q -r requirements-kit.txt -d kit_parts/wheels --platform win_amd64 --python-version 311 --only-binary=:all:
  for w in kit_parts/wheels/*.whl; do unzip -q -o "$w" -d kit_parts/lib; done
  test -d kit_parts/lib/pyhanko
  PY_DIR=kit_parts/python
  LIB_DIR=kit_parts/lib
fi
rm -rf dist build && mkdir -p dist build

# Mac
M="build/DSC Bridge Connector - Mac"
mkdir -p "$M"
cp connector.py requirements.txt "$M/"
cp mac/*.command "$M/"
cp README.md "$M/README.md"
( cd build && zip -q -r "../dist/DSC_Bridge_Connector_Mac_${VERSION}.zip" "DSC Bridge Connector - Mac" -x '*.DS_Store' )
echo "built dist/DSC_Bridge_Connector_Mac_${VERSION}.zip"

# Windows one-click
if [ -f "$PY_DIR/pythonw.exe" ] && [ -d "$LIB_DIR/pyhanko" ]; then
  W="build/DSC Bridge Connector - Windows"
  mkdir -p "$W"
  cp connector.py "$W/"
  cp windows/install.bat windows/start.vbs windows/stop.bat windows/uninstall.bat "$W/"
  cp README.md "$W/README.md"
  cp -R "$PY_DIR" "$W/python"
  cp -R "$LIB_DIR" "$W/lib"
  # the embeddable Python's search path: its own zip, this folder, and the libraries in ..\lib (no site-packages)
  printf 'python311.zip\r\n.\r\n..\\lib\r\n\r\n# DSC Bridge Connector: the signing libraries are in ..\\lib (no Python install needed on the PC)\r\n#import site\r\n' > "$W/python/python311._pth"
  find "$W" -name '__pycache__' -type d -prune -exec rm -rf {} +
  ( cd build && zip -q -r "../dist/DSC_Bridge_Connector_Windows_${VERSION}.zip" "DSC Bridge Connector - Windows" -x '*.DS_Store' )
  echo "built dist/DSC_Bridge_Connector_Windows_${VERSION}.zip"
else
  echo "Windows kit skipped: put the embeddable Python in $PY_DIR and the unpacked wheels in $LIB_DIR (see the top of this file)."
fi
rm -rf build
