import Cocoa

// MARK: - 状态栏 App

final class AppDelegate: NSObject, NSApplicationDelegate, NSMenuDelegate {

    private var statusItem: NSStatusItem!
    private let kb = RazerKeyboard.shared

    private var rainbowTimer: Timer?
    private var pulseTimer: Timer?

    private var hue: Double = 0
    private var currentBrightness: Int = 100
    private var lastStatic: (UInt8, UInt8, UInt8) = (0x44, 0xD6, 0x2C)
    private var cachedFirmware: String = ""

    // 菜单项引用（菜单只构建一次，打开时只更新状态）
    private var infoItem: NSMenuItem!
    private var loginItem: NSMenuItem!
    private var pulseItem: NSMenuItem!
    private var rainbowFlowItem: NSMenuItem!
    private var brightnessSlider: NSSlider?
    private var brightnessValueLabel: NSTextField?
    private var draggingBrightness = false

    private let presets: [(String, (UInt8, UInt8, UInt8))] = [
        ("雷蛇绿", (0x44, 0xD6, 0x2C)),
        ("血红",   (0xFF, 0x00, 0x33)),
        ("橙",     (0xFF, 0x77, 0x00)),
        ("琥珀",   (0xFF, 0xB0, 0x00)),
        ("青",     (0x00, 0xFF, 0xCC)),
        ("冰蓝",   (0x00, 0xAA, 0xFF)),
        ("紫",     (0x99, 0x33, 0xFF)),
        ("品红",   (0xFF, 0x00, 0xAA)),
        ("纯白",   (0xFF, 0xFF, 0xFF)),
        ("暖白",   (0xFF, 0xE4, 0xB5)),
    ]

    // MARK: - 生命周期

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            button.image = NSImage(systemSymbolName: "keyboard.fill",
                                   accessibilityDescription: "Razer 灯控")
            button.image?.isTemplate = true
            button.toolTip = "Razer 灯控"
        }
        _ = kb.connect()
        cachedFirmware = kb.firmware() ?? ""
        kb.requestInputMonitoringIfNeeded()
        buildMenu()          // 只建一次，绝不重建
        NSLog("RazerLights started, device=\(kb.isConnected), fw=\(cachedFirmware)")
    }

    // MARK: - 菜单构建（仅一次）

    private func buildMenu() {
        let menu = NSMenu()
        menu.delegate = self

        infoItem = NSMenuItem(title: infoTitle(), action: nil, keyEquivalent: "")
        infoItem.isEnabled = false
        menu.addItem(infoItem)
        menu.addItem(.separator())

        // 亮度滑块
        let container = NSView(frame: NSRect(x: 0, y: 0, width: 260, height: 34))

        let title = NSTextField(labelWithString: "☀︎")
        title.frame = NSRect(x: 14, y: 8, width: 18, height: 18)
        title.font = .systemFont(ofSize: 13)
        title.textColor = .secondaryLabelColor
        container.addSubview(title)

        let slider = NSSlider(value: Double(currentBrightness),
                              minValue: 0, maxValue: 100,
                              target: self,
                              action: #selector(brightnessSliderChanged(_:)))
        slider.frame = NSRect(x: 36, y: 7, width: 172, height: 20)
        slider.isContinuous = true
        slider.controlSize = .small
        container.addSubview(slider)
        brightnessSlider = slider

        let valueLabel = NSTextField(labelWithString: "\(currentBrightness)%")
        valueLabel.frame = NSRect(x: 212, y: 8, width: 42, height: 17)
        valueLabel.font = .monospacedDigitSystemFont(ofSize: 11, weight: .regular)
        valueLabel.textColor = .secondaryLabelColor
        valueLabel.alignment = .right
        container.addSubview(valueLabel)
        brightnessValueLabel = valueLabel

        let brightItem = NSMenuItem()
        brightItem.view = container
        menu.addItem(brightItem)

        // 纯色
        let colorItem = NSMenuItem(title: "纯色", action: nil, keyEquivalent: "")
        let colorMenu = NSMenu()
        for (i, preset) in presets.enumerated() {
            let it = NSMenuItem(title: preset.0, action: #selector(applyPreset(_:)),
                                keyEquivalent: "")
            it.tag = i
            it.target = self
            colorMenu.addItem(it)
        }
        colorMenu.addItem(.separator())
        let picker = NSMenuItem(title: "取色器…", action: #selector(openColorPanel),
                                keyEquivalent: "")
        picker.target = self
        colorMenu.addItem(picker)
        colorItem.submenu = colorMenu
        menu.addItem(colorItem)

        // 效果
        let effectItem = NSMenuItem(title: "效果", action: nil, keyEquivalent: "")
        let effectMenu = NSMenu()
        let effects: [(String, Selector)] = [
            ("光谱循环", #selector(effectSpectrum)),
            ("波浪 →", #selector(effectWaveRight)),
            ("波浪 ←", #selector(effectWaveLeft)),
            ("随机呼吸", #selector(effectBreathingRandom)),
            ("关灯", #selector(effectOff)),
        ]
        for (title, sel) in effects {
            let it = NSMenuItem(title: title, action: sel, keyEquivalent: "")
            it.target = self
            effectMenu.addItem(it)
        }
        effectItem.submenu = effectMenu
        menu.addItem(effectItem)

        // 逐键
        let matrixItem = NSMenuItem(title: "逐键", action: nil, keyEquivalent: "")
        let matrixMenu = NSMenu()

        let m1 = NSMenuItem(title: "静态彩虹", action: #selector(matrixRainbow), keyEquivalent: "")
        m1.target = self
        matrixMenu.addItem(m1)

        rainbowFlowItem = NSMenuItem(title: "彩虹流动", action: #selector(toggleRainbowFlow),
                                     keyEquivalent: "")
        rainbowFlowItem.target = self
        matrixMenu.addItem(rainbowFlowItem)

        let m3 = NSMenuItem(title: "整片填当前色", action: #selector(matrixFillCurrent),
                            keyEquivalent: "")
        m3.target = self
        matrixMenu.addItem(m3)

        matrixItem.submenu = matrixMenu
        menu.addItem(matrixItem)

        menu.addItem(.separator())

        pulseItem = NSMenuItem(title: "🎵 音乐律动（麦克风）", action: #selector(togglePulse),
                               keyEquivalent: "")
        pulseItem.target = self
        menu.addItem(pulseItem)

        loginItem = NSMenuItem(title: "开机自动应用", action: #selector(toggleLoginItem),
                               keyEquivalent: "")
        loginItem.target = self
        menu.addItem(loginItem)

        let refresh = NSMenuItem(title: "重新连接设备", action: #selector(reconnect),
                                 keyEquivalent: "")
        refresh.target = self
        menu.addItem(refresh)

        let perm = NSMenuItem(title: "打开输入监控设置…", action: #selector(openInputMonitoring),
                              keyEquivalent: "")
        perm.target = self
        menu.addItem(perm)

        menu.addItem(.separator())
        let quit = NSMenuItem(title: "退出", action: #selector(NSApplication.terminate(_:)),
                              keyEquivalent: "q")
        menu.addItem(quit)

        statusItem.menu = menu      // 唯一一次赋值
    }

    // 菜单打开前刷新状态（不增删菜单项）
    func menuNeedsUpdate(_ menu: NSMenu) {
        infoItem.title = infoTitle()
        if !draggingBrightness, let b = kb.brightness() {
            let pct = Int(round(Double(b) * 100.0 / 255.0))
            currentBrightness = pct
            brightnessSlider?.doubleValue = Double(pct)
            brightnessValueLabel?.stringValue = "\(pct)%"
        }
        loginItem.state = isLoginItemEnabled() ? .on : .off
        pulseItem.state = (pulseTimer != nil) ? .on : .off
        rainbowFlowItem.state = (rainbowTimer != nil) ? .on : .off
    }

    private func infoTitle() -> String {
        if !kb.hasInputMonitoring { return "⚠️ 需要「输入监控」权限" }
        guard kb.isConnected else { return "⚠️ 未找到 Razer 键盘" }
        let fw = cachedFirmware.isEmpty ? (kb.firmware() ?? "?") : cachedFirmware
        if cachedFirmware.isEmpty { cachedFirmware = fw }
        return "\(kb.productName) · \(fw)"
    }

    // MARK: - 动作

    @objc private func brightnessSliderChanged(_ sender: NSSlider) {
        let pct = Int(sender.doubleValue.rounded())
        currentBrightness = pct
        brightnessValueLabel?.stringValue = "\(pct)%"
        UserDefaults.standard.set(pct, forKey: "lastBrightness")
        // 只写不读，拖动才跟手
        kb.setBrightnessFast(Int(round(Double(pct) * 255.0 / 100.0)))
    }

    @objc private func applyPreset(_ sender: NSMenuItem) {
        guard sender.tag < presets.count else { return }
        let (r, g, b) = presets[sender.tag].1
        lastStatic = (r, g, b)
        remember(r, g, b)
        stopPulse()
        _ = kb.setStatic(r: r, g: g, b: b)
    }

    private func remember(_ r: UInt8, _ g: UInt8, _ b: UInt8) {
        let d = UserDefaults.standard
        d.set(true, forKey: "hasLastColor")
        d.set(Int(r), forKey: "lastR")
        d.set(Int(g), forKey: "lastG")
        d.set(Int(b), forKey: "lastB")
    }

    @objc private func openColorPanel() {
        let panel = NSColorPanel.shared
        panel.setTarget(self)
        panel.setAction(#selector(colorPicked(_:)))
        panel.showsAlpha = false
        NSApp.activate(ignoringOtherApps: true)
        panel.orderFront(nil)
    }

    @objc private func colorPicked(_ sender: NSColorPanel) {
        guard let c = sender.color.usingColorSpace(.deviceRGB) else { return }
        let r = UInt8(max(0, min(255, c.redComponent * 255)))
        let g = UInt8(max(0, min(255, c.greenComponent * 255)))
        let b = UInt8(max(0, min(255, c.blueComponent * 255)))
        lastStatic = (r, g, b)
        remember(r, g, b)
        _ = kb.setStatic(r: r, g: g, b: b)
    }

    @objc private func effectSpectrum() { stopAnimations(); _ = kb.spectrum() }
    @objc private func effectWaveRight() { stopAnimations(); _ = kb.wave(direction: 0) }
    @objc private func effectWaveLeft() { stopAnimations(); _ = kb.wave(direction: 1) }
    @objc private func effectBreathingRandom() { stopAnimations(); _ = kb.breathingRandom() }
    @objc private func effectOff() { stopAnimations(); _ = kb.turnOff() }

    @objc private func matrixRainbow() {
        stopAnimations()
        _ = kb.fillRainbow()
    }

    @objc private func matrixFillCurrent() {
        stopAnimations()
        let (r, g, b) = lastStatic
        _ = kb.fill(r: r, g: g, b: b)
    }

    @objc private func toggleRainbowFlow() {
        if rainbowTimer != nil { stopRainbowFlow(); return }
        stopPulse()
        _ = kb.enterCustomMode()
        hue = 0
        rainbowTimer = Timer.scheduledTimer(withTimeInterval: 0.09, repeats: true) { [weak self] _ in
            guard let self else { return }
            self.hue = (self.hue + 0.025).truncatingRemainder(dividingBy: 1)
            _ = self.kb.fillRainbow(hueOffset: self.hue)
        }
    }

    private func stopRainbowFlow() {
        rainbowTimer?.invalidate()
        rainbowTimer = nil
    }

    @objc private func openInputMonitoring() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent") {
            NSWorkspace.shared.open(url)
        }
    }

    @objc private func reconnect() {
        _ = kb.connect()
        cachedFirmware = kb.firmware() ?? ""
        kb.requestInputMonitoringIfNeeded()
        NSLog("reconnect -> connected=\(kb.isConnected) fw=\(cachedFirmware)")
    }

    // MARK: - 音乐律动

    @objc private func togglePulse() {
        if pulseTimer != nil { stopPulse(); return }
        stopRainbowFlow()
        AudioPulse.requestPermission { [weak self] granted in
            guard let self else { return }
            guard granted else {
                let alert = NSAlert()
                alert.messageText = "需要麦克风权限"
                alert.informativeText = "系统设置 → 隐私与安全性 → 麦克风，勾选 RazerLights 后重试。"
                alert.runModal()
                return
            }
            guard AudioPulse.shared.start() else {
                NSLog("AudioPulse.start() failed")
                return
            }
            let base = self.lastStatic
            self.pulseTimer = Timer.scheduledTimer(withTimeInterval: 0.05, repeats: true) { [weak self] _ in
                guard let self else { return }
                let lvl = AudioPulse.shared.level
                let k = 0.10 + lvl * 1.35
                let r = UInt8(min(255, Double(base.0) * k))
                let g = UInt8(min(255, Double(base.1) * k))
                let b = UInt8(min(255, Double(base.2) * k))
                _ = self.kb.setStatic(r: r, g: g, b: b)
            }
        }
    }

    private func stopPulse() {
        pulseTimer?.invalidate()
        pulseTimer = nil
        AudioPulse.shared.stop()
    }

    private func stopAnimations() {
        stopRainbowFlow()
        stopPulse()
    }

    // MARK: - 开机自启

    private func launchAgentPath() -> URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/LaunchAgents/com.local.razerlights.plist")
    }

    private func isLoginItemEnabled() -> Bool {
        FileManager.default.fileExists(atPath: launchAgentPath().path)
    }

    @objc private func toggleLoginItem() {
        let path = launchAgentPath()
        if FileManager.default.fileExists(atPath: path.path) {
            try? FileManager.default.removeItem(at: path)
            return
        }
        let exec = Bundle.main.executablePath ?? "/usr/bin/true"
        let plist: [String: Any] = [
            "Label": "com.local.razerlights",
            "ProgramArguments": [exec, "--apply-once"],
            "RunAtLoad": true,
            "KeepAlive": false,
        ]
        try? FileManager.default.createDirectory(
            at: path.deletingLastPathComponent(), withIntermediateDirectories: true)
        if let data = try? PropertyListSerialization.data(fromPropertyList: plist,
                                                          format: .xml, options: 0) {
            try? data.write(to: path)
        }
    }
}

// MARK: - 入口

// 诊断模式：打印 HID 连接细节
if CommandLine.arguments.contains("--selftest") {
    let kb = RazerKeyboard.shared
    print("connect:", kb.connect())
    print("product:", kb.productName)
    print("firmware:", kb.firmware() ?? "nil")
    print("serial:", kb.serial() ?? "nil")
    print("brightness:", kb.brightness().map(String.init) ?? "nil")
    exit(0)
}

// headless 模式：应用一次上次的配色后退出（给 LaunchAgent 用）
if CommandLine.arguments.contains("--apply-once") {
    let kb = RazerKeyboard.shared
    if kb.connect() {
        let defaults = UserDefaults.standard
        if defaults.bool(forKey: "hasLastColor") {
            let r = UInt8(clamping: defaults.integer(forKey: "lastR"))
            let g = UInt8(clamping: defaults.integer(forKey: "lastG"))
            let b = UInt8(clamping: defaults.integer(forKey: "lastB"))
            _ = kb.setStatic(r: r, g: g, b: b)
        }
        let pct = defaults.object(forKey: "lastBrightness") as? Int ?? 100
        _ = kb.setBrightness(Int(round(Double(pct) * 255.0 / 100.0)))
    }
    exit(0)
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
