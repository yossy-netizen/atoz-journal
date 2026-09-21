#!/bin/bash
# Double-click this file in Finder: it opens Terminal and installs CV Rider into your
# user plug-in folders (AU + VST3), removes the download quarantine flag, ad-hoc signs
# the bundles and runs Apple's AU validator. Nothing outside ~/Library is touched.
cd "$(dirname "$0")"
echo "=== CV Rider installer ==="
echo "folder: $(pwd)"
echo
if [[ ! -f install-mac.sh ]]; then
  echo "install-mac.sh が見つかりません。zip を展開したフォルダごと開いてください。"
  read -r -p "Enter キーで閉じます..." _
  exit 1
fi
chmod +x install-mac.sh
if ./install-mac.sh .; then
  echo
  echo "=== インストール完了 ==="
  echo "Logic Pro を（起動中なら再起動して）開き、Audio FX → Audio Units → AtoZ Studio → CV Rider を選んでください。"
else
  echo
  echo "=== エラーが発生しました。上のメッセージを添えてご連絡ください ==="
fi
echo
read -r -p "Enter キーで閉じます..." _
