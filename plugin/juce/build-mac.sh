#!/bin/bash
# Builds CV Rider on macOS (AU + VST3 + Standalone, universal arm64/x86_64) and installs
# it into the user's plug-in folders. Requires Xcode Command Line Tools and CMake
# (brew install cmake). JUCE 8.0.4 is fetched automatically on the first configure.
#
#   ./build-mac.sh            # build + install + auval
#   ./build-mac.sh --no-install
set -euo pipefail
cd "$(dirname "$0")"

INSTALL=1
[[ "${1:-}" == "--no-install" ]] && INSTALL=0

cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j"$(sysctl -n hw.ncpu)"

ART="build/CVRider_artefacts/Release"
AU="$ART/AU/CV Rider.component"
VST3="$ART/VST3/CV Rider.vst3"
APP="$ART/Standalone/CV Rider.app"

# ad-hoc signature so the bundles load on Apple Silicon (no Developer ID needed for local use)
for b in "$AU" "$VST3" "$APP"; do
  [[ -e "$b" ]] && codesign --force --deep --sign - "$b"
done

if [[ $INSTALL -eq 1 ]]; then
  mkdir -p ~/Library/Audio/Plug-Ins/Components ~/Library/Audio/Plug-Ins/VST3
  rm -rf ~/Library/Audio/Plug-Ins/Components/"CV Rider.component" ~/Library/Audio/Plug-Ins/VST3/"CV Rider.vst3"
  cp -R "$AU"   ~/Library/Audio/Plug-Ins/Components/
  cp -R "$VST3" ~/Library/Audio/Plug-Ins/VST3/
  echo "installed:"
  echo "  ~/Library/Audio/Plug-Ins/Components/CV Rider.component"
  echo "  ~/Library/Audio/Plug-Ins/VST3/CV Rider.vst3"
  # make Logic / GarageBand re-scan the AU, then validate it
  killall -9 AudioComponentRegistrar 2>/dev/null || true
  echo "--- auval ---"
  auval -v aufx Cvrd AtoZ | tail -n 5
fi
