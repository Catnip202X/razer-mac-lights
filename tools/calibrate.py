#!/usr/bin/env python3
"""
逐键映射标定：把 5×15 矩阵的每个格子对应到具体物理键。

做法：一次点亮一个格子（白光，其余全黑），你在键盘上看哪个键亮了，输入它的名字。
      回车 = 沿用猜测值；输入 - = 这个格子没有灯；q = 保存退出。

结果写到 keymap.json：
    { "grid": [ [ "Esc", "1", ... ], ... ] }   5 行 × 15 列
"""
from __future__ import annotations
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from razerctl import Device  # noqa: E402

ROWS, COLS = 5, 15
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYMAP = os.path.join(HERE, "keymap.json")

# 标准 60% ANSI 的猜测（只用来当默认值，你按实际键盘改）
GUESS = [
    ["Esc", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-", "=", "BSpc", ""],
    ["Tab", "Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P", "[", "]", "\\", ""],
    ["Caps", "A", "S", "D", "F", "G", "H", "J", "K", "L", ";", "'", "Enter", "", ""],
    ["LShift", "Z", "X", "C", "V", "B", "N", "M", ",", ".", "/", "RShift", "", "", ""],
    ["LCtrl", "LWin", "LAlt", "Space", "RAlt", "Fn", "Menu", "RCtrl", "Left", "Down", "Right", "", "", "", ""],
]

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
DIM = (0, 60, 255)


def paint(dev, lit: set[tuple[int, int]]):
    """lit 里的格子亮白，其它暗蓝（便于看清空位边界）"""
    dev.effect_custom()
    time.sleep(0.02)
    for row in range(ROWS):
        colors = []
        for col in range(COLS):
            if (row, col) in lit:
                colors.append(WHITE)
            else:
                colors.append(DIM)
        dev.set_row(row, 0, COLS - 1, bytes(c for px in colors for c in px))
        time.sleep(0.01)


def load_grid():
    if os.path.exists(KEYMAP):
        try:
            data = json.load(open(KEYMAP))
            grid = data["grid"]
            if len(grid) == ROWS and all(len(r) == COLS for r in grid):
                return grid
        except Exception:
            pass
    return [row[:] for row in GUESS]


def save(grid):
    with open(KEYMAP, "w") as f:
        json.dump({"grid": grid}, f, ensure_ascii=False, indent=2)
    print(f"\n已保存 -> {KEYMAP}")


def main():
    dev = Device()
    grid = load_grid()
    print(f"标定 {ROWS}×{COLS} 矩阵。当前格子会亮白光，其余暗蓝。")
    print("回车=沿用建议值   输入键名=改写   -  =这个格子是空的   q=保存退出\n")
    total = ROWS * COLS
    n = 0
    try:
        for row in range(ROWS):
            print(f"--- 第 {row} 行 ---")
            for col in range(COLS):
                n += 1
                paint(dev, {(row, col)})
                suggestion = grid[row][col]
                prompt = f"[{n:2d}/{total}] row={row} col={col}  建议 '{suggestion}' > "
                ans = input(prompt).strip()
                if ans.lower() == "q":
                    save(grid)
                    return
                if ans == "-":
                    grid[row][col] = ""
                elif ans:
                    grid[row][col] = ans
                # 空输入 = 保留 suggestion
    except KeyboardInterrupt:
        print("\n中断")
    save(grid)
    # 收尾：全亮一下确认
    dev.effect_custom()
    time.sleep(0.05)
    for r in range(ROWS):
        dev.set_row(r, 0, COLS - 1, bytes([0x44, 0xD6, 0x2C]) * COLS)
    print("完成，键盘已刷绿。")


if __name__ == "__main__":
    main()
