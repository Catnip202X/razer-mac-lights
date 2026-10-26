#!/usr/bin/env python3
"""dump Razer 接口的 HID report descriptor 与 feature report 长度"""
from __future__ import annotations
import ctypes
RAZER_VID = 0x1532

class HidDeviceInfo(ctypes.Structure): pass
HidDeviceInfo._fields_ = [
    ("path", ctypes.c_char_p), ("vendor_id", ctypes.c_ushort), ("product_id", ctypes.c_ushort),
    ("serial_number", ctypes.c_wchar_p), ("release_number", ctypes.c_ushort),
    ("manufacturer_string", ctypes.c_wchar_p), ("product_string", ctypes.c_wchar_p),
    ("usage_page", ctypes.c_ushort), ("usage", ctypes.c_ushort),
    ("interface_number", ctypes.c_int), ("next", ctypes.POINTER(HidDeviceInfo)), ("bus_type", ctypes.c_int)]

lib = ctypes.CDLL("/opt/homebrew/lib/libhidapi.dylib")
lib.hid_init.restype = ctypes.c_int
lib.hid_enumerate.restype = ctypes.POINTER(HidDeviceInfo)
lib.hid_enumerate.argtypes = [ctypes.c_ushort, ctypes.c_ushort]
lib.hid_free_enumeration.argtypes = [ctypes.POINTER(HidDeviceInfo)]
lib.hid_open_path.restype = ctypes.c_void_p
lib.hid_open_path.argtypes = [ctypes.c_char_p]
lib.hid_get_report_descriptor.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
lib.hid_get_report_descriptor.restype = ctypes.c_int
lib.hid_get_feature_report.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
lib.hid_get_feature_report.restype = ctypes.c_int
lib.hid_close.argtypes = [ctypes.c_void_p]
lib.hid_error.restype = ctypes.c_wchar_p
lib.hid_error.argtypes = [ctypes.c_void_p]

def parse_desc(desc):
    """极简 HID descriptor 解析：输出 Report ID / Feature / Output / Input 长度"""
    reports = {}
    rid = 0; size = 0; rtype = None; i = 0
    while i < len(desc):
        b = desc[i]
        if b == 0xFE:  # long item
            i += 3 + desc[i+1]; continue
        bSize = [0,1,2,4][b & 0x03]
        bType = (b >> 2) & 0x03
        bTag = (b >> 4) & 0x0F
        data = int.from_bytes(desc[i+1:i+1+bSize], "little") if bSize else 0
        if bType == 1 and bTag == 0x8:   # Report ID
            rid = data
        elif bType == 1 and bTag == 0x7:  # Report Size
            size = data
        elif bType == 0 and bTag in (0x8, 0x9, 0xB):  # Input/Output/Feature
            kind = {0x8:"IN", 0x9:"OUT", 0xB:"FEAT"}[bTag]
            cnt = data if data else 1
            bits = size * cnt
            reports.setdefault((kind, rid), set()).add(bits)
        i += 1 + bSize
    return reports

lib.hid_init()
devs = lib.hid_enumerate(0, 0)
out, cur = [], devs
while cur:
    d = cur.contents
    if d.vendor_id == RAZER_VID:
        out.append({"path": d.path, "iface": d.interface_number,
                    "up": d.usage_page, "usage": d.usage})
    cur = d.next
lib.hid_free_enumeration(devs)

for d in out:
    h = lib.hid_open_path(d["path"])
    tag = f"iface={d['iface']} up=0x{d['up']:04X} usage=0x{d['usage']:04X}"
    if not h:
        print(f"\n### {tag}: open failed"); continue
    buf = ctypes.create_string_buffer(4096)
    n = lib.hid_get_report_descriptor(h, buf, 4096)
    print(f"\n### {tag}  descriptor={n} bytes")
    if n > 0:
        desc = buf.raw[:n]
        print("   ", desc.hex())
        for k, v in sorted(parse_desc(desc).items()):
            print(f"    {k[0]:5s} report_id={k[1]:#04x}  bits={sorted(v)} -> bytes={[b//8 for b in sorted(v)]}")
    # feature report 实际长度探测
    for ln in (91, 90, 65, 33, 9):
        fb = ctypes.create_string_buffer(ln)
        fb.raw = bytes([0]) + fb.raw[1:]
        r = lib.hid_get_feature_report(h, fb, ln)
        if r > 0:
            print(f"    get_feature_report(len={ln}) -> {r} bytes: {fb.raw[:min(r,24)].hex()}")
            break
    else:
        print(f"    get_feature_report 全部失败: {lib.hid_error(h)}")
    lib.hid_close(h)
