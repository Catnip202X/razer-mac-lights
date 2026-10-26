#!/usr/bin/env python3
"""Razer 90-byte report 协议测试（macOS / hidapi）
结构（无 report-id 前缀）:
  [0] status  [1] transaction_id  [2..3] remaining_packets  [4] protocol_type
  [5] data_size  [6] command_class  [7] command_id  [8..87] arguments  [88] crc  [89] reserved
crc = XOR of bytes[2..87]
"""
from __future__ import annotations
import ctypes, sys

RAZER_VID = 0x1532
PRODUCT = "Razer Huntsman Mini"

class HidDeviceInfo(ctypes.Structure):
    pass

HidDeviceInfo._fields_ = [
    ("path", ctypes.c_char_p), ("vendor_id", ctypes.c_ushort), ("product_id", ctypes.c_ushort),
    ("serial_number", ctypes.c_wchar_p), ("release_number", ctypes.c_ushort),
    ("manufacturer_string", ctypes.c_wchar_p), ("product_string", ctypes.c_wchar_p),
    ("usage_page", ctypes.c_ushort), ("usage", ctypes.c_ushort),
    ("interface_number", ctypes.c_int), ("next", ctypes.POINTER(HidDeviceInfo)),
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
lib.hid_send_feature_report.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
lib.hid_send_feature_report.restype = ctypes.c_int
lib.hid_read_timeout.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int]
lib.hid_read_timeout.restype = ctypes.c_int
lib.hid_get_feature_report.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
lib.hid_get_feature_report.restype = ctypes.c_int
lib.hid_close.argtypes = [ctypes.c_void_p]
lib.hid_error.restype = ctypes.c_wchar_p
lib.hid_error.argtypes = [ctypes.c_void_p]


def build(cls: int, cid: int, args: bytes = b"", txn: int = 0x1F) -> bytes:
    p = bytearray(90)
    p[0] = 0x00      # status: new
    p[1] = txn       # transaction id
    p[2] = 0x00      # remaining packets msb
    p[3] = 0x00      # remaining packets lsb
    p[4] = 0x00      # protocol type
    p[5] = len(args)  # data size
    p[6] = cls
    p[7] = cid
    p[8:8 + len(args)] = args
    crc = 0
    for i in range(2, 88):
        crc ^= p[i]
    p[88] = crc
    p[89] = 0x00
    return bytes(p)


def enumerate_razer():
    """返回纯 Python dict 列表（避免 hid_free_enumeration 后悬空指针）"""
    lib.hid_init()
    devs = lib.hid_enumerate(0, 0)
    out, cur = [], devs
    while cur:
        d = cur.contents
        if d.vendor_id == RAZER_VID:
            out.append({
                "path": d.path,
                "product_id": d.product_id,
                "interface_number": d.interface_number,
                "usage_page": d.usage_page,
                "usage": d.usage,
                "product_string": d.product_string,
            })
        cur = d.next
    lib.hid_free_enumeration(devs)
    return out


def describe_reply(raw: bytes, n: int) -> str:
    if n <= 0:
        return "no reply"
    status = raw[0]
    size = raw[5]
    body = bytes(raw[8:8 + min(size, 24)])
    names = {0x00: "NEW", 0x01: "BUSY", 0x02: "SUCCESSFUL", 0x03: "FAILURE", 0x04: "NOT_SUPPORTED"}
    return (f"status={names.get(status, hex(status))} size={size} "
            f"payload={body.hex()} ascii={body.decode('latin1').strip(chr(0))!r}")


def try_interface(d, mode: str):
    h = lib.hid_open_path(d["path"])
    if not h:
        return f"open failed: {lib.hid_error(None)}"
    buf = ctypes.create_string_buffer(91)
    notes = []
    for label, (cls, cid, args) in {
        "firmware(0x00/0x81)": (0x00, 0x81, b"\x00\x00"),
        "device_mode(0x00/0x82)": (0x00, 0x82, b"\x00\x00"),
    }.items():
        pkt = build(cls, cid, args)
        if mode == "write":
            w = lib.hid_write(h, pkt, 90)
        else:
            w = lib.hid_send_feature_report(h, b"\x00" + pkt, 91)
        n = lib.hid_read_timeout(h, buf, 90, 600)
        notes.append(f"  {label:24s} [{mode}] w={w} read={n} {describe_reply(buf.raw, n)}")
        if n <= 0:
            try:
                n2 = lib.hid_get_feature_report(h, buf, 90)
                notes.append(f"    feature-getread={n2} {describe_reply(buf.raw, n2)}")
            except Exception as e:
                notes.append(f"    feature-getread err {e}")
    lib.hid_close(h)
    return "\n".join(notes)


def main():
    devs = enumerate_razer()
    if not devs:
        print("没有找到 Razer 设备")
        return
    seen = set()
    for d in devs:
        key = (d["interface_number"], d["usage_page"], d["usage"])
        if key in seen:
            continue
        seen.add(key)
        tag = f"iface={d['interface_number']} usage_page=0x{d['usage_page']:04X} usage=0x{d['usage']:04X}"
        print(f"\n### {tag}")
        for mode in ("write", "feature"):
            try:
                print(try_interface(d, mode))
            except Exception as e:
                print(f"  [{mode}] error: {e}")


if __name__ == "__main__":
    main()
