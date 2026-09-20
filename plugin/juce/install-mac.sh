#!/bin/bash
# Installs a CI-built "CV Rider" bundle set (downloaded from the GitHub Actions artefact) into
# the user's plug-in folders, strips the download quarantine flag and ad-hoc signs the bundles.
#
#   unzip cvrider-macos.zip -d cvrider-macos
#   ./install-mac.sh cvrider-macos
set -euo pipefail
SRC="${1:-.}"

AU="$SRC/CV Rider.component"
VST3="$SRC/CV Rider.vst3"
APP="$SRC/CV Rider.app"

for b in "$AU" "$VST3" "$APP"; do
  [[ -e "$b" ]] || continue
  xattr -dr com.apple.quarantine "$b" 2>/dev/null || true
  codesign --force --deep --sign - "$b"
done

mkdir -p ~/Library/Audio/Plug-Ins/Components ~/Library/Audio/Plug-Ins/VST3
if [[ -e "$AU" ]]; then
  rm -rf ~/Library/Audio/Plug-Ins/Components/"CV Rider.component"
  cp -R "$AU" ~/Library/Audio/Plug-Ins/Components/
  echo "installed ~/Library/Audio/Plug-Ins/Components/CV Rider.component"
fi
if [[ -e "$VST3" ]]; then
  rm -rf ~/Library/Audio/Plug-Ins/VST3/"CV Rider.vst3"
  cp -R "$VST3" ~/Library/Audio/Plug-Ins/VST3/
  echo "installed ~/Library/Audio/Plug-Ins/VST3/CV Rider.vst3"
fi
if [[ -e "$APP" ]]; then
  rm -rf /Applications/"CV Rider.app"
  cp -R "$APP" /Applications/ 2>/dev/null && echo "installed /Applications/CV Rider.app" || echo "(skipped /Applications: no permission)"
fi

killall -9 AudioComponentRegistrar 2>/dev/null || true
if [[ -e "$AU" ]]; then
  echo "--- auval ---"
  auval -v aufx Cvrd AtoZ | tail -n 5
fi
