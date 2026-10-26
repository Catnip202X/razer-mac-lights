#!/usr/bin/env python3
"""逐键矩阵参数组合测试"""
from __future__ import annotations
import sys, time
sys.path.insert(0, "tools")
from razerctl import Device, VARSTORE, BACKLIGHT_LED

STAT = {0x00:"NEW",0x01:"BUSY",0x02:"OK",0x03:"FAILURE",0x04:"NOT_SUPPORTED?",0x05:"NOT_SUPPORTED"}

dev = Device()

def show(tag, r):
    st = r.get("status", -1)
    print(f"  {tag:52s} status=0x{st:02X} {STAT.get(st,'?')}")
    return st == 0x02

print("=== 1) custom effect 变体 ===")
variants = {
    "args[00,00,08] size=0x0C txn=0x3F": (bytes([0x00,0x00,0x08,0,0,0,0,0,0,0,0,0]), 0x3F),
    "args[00,00,08] size=0x0C txn=0x1F": (bytes([0x00,0x00,0x08,0,0,0,0,0,0,0,0,0]), 0x1F),
    "args[01,05,08] size=0x0C txn=0x3F": (bytes([0x01,0x05,0x08,0,0,0,0,0,0,0,0,0]), 0x3F),
    "args[00,00,08] size=0x06 txn=0x3F": (bytes([0x00,0x00,0x08,0,0,0]), 0x3F),
}
for tag, (args, txn) in variants.items():
    show(tag, dev.exec(0x0F, 0x02, args, txn=txn))
    time.sleep(0.05)

print("\n=== 2) set_row 变体 (class 0x0F id 0x03) ===")
for cols, dsize, txn in [(16, 0x47, 0x3F), (16, 0x35, 0x3F), (15, 0x32, 0x3F),
                         (16, 0x35, 0x1F), (15, 0x32, 0x1F)]:
    args = bytearray(dsize)
    args[2] = 0          # row
    args[3] = 0          # start col
    args[4] = cols - 1   # stop col
    args[5:5 + cols*3] = bytes([0x00, 0xFF, 0x88]) * cols
    r = dev.exec(0x0F, 0x03, bytes(args), txn=txn)
    show(f"row0 cols={cols} size=0x{dsize:02X} txn=0x{txn:02X}", r)
    time.sleep(0.05)

print("\n=== 3) standard matrix (class 0x03 id 0x0B) 对照 ===")
for txn in (0x3F, 0xFF):
    args = bytearray(0x46)
    args[0] = 0xFF       # frame id
    args[1] = 0          # row
    args[2] = 0          # start
    args[3] = 15         # stop
    args[4:4+48] = bytes([0xFF,0x00,0x44]) * 16
    show(f"standard row0 16cols size=0x46 txn=0x{txn:02X}", dev.exec(0x03, 0x0B, bytes(args), txn=txn))
    time.sleep(0.05)

dev.close()
