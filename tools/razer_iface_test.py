#!/usr/bin/env python3
from __future__ import annotations
import ctypes, sys
sys.path.insert(0, "tools")
from razer_probe import HidDeviceInfo, lib, packet, RAZER_VID

lib.hid_init()
devs = lib.hid_enumerate(0, 0)
rows, cur = [], devs
while cur:
    rows.append(cur.contents); cur = cur.contents.next
razer = [d for d in rows if d.vendor_id == RAZER_VID]

seen = set()
for d in razer:
    key = (d.interface_number, d.usage_page, d.usage)
    if key in seen: continue
    seen.add(key)
    h = lib.hid_open_path(d.path)
    tag = f"iface={d.interface_number} up=0x{d.usage_page:04X} usage=0x{d.usage:04X}"
    if not h:
        print(f"{tag}: OPEN FAIL"); continue
    buf = ctypes.create_string_buffer(256)
    # 1) firmware version
    w = lib.hid_write(h, packet(0x00, 0x81, b"\x00\x00", txn=0x1F), 90)
    n = lib.hid_read_timeout(h, buf, 90, 1200)
    fw = ""
    if n > 12:
        status = buf.raw[1]; size = buf.raw[8]
        fw = bytes(buf.raw[11:11+min(size,20)]).decode("latin1").strip("\x00")
        print(f"{tag}: w={w} read={n} status=0x{status:02X} size={size} fw='{fw}'")
    else:
        print(f"{tag}: w={w} read={n}")
    # 2) brightness 100%
    w2 = lib.hid_write(h, packet(0x0F, 0x04, b"\x00\xFF", txn=0x20), 90)
    n2 = lib.hid_read_timeout(h, buf, 90, 800)
    st2 = f"0x{buf.raw[1]:02X}" if n2 > 0 else "-"
    print(f"    brightness100: w={w2} read={n2} status={st2}")
    # 3) static effect
    w3 = lib.hid_write(h, packet(0x0F, 0x02, b"\x00\x01\x00\x00\x01", txn=0x21), 90)
    n3 = lib.hid_read_timeout(h, buf, 90, 800)
    st3 = f"0x{buf.raw[1]:02X}" if n3 > 0 else "-"
    print(f"    static effect: w={w3} read={n3} status={st3}")
    lib.hid_close(h)
lib.hid_free_enumeration(devs)
