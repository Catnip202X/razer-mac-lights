#!/bin/bash
# 构建 RazerLights.app（菜单栏灯控）
set -e
cd "$(dirname "$0")"
APP="RazerLights.app"

swiftc -O -swift-version 5 -o RazerLights \
    main.swift RazerHID.swift AudioPulse.swift \
    -framework Cocoa -framework IOKit -framework AVFoundation

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp RazerLights "$APP/Contents/MacOS/RazerLights"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key><string>com.local.razerlights</string>
    <key>CFBundleName</key><string>RazerLights</string>
    <key>CFBundleDisplayName</key><string>Razer 灯控</string>
    <key>CFBundleExecutable</key><string>RazerLights</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>LSMinimumSystemVersion</key><string>13.0</string>
    <key>LSUIElement</key><true/>
    <key>NSMicrophoneUsageDescription</key><string>用麦克风音量驱动键盘灯效律动</string>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

# 签名：优先用 CODESIGN_IDENTITY 环境变量指定的证书，否则自动挑本机第一个
# Apple Development 证书，都没有就退化成 adhoc（GUI 启动时可能需要手动授予输入监控）
if [ -z "${CODESIGN_IDENTITY:-}" ]; then
    CODESIGN_IDENTITY=$(security find-identity -v -p codesigning 2>/dev/null \
        | awk -F'"' '/Apple Development/ {print $2; exit}')
fi
if [ -n "${CODESIGN_IDENTITY:-}" ]; then
    echo "signing with: $CODESIGN_IDENTITY"
    codesign --force --deep --sign "$CODESIGN_IDENTITY" "$APP"
else
    echo "no signing identity found, falling back to adhoc"
    codesign --force --deep --sign - "$APP"
fi
echo "built: $(pwd)/$APP"
