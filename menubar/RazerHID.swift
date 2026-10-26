import Foundation
import IOKit.hid

/// Razer Huntsman Mini 的 HID 灯控层（纯 IOKit，无需 hidapi / 内核驱动）
///
/// 协议要点（来自 OpenRazer / OpenRGB 的逆向定义，本机实测验证）：
///   - 90 字节私有 report，通过 feature report（reportID 0）收发
///   - IOKit 的 IOHIDDeviceGetReport 返回的 buffer **不含** report id：
///       [0]=status [1]=txn [2..3]=remaining [4]=protocol [5]=data_size
///       [6]=class [7]=cmd  [8...]=arguments [88]=crc
///   - crc = XOR of bytes[2..87]
///   - 灯光命令 transaction id = 0x3F
///   - 矩阵 5 行 × 15 列，写行时 data_size 必须 == 列数*3 + 5
final class RazerKeyboard {

    static let shared = RazerKeyboard()

    struct Reply {
        let status: UInt8
        let dataSize: UInt8
        let commandID: UInt8
        let args: [UInt8]
        var ok: Bool { status == 0x02 }
        var hexStatus: String { String(format: "0x%02X", status) }
    }

    private let vendorID = 0x1532
    private let productID = 0x0257
    private var device: IOHIDDevice?
    private var manager: IOHIDManager?

    // 键盘常量
    static let rows = 5
    static let cols = 15
    private let varstore: UInt8 = 0x01
    private let backlightLED: UInt8 = 0x05
    private let lightingTxn: UInt8 = 0x3F

    private init() {}

    /// 诊断日志：始终写 ~/Library/Logs/RazerLights.log，同时 stderr
    private func dbg(_ msg: @autoclosure () -> String) {
        let line = "[hid] " + msg() + "\n"
        FileHandle.standardError.write(line.data(using: .utf8)!)
        let url = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/RazerLights.log")
        if let fh = try? FileHandle(forWritingTo: url) {
            fh.seekToEndOfFile()
            fh.write(line.data(using: .utf8)!)
            try? fh.close()
        } else {
            try? line.write(to: url, atomically: true, encoding: .utf8)
        }
    }

    // MARK: - 连接

    /// 主动请求「输入监控」权限。GUI 进程访问 HID 必需；
    /// 从终端启动会继承终端的权限，所以命令行测试会「看起来正常」。
    func requestInputMonitoringIfNeeded() {
        let type = IOHIDCheckAccess(kIOHIDRequestTypeListenEvent)
        dbg("IOHIDCheckAccess(ListenEvent)=\(type.rawValue)")
        guard type != kIOHIDAccessTypeGranted else { return }
        dbg("Input Monitoring not granted -> requesting")
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let granted = IOHIDRequestAccess(kIOHIDRequestTypeListenEvent)
            self?.dbg("IOHIDRequestAccess -> \(granted)")
            DispatchQueue.main.async { [weak self] in
                self?.device = nil
                _ = self?.connect()
            }
        }
    }

    var hasInputMonitoring: Bool {
        IOHIDCheckAccess(kIOHIDRequestTypeListenEvent) == kIOHIDAccessTypeGranted
    }

    @discardableResult
    func connect() -> Bool {
        if device != nil { return true }
        let mgr = IOHIDManagerCreate(kCFAllocatorDefault, IOOptionBits(kIOHIDOptionsTypeNone))
        // 只匹配控制接口（usage page 0x0001 / usage 0x0002），不碰键盘接口，
        // 这样不必申请「输入监控」权限
        let match: [String: Any] = [
            kIOHIDVendorIDKey: vendorID,
            kIOHIDProductIDKey: productID,
            kIOHIDPrimaryUsagePageKey: 0x0001,
            kIOHIDPrimaryUsageKey: 0x0002,
        ]
        IOHIDManagerSetDeviceMatching(mgr, match as CFDictionary)
        let openRes = IOHIDManagerOpen(mgr, IOOptionBits(kIOHIDOptionsTypeNone))
        dbg("managerOpen=0x\(String(openRes, radix: 16))")
        guard let set = IOHIDManagerCopyDevices(mgr) as? Set<IOHIDDevice> else {
            dbg("copyDevices returned nil")
            manager = mgr
            return false
        }
        dbg("devices=\(set.count)")
        // 控制接口：usage page 0x0001, usage 0x0001/0x0002
        for dev in set {
            let up = IOHIDDeviceGetProperty(dev, kIOHIDPrimaryUsagePageKey as CFString) as? Int ?? -1
            let us = IOHIDDeviceGetProperty(dev, kIOHIDPrimaryUsageKey as CFString) as? Int ?? -1
            dbg("dev usagePage=0x\(String(up, radix: 16)) usage=0x\(String(us, radix: 16))")
            if up == 0x0001 && (us == 0x0001 || us == 0x0002) {
                let res = IOHIDDeviceOpen(dev, IOOptionBits(kIOHIDOptionsTypeNone))
                dbg("IOHIDDeviceOpen=0x\(String(res, radix: 16))")
                if res == kIOReturnSuccess {
                    device = dev
                    manager = mgr
                    return true
                }
            }
        }
        manager = mgr
        return false
    }

    var isConnected: Bool { device != nil && connect() }

    var productName: String {
        guard let d = device ?? firstDevice() else { return "Razer 键盘" }
        return IOHIDDeviceGetProperty(d, kIOHIDProductKey as CFString) as? String ?? "Razer 键盘"
    }

    private func firstDevice() -> IOHIDDevice? {
        connect()
        return device
    }

    // MARK: - 协议

    private func buildReport(_ cls: UInt8, _ cid: UInt8, _ args: [UInt8], txn: UInt8) -> [UInt8] {
        var p = [UInt8](repeating: 0, count: 90)
        p[0] = 0x00                       // status: new
        p[1] = txn
        p[5] = UInt8(min(args.count, 80))  // data size
        p[6] = cls
        p[7] = cid
        for (i, b) in args.prefix(80).enumerated() { p[8 + i] = b }
        var crc: UInt8 = 0
        for i in 2..<88 { crc ^= p[i] }
        p[88] = crc
        return p
    }

    /// 发一条命令并读回响应；失败会自动重连重试一次
    @discardableResult
    func send(_ cls: UInt8, _ cid: UInt8, _ args: [UInt8] = [], txn: UInt8? = nil) -> Reply? {
        if !connect() { return nil }
        if let r = sendOnce(cls, cid, args, txn ?? lightingTxn) { return r }
        // 设备可能重新枚举过，重连再试
        device = nil
        guard connect() else { return nil }
        return sendOnce(cls, cid, args, txn ?? lightingTxn)
    }

    private func sendOnce(_ cls: UInt8, _ cid: UInt8, _ args: [UInt8], _ txn: UInt8) -> Reply? {
        guard let dev = device else { return nil }
        var report = buildReport(cls, cid, args, txn: txn)
        let setRes = IOHIDDeviceSetReport(dev, kIOHIDReportTypeFeature, 0, &report, report.count)
        guard setRes == kIOReturnSuccess else {
            dbg("setReport failed 0x\(String(setRes, radix: 16))")
            device = nil
            return nil
        }
        // 设备处理需要一点时间；给一点余量
        Thread.sleep(forTimeInterval: 0.012)
        var inBuf = [UInt8](repeating: 0, count: 90)
        var inLen = inBuf.count
        let getRes = IOHIDDeviceGetReport(dev, kIOHIDReportTypeFeature, 0, &inBuf, &inLen)
        guard getRes == kIOReturnSuccess, inLen >= 6 else { return nil }
        let size = inBuf[5]
        let start = 8
        let end = min(start + Int(size), inBuf.count)
        return Reply(status: inBuf[0], dataSize: size, commandID: inBuf[7],
                     args: Array(inBuf[start..<max(start, end)]))
    }

    // MARK: - 查询

    /// 固件版本，形如 "v1.12"
    func firmware() -> String? {
        guard let r = send(0x00, 0x81, [0x00, 0x00], txn: 0xFF), r.args.count >= 2 else { return nil }
        return "v\(r.args[0]).\(r.args[1])"
    }

    /// 设备序列号
    func serial() -> String? {
        guard let r = send(0x00, 0x82, [0x00, 0x00], txn: 0xFF) else { return nil }
        let s = String(bytes: r.args.prefix { $0 != 0 }, encoding: .isoLatin1)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return (s?.isEmpty ?? true) ? nil : s
    }

    /// 当前亮度 0-255
    func brightness() -> Int? {
        guard let r = send(0x0F, 0x84, [varstore, backlightLED]), r.ok, r.args.count >= 3 else {
            return nil
        }
        return Int(r.args[2])
    }

    // MARK: - 整体效果

    @discardableResult
    func setBrightness(_ value: Int) -> Bool {
        send(0x0F, 0x04, [varstore, backlightLED, UInt8(max(0, min(255, value)))])?.ok ?? false
    }

    /// 滑块拖动专用：只下发不读回，单次 <1ms，拖动才跟手
    func setBrightnessFast(_ value: Int) {
        if !connect() { return }
        guard let dev = device else { return }
        var report = buildReport(0x0F, 0x04,
                                 [varstore, backlightLED, UInt8(max(0, min(255, value)))],
                                 txn: lightingTxn)
        _ = IOHIDDeviceSetReport(dev, kIOHIDReportTypeFeature, 0, &report, report.count)
    }

    @discardableResult
    func setStatic(r: UInt8, g: UInt8, b: UInt8) -> Bool {
        send(0x0F, 0x02, [varstore, backlightLED, 0x01, 0, 0, 0x01, r, g, b])?.ok ?? false
    }

    @discardableResult
    func turnOff() -> Bool {
        send(0x0F, 0x02, [varstore, backlightLED, 0x00, 0, 0, 0])?.ok ?? false
    }

    @discardableResult
    func spectrum() -> Bool {
        send(0x0F, 0x02, [varstore, backlightLED, 0x03, 0, 0, 0])?.ok ?? false
    }

    @discardableResult
    func wave(direction: UInt8 = 0) -> Bool {
        send(0x0F, 0x02, [varstore, backlightLED, 0x04, direction, 0x28, 0])?.ok ?? false
    }

    @discardableResult
    func breathingRandom() -> Bool {
        send(0x0F, 0x02, [varstore, backlightLED, 0x02, 0, 0, 0])?.ok ?? false
    }

    @discardableResult
    func breathing(r: UInt8, g: UInt8, b: UInt8) -> Bool {
        send(0x0F, 0x02, [varstore, backlightLED, 0x02, 0x01, 0, 0x01, r, g, b])?.ok ?? false
    }

    // MARK: - 逐键矩阵

    /// 切到 custom 模式。注意 varstore/ledID 必须是 0x00/0x00（实测 0x01/0x05 会被拒）
    @discardableResult
    func enterCustomMode() -> Bool {
        send(0x0F, 0x02, [0x00, 0x00, 0x08, 0, 0, 0, 0, 0, 0, 0, 0, 0])?.ok ?? false
    }

    /// 写一行颜色；data_size 由列数决定，多一列都会被 NOT_SUPPORTED
    @discardableResult
    func setRow(_ row: Int, colors: [(UInt8, UInt8, UInt8)]) -> Bool {
        guard !colors.isEmpty, row >= 0, row < Self.rows else { return false }
        let startCol: UInt8 = 0
        let stopCol = UInt8(colors.count - 1)
        let dataSize = colors.count * 3 + 5
        var args = [UInt8](repeating: 0, count: dataSize)
        args[2] = UInt8(row)
        args[3] = startCol
        args[4] = stopCol
        var i = 5
        for (r, g, b) in colors {
            args[i] = r; args[i + 1] = g; args[i + 2] = b
            i += 3
        }
        return send(0x0F, 0x03, args)?.ok ?? false
    }

    /// 整片矩阵刷色
    @discardableResult
    func fill(r: UInt8, g: UInt8, b: UInt8) -> Bool {
        guard enterCustomMode() else { return false }
        var all = true
        for row in 0..<Self.rows {
            let colors = [(UInt8, UInt8, UInt8)](repeating: (r, g, b), count: Self.cols)
            if !setRow(row, colors: colors) { all = false }
        }
        return all
    }

    /// 横向彩虹
    @discardableResult
    func fillRainbow(hueOffset: Double = 0) -> Bool {
        guard enterCustomMode() else { return false }
        var all = true
        for row in 0..<Self.rows {
            var colors: [(UInt8, UInt8, UInt8)] = []
            for col in 0..<Self.cols {
                var h = (Double(col) / Double(Self.cols) + hueOffset).truncatingRemainder(dividingBy: 1)
                if h < 0 { h += 1 }
                colors.append(Self.hsv(h, 1, 1))
            }
            if !setRow(row, colors: colors) { all = false }
        }
        return all
    }

    // MARK: - 工具

    static func hsv(_ h: Double, _ s: Double, _ v: Double) -> (UInt8, UInt8, UInt8) {
        let i = Int(h * 6) % 6
        let f = h * 6 - Double(Int(h * 6))
        let p = v * (1 - s)
        let q = v * (1 - f * s)
        let t = v * (1 - (1 - f) * s)
        let (r, g, b): (Double, Double, Double)
        switch i {
        case 0: (r, g, b) = (v, t, p)
        case 1: (r, g, b) = (q, v, p)
        case 2: (r, g, b) = (p, v, t)
        case 3: (r, g, b) = (p, q, v)
        case 4: (r, g, b) = (t, p, v)
        default: (r, g, b) = (v, p, q)
        }
        return (UInt8(r * 255), UInt8(g * 255), UInt8(b * 255))
    }
}
