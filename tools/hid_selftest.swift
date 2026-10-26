import Foundation
import IOKit.hid

let VID = 0x1532, PID = 0x0257

func buildReport(cls: UInt8, cid: UInt8, args: [UInt8], txn: UInt8 = 0x3F) -> [UInt8] {
    var p = [UInt8](repeating: 0, count: 90)
    p[0] = 0x00; p[1] = txn; p[5] = UInt8(args.count); p[6] = cls; p[7] = cid
    for (i, b) in args.enumerated() { p[8 + i] = b }
    var crc: UInt8 = 0
    for i in 2..<88 { crc ^= p[i] }
    p[88] = crc
    return p
}

let mgr = IOHIDManagerCreate(kCFAllocatorDefault, IOOptionBits(kIOHIDOptionsTypeNone))
let match: [String: Any] = [kIOHIDVendorIDKey: VID, kIOHIDProductIDKey: PID]
IOHIDManagerSetDeviceMatching(mgr, match as CFDictionary)
let r = IOHIDManagerOpen(mgr, IOOptionBits(kIOHIDOptionsTypeNone))
print("open manager: 0x\(String(r, radix: 16))")
guard let set = IOHIDManagerCopyDevices(mgr) as? Set<IOHIDDevice> else {
    print("no devices"); exit(1)
}
print("devices: \(set.count)")

for dev in set {
    let up = IOHIDDeviceGetProperty(dev, kIOHIDPrimaryUsagePageKey as CFString) as? Int ?? -1
    let us = IOHIDDeviceGetProperty(dev, kIOHIDPrimaryUsageKey as CFString) as? Int ?? -1
    guard up == 1, us == 1 || us == 2 else { continue }
    print("picked usagePage=\(up) usage=\(us)")
    // firmware query
    var report = buildReport(cls: 0x00, cid: 0x81, args: [0x00, 0x00], txn: 0xFF)
    let setRes = IOHIDDeviceSetReport(dev, kIOHIDReportTypeFeature, 0, &report, report.count)
    print("setReport: \(setRes)")
    Thread.sleep(forTimeInterval: 0.1)
    var inBuf = [UInt8](repeating: 0, count: 90)
    var inLen = inBuf.count
    let getRes = IOHIDDeviceGetReport(dev, kIOHIDReportTypeFeature, 0, &inBuf, &inLen)
    print("getReport: \(getRes) len=\(inLen) raw=\(inBuf.prefix(16).map { String(format: "%02x", $0) }.joined())")
    if inLen >= 2 { print("status=0x\(String(inBuf[0], radix: 16)) firmware=v\(inBuf[1]).\(inBuf[2])") }
}
