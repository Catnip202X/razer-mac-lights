#!/usr/bin/env python3
"""Razer HID 接口探测器 (macOS / hidapi via ctypes)
列出 Razer 设备的全部 HID 接口，并对控制接口尝试读取固件版本。
"""
from __future__ import annotations
import ctypes, ctypes.util, sys

RAZER_VID = 0x1532

class HidDeviceInfo(ctypes.Structure):
    pass

HidDeviceInfo._fields_ = [
    ("path", ctypes.c_char_p),
    ("vendor_id", ctypes.c_ushort),
    ("product_id", ctypes.c_ushort),
    ("serial_number", ctypes.c_wchar_p),
    ("release_number", ctypes.c_ushort),
    ("manufacturer_string", ctypes.c_wchar_p),
    ("product_string", ctypes.c_wchar_p),
    ("usage_page", ctypes.c_ushort),
    ("usage", ctypes.c_ushort),
    ("interface_number", ctypes.c_int),
    ("next", ctypes.POINTER(HidDeviceInfo)),
    ("bus_type", ctypes.c_int),
]

lib = ctypes.CDLL("/opt/homebrew/lib/libhidapi.dylib")
lib.hid_init.restype = ctypes.c_int
lib.hid_enumerate.restype = ctypes.POINTER(HidDeviceInfo)
lib.hid_enumerate.argtypes = [ctypes.c_ushort, ctypes.c_ushort]
lib.hid_free_enumeration.argtypes = [ctypes.POINTER(HidDeviceInfo)]
lib.hid_open_path.restype = ctypes.c_void_p
lib.hid_open_path.argtypes = [ctypes.c_char_p]
lib.hid_write.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
lib.hid_write.restype = ctypes.c_int
lib.hid_read_timeout.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int]
lib.hid_read_timeout.restype = ctypes.c_int
lib.hid_close.argtypes = [ctypes.c_void_p]
lib.hid_error.restype = ctypes.c_wchar_p
lib.hid_error.argtypes = [ctypes.c_void_p]


def crc(buf: bytes) -> int:
    c = 0
    for b in buf[2:88]:
        c ^= b
    return c


def packet(cmd_class: int, cmd_id: int, data: bytes, txn: int = 0xFF) -> bytes:
    p = bytearray(90)
    p[0] = 0x00            # report id
    p[1] = 0x00            # status: new command
    p[2] = 0x00            # reserved
    p[3] = 0x00            # reserved
    p[4] = txn             # transaction id
    remaining = 0
    p[5] = (remaining >> 8) & 0xFF
    p[6] = remaining & 0xFF
    p[7] = 0x00            # protocol type
    p[8] = len(data)       # data size
    p[9] = cmd_class
    p[10] = cmd_id
    p[11:11 + len(data)] = data
    p[88] = crc(p)
    return bytes(p)


def main():
    lib.hid_init()
    devs = lib.hid_enumerate(0, 0)
    if not devs:
        print("hid_enumerate 返回空")
        return
    rows, cur = [], devs
    while cur:
        d = cur.contents
        rows.append(d)
        cur = d.next
    print(f"HID 设备总数: {len(rows)}\n")
    razer = [d for d in rows if d.vendor_id == RAZER_VID]
    print(f"Razer 接口数: {len(razer)}")
    print(f"{'PID':>6} {'iface':>5} {'usage_page':>10} {'usage':>6}  {'product':<24} path")
    for d in razer:
        print(f"0x{d.product_id:04X} {d.interface_number:>5} 0x{d.usage_page:04X}{'':>6} 0x{d.usage:04X} "
              f" {str(d.product_string or ''):<24} {d.path.decode(errors='replace') if d.path else ''}")

    # 尝试每个接口：读固件版本
    print("\n=== 尝试读取固件版本 (GET_FIRMWARE_VERSION 0x00/0x81) ===")
    for d in razer:
        if d.usage_page < 0xFF00 and d.usage_page != 0x0001:
            continue
        h = lib.hid_open_path(d.path)
        if not h:
            print(f"  接口 iface={d.interface_number} usage_page=0x{d.usage_page:04X}: 打开失败 ({lib.hid_error(None)})")
            continue
        buf = ctypes.create_string_buffer(91)

        ok_w = lib.hid_write(h, packet(0x00, 0x81, b"\x00\x00"), 90)
        n = lib.hid_read_timeout(h, buf, 90, 400)
        status = buf.raw[1] if n > 0 else None
        fw = ""
        if n >= 20:
            raw = buf.raw[11:]
            fw = "".join(chr(b) if 32 <= b < 127 else "" for b in raw[:20]).strip("\x00").strip()
        print(f"  接口 iface={d.interface_number} usage_page=0x{d.usage_page:04X}: "
              f"write={ok_w} read={n} status={status} firmware='{fw}'")
        lib.hid_close(h)
    lib.hid_free_enumeration(devs)


if __name__ == "__main__":
    main()
