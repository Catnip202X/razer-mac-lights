#!/usr/bin/env python3
"""
razerctl — macOS 上的 Razer 键盘灯光控制（无需 Synapse / 无需内核驱动）

原理：雷蛇键盘在 HID 接口 2（usage page 0x0001）接受 90 字节的 Razer 私有 report，
      macOS 上用 feature report 通道下发（SET_REPORT / GET_REPORT report-id 0）。
      协议取自 OpenRazer 驱动（GPL-2.0）中的 razer_report / razerchromacommon。

用法：
  razerctl.py info
  razerctl.py brightness 100          # 0-100 (%)
  razerctl.py static ff3300           # 静态色
  razerctl.py off
  razerctl.py spectrum
  razerctl.py wave left|right
  razerctl.py breathing [ff0000]      # 无色=随机色
  razerctl.py custom keys.json        # 逐键自定义
"""
from __future__ import annotations

import ctypes
import json
import sys
import time

RAZER_VID = 0x1532

# Razer Huntsman Mini (VID 0x1532 / PID 0x0257), 控制接口 = 2
KNOWN = {
    0x0257: ("Razer Huntsman Mini", 2),
}

# OpenRazer: VARSTORE / LED id
VARSTORE = 0x01
BACKLIGHT_LED = 0x05
ZERO_LED = 0x00

# 状态码
ST_SUCCESS = 0x02
ST_BUSY = 0x01


# ---------------------------------------------------------------- hidapi 封装
class _HidDeviceInfo(ctypes.Structure):
    pass


_HidDeviceInfo._fields_ = [
    ("path", ctypes.c_char_p), ("vendor_id", ctypes.c_ushort),
    ("product_id", ctypes.c_ushort), ("serial_number", ctypes.c_wchar_p),
    ("release_number", ctypes.c_ushort), ("manufacturer_string", ctypes.c_wchar_p),
    ("product_string", ctypes.c_wchar_p), ("usage_page", ctypes.c_ushort),
    ("usage", ctypes.c_ushort), ("interface_number", ctypes.c_int),
    ("next", ctypes.POINTER(_HidDeviceInfo)), ("bus_type", ctypes.c_int),
]


def _load_lib():
    for cand in ("/opt/homebrew/lib/libhidapi.dylib",
                 "/usr/local/lib/libhidapi.dylib",
                 "libhidapi.dylib", "libhidapi-0.15.0.dylib"):
        try:
            lib = ctypes.CDLL(cand)
            break
        except OSError:
            continue
    else:
        sys.exit("找不到 libhidapi —— 先装：brew install hidapi")

    lib.hid_init.restype = ctypes.c_int
    lib.hid_enumerate.restype = ctypes.POINTER(_HidDeviceInfo)
    lib.hid_enumerate.argtypes = [ctypes.c_ushort, ctypes.c_ushort]
    lib.hid_free_enumeration.argtypes = [ctypes.POINTER(_HidDeviceInfo)]
    lib.hid_open_path.restype = ctypes.c_void_p
    lib.hid_open_path.argtypes = [ctypes.c_char_p]
    lib.hid_send_feature_report.restype = ctypes.c_int
    lib.hid_send_feature_report.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
    lib.hid_get_feature_report.restype = ctypes.c_int
    lib.hid_get_feature_report.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
    lib.hid_close.argtypes = [ctypes.c_void_p]
    lib.hid_error.restype = ctypes.c_wchar_p
    lib.hid_error.argtypes = [ctypes.c_void_p]
    return lib


lib = _load_lib()


def enumerate_razer():
    lib.hid_init()
    devs = lib.hid_enumerate(0, 0)
    out, cur = [], devs
    while cur:
        d = cur.contents
        if d.vendor_id == RAZER_VID:
            out.append({
                "path": d.path,
                "product_id": d.product_id,
                "iface": d.interface_number,
                "usage_page": d.usage_page,
                "usage": d.usage,
                "product": d.product_string,
                "serial": d.serial_number,
            })
        cur = d.next
    lib.hid_free_enumeration(devs)
    return out


# ---------------------------------------------------------------- Razer 协议
def build_report(cls: int, cid: int, args: bytes = b"", txn: int = 0x3F) -> bytes:
    """90 字节 Razer report（不含 report-id 前缀）"""
    p = bytearray(90)
    p[0] = 0x00          # status: new command
    p[1] = txn           # transaction id
    p[2] = 0x00          # remaining packets msb
    p[3] = 0x00          # remaining packets lsb
    p[4] = 0x00          # protocol type
    p[5] = len(args)     # data size
    p[6] = cls
    p[7] = cid
    p[8:8 + len(args)] = args
    crc = 0
    for i in range(2, 88):
        crc ^= p[i]
    p[88] = crc
    p[89] = 0x00
    return bytes(p)


class Device:
    def __init__(self, pid: int | None = None):
        cands = [d for d in enumerate_razer() if d["usage_page"] == 0x0001
                 and d["usage"] in (0x0001, 0x0002) and d["iface"] is not None]
        if pid:
            cands = [d for d in cands if d["product_id"] == pid]
        if not cands:
            sys.exit("没有找到可控制的 Razer 设备（检查键盘是否插好）")
        # 优先使用已知的控制接口号
        cands.sort(key=lambda d: (d["iface"] != KNOWN.get(d["product_id"], (None, 2))[1],))
        self.info = cands[0]
        self.h = lib.hid_open_path(self.info["path"])
        if not self.h:
            sys.exit(f"打开设备失败: {lib.hid_error(None)}")

    @property
    def name(self) -> str:
        return self.info["product"] or "Razer device"

    def _send(self, payload: bytes) -> None:
        n = lib.hid_send_feature_report(self.h, b"\x00" + payload, len(payload) + 1)
        if n < 0:
            sys.exit(f"发送失败: {lib.hid_error(self.h)}")
        time.sleep(0.05)

    def _recv(self) -> dict:
        buf = ctypes.create_string_buffer(91)
        n = lib.hid_get_feature_report(self.h, buf, 91)
        if n < 2:
            return {"ok": False, "raw": b""}
        raw = buf.raw[:n]
        return {
            "ok": raw[1] == ST_SUCCESS,
            "status": raw[1],
            "txn": raw[2],
            "size": raw[6],
            "cmd_id": raw[8],
            "args": raw[9:9 + raw[6]],
            "raw": raw,
        }

    def exec(self, cls: int, cid: int, args: bytes = b"", txn: int = 0x3F) -> dict:
        self._send(build_report(cls, cid, args, txn))
        return self._recv()

    # -- 查询
    def firmware(self) -> str:
        """固件版本：args = [major, minor, ...] -> v1.12"""
        r = self.exec(0x00, 0x81, b"\x00\x00", txn=0xFF)
        a = r["args"]
        if len(a) >= 2:
            return f"v{a[0]}.{a[1]}"
        return ""

    def serial(self) -> str:
        r = self.exec(0x00, 0x82, b"\x00\x00", txn=0xFF)
        return r["args"].split(b"\x00")[0].decode("latin1", "replace").strip()

    def brightness_get(self) -> int | None:
        r = self.exec(0x0F, 0x84, bytes([VARSTORE, BACKLIGHT_LED]), txn=0x3F)
        if r["ok"] and len(r["args"]) >= 3:
            return r["args"][2]
        return None

    # -- 灯光
    def brightness_set(self, value: int) -> dict:
        return self.exec(0x0F, 0x04, bytes([VARSTORE, BACKLIGHT_LED, value & 0xFF]))

    def effect_none(self) -> dict:
        return self.exec(0x0F, 0x02, bytes([VARSTORE, BACKLIGHT_LED, 0x00, 0, 0, 0]))

    def effect_static(self, r: int, g: int, b: int) -> dict:
        return self.exec(0x0F, 0x02,
                         bytes([VARSTORE, BACKLIGHT_LED, 0x01, 0, 0, 0x01, r, g, b]))

    def effect_spectrum(self) -> dict:
        return self.exec(0x0F, 0x02, bytes([VARSTORE, BACKLIGHT_LED, 0x03, 0, 0, 0]))

    def effect_wave(self, direction: int = 0) -> dict:
        return self.exec(0x0F, 0x02,
                         bytes([VARSTORE, BACKLIGHT_LED, 0x04, direction & 2, 0x28, 0]))

    def effect_breathing_random(self) -> dict:
        return self.exec(0x0F, 0x02, bytes([VARSTORE, BACKLIGHT_LED, 0x02, 0, 0, 0]))

    def effect_breathing_single(self, r: int, g: int, b: int) -> dict:
        return self.exec(0x0F, 0x02,
                         bytes([VARSTORE, BACKLIGHT_LED, 0x02, 0x01, 0, 0x01, r, g, b]))

    def effect_custom(self) -> dict:
        """切到 custom 模式。注意 varstore/led_id 必须是 0x00/0x00（实测 0x01/0x05 会被拒）"""
        return self.exec(0x0F, 0x02, bytes([0x00, 0x00, 0x08, 0, 0, 0, 0, 0, 0, 0, 0, 0]))

    def set_row(self, row: int, start_col: int, stop_col: int, rgb: bytes,
                data_size: int | None = None) -> dict:
        # Huntsman Mini 要求 data_size 精确等于 row_length + 5，多一列都会被 NOT_SUPPORTED
        if data_size is None:
            data_size = ((stop_col + 1) - start_col) * 3 + 5
        args = bytearray(data_size)
        args[2] = row
        args[3] = start_col
        args[4] = stop_col
        args[5:5 + len(rgb)] = rgb
        return self.exec(0x0F, 0x03, bytes(args))

    def close(self):
        lib.hid_close(self.h)


# ---------------------------------------------------------------- CLI
def parse_color(s: str) -> tuple[int, int, int]:
    s = s.strip().lstrip("#")
    if "," in s:
        parts = [int(x) for x in s.split(",")]
        return parts[0], parts[1], parts[2]
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        sys.exit(f"颜色格式不对: {s}（示例 ff3300 或 255,51,0）")
    return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)


def ok(r: dict) -> str:
    return "OK" if r.get("ok") else f"FAIL(status=0x{r.get('status', 0):02X})"


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0

    cmd, rest = argv[0], argv[1:]
    dev = Device()

    if cmd == "info":
        print(f"设备: {dev.name}")
        print(f"PID : 0x{dev.info['product_id']:04X}  iface={dev.info['iface']}")
        print(f"序列号: {dev.serial() or '(无)'}")
        print(f"固件  : {dev.firmware() or '(无)'}")
        b = dev.brightness_get()
        print(f"亮度  : {b if b is not None else '(读不到)'}")
    elif cmd == "brightness":
        if not rest:
            sys.exit("用法: brightness 0-100")
        pct = max(0, min(100, int(rest[0])))
        val = round(pct * 255 / 100)
        print(f"亮度 {pct}% -> {ok(dev.brightness_set(val))}")
    elif cmd == "static":
        if not rest:
            sys.exit("用法: static ff3300")
        r, g, b = parse_color(rest[0])
        print(f"静态色 #{r:02x}{g:02x}{b:02x} -> {ok(dev.effect_static(r, g, b))}")
    elif cmd == "off":
        print(f"关灯 -> {ok(dev.effect_none())}")
    elif cmd == "spectrum":
        print(f"光谱循环 -> {ok(dev.effect_spectrum())}")
    elif cmd == "wave":
        d = 1 if rest and rest[0].lower() in ("right", "r") else 0
        print(f"波浪({rest[0] if rest else 'left'}) -> {ok(dev.effect_wave(d))}")
    elif cmd == "breathing":
        if rest:
            r, g, b = parse_color(rest[0])
            print(f"呼吸 #{r:02x}{g:02x}{b:02x} -> {ok(dev.effect_breathing_single(r, g, b))}")
        else:
            print(f"随机呼吸 -> {ok(dev.effect_breathing_random())}")
    elif cmd == "fill":
        # 整片矩阵刷同一颜色，用来标定行/列范围
        if not rest:
            sys.exit("用法: fill ff3300 [rows] [cols] [data_size]")
        r, g, b = parse_color(rest[0])
        rows = int(rest[1]) if len(rest) > 1 else 6
        cols = int(rest[2]) if len(rest) > 2 else 15
        dsize = int(rest[3], 0) if len(rest) > 3 and rest[3] != "auto" else None
        print(f"custom 模式 -> {ok(dev.effect_custom())}")
        time.sleep(0.1)
        rgb = bytes([r, g, b]) * cols
        for i in range(rows):
            res = dev.set_row(i, 0, cols - 1, rgb, data_size=dsize)
            print(f"  row {i}: col 0..{cols - 1} -> {ok(res)}")
            time.sleep(0.03)
    elif cmd == "key":
        # 单格测试：key ROW COL RRGGBB —— 用来标定某个物理键在矩阵里的位置
        if len(rest) < 3:
            sys.exit("用法: key ROW COL RRGGBB")
        row, col = int(rest[0]), int(rest[1])
        r, g, b = parse_color(rest[2])
        dev.effect_custom()
        time.sleep(0.05)
        print(f"row={row} col={col} -> {ok(dev.set_row(row, col, col, bytes([r, g, b])))}")
    elif cmd == "custom":
        if not rest:
            sys.exit("用法: custom keys.json")
        data = json.loads(open(rest[0]).read())
        rows = data["rows"]      # [[[r,g,b], ...], ...]
        cols_per_row = data.get("cols", [len(r) for r in rows])
        print(f"custom 模式 -> {ok(dev.effect_custom())}")
        time.sleep(0.1)
        for i, row in enumerate(rows):
            rgb = bytes(c for px in row for c in px)
            print(f"  row {i}: {len(row)} keys -> "
                  f"{ok(dev.set_row(i, 0, len(row) - 1, rgb))}")
            time.sleep(0.02)
    else:
        sys.exit(f"未知命令: {cmd}\n\n{__doc__}")

    dev.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
