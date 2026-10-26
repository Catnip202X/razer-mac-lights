# Razer Huntsman Mini — macOS 灯控

雷蛇没给 macOS 出 Synapse，所以插到 Mac 上键盘只剩出厂灯效、改不了。这里是一套**不依赖任何雷蛇官方软件**的替代方案：直接走键盘的 HID 私有协议。

## 结论先说

| 项目 | 结果 |
|---|---|
| 设备 | Razer Huntsman Mini，`VID 0x1532` / `PID 0x0257` |
| 序列号 | `<DEVICE_SERIAL>` |
| 固件 | `v1.12` |
| 控制接口 | HID `interface 2`（usage page `0x0001`） |
| 传输方式 | **feature report**（91 字节，report-id `0`），`hid_read` 读不到，必须 `hid_get_feature_report` |
| 灯效矩阵 | **5 行 × 15 列**（60% 布局，EXTENDED matrix），`data_size` 必须精确 `row_length + 5` |
| transaction id | `0x3F`（灯光命令） |

## 为什么 Mac 上没有灯控

1. Razer Synapse 只有 Windows 版；Chroma SDK 也没有 macOS 实现 —— 官方层面就是不管。
2. 键盘的灯控是**厂商私有 HID 协议**（90 字节 report），协议本身被 [OpenRazer](https://github.com/openrazer/openrazer) 逆向出来了。
3. macOS 上完全可以**绕过官方软件**直接说这套协议，本工具就是这么做的。

## 实测证据（都在这台机器上跑出来的）

```
写亮度 50%  → 回读 128
写亮度 100% → 回读 255
固件查询    → v1.12
序列号查询  → <DEVICE_SERIAL>
矩阵 row 0-4 × col 0-14 → 全部 status=0x02 (SUCCESSFUL)
```

坑点（踩过才知道）：
- `custom` 效果命令的 varstore / led_id 必须是 `0x00 / 0x00`，传 `0x01 / 0x05` 会被拒（`FAILURE`）。
- 逐行写色时 `data_size` 一列都不能多，16 列直接 `NOT_SUPPORTED`。
- 行 5 不存在（`NOT_SUPPORTED`），60% 键盘只有 5 行。

## 菜单栏 App（推荐日常用）

已构建并安装：`/Applications/RazerLights.app`（LSUIElement，只在菜单栏，不占 Dock）。

菜单里能做什么：

| 分组 | 内容 |
|---|---|
| 设备信息 | 型号 + 固件版本，未连接会提示 |
| 亮度 | **滑动条 0–100%**，拖动实时跟手（走只写不读的快速通道），右侧显示百分比 |
| 纯色 | 雷蛇绿、血红、橙、琥珀、青、冰蓝、紫、品红、纯白、暖白 + 系统取色器 |
| 效果 | 光谱循环、波浪 →/←、随机呼吸、关灯 |
| 逐键 | 静态彩虹、彩虹流动 ▶（动画）、整片填充当前色 |
| 🎵 音乐律动 | 麦克风音量驱动灯光脉冲（首次需授权麦克风） |
| 开机自动应用 | 写入 `~/Library/LaunchAgents/com.local.razerlights.plist`，登录时恢复上次配色 |
| 重新连接设备 | 插拔键盘后手动重连 |

重新构建：

```bash
cd <repo>/menubar && ./build.sh
cp -R RazerLights.app /Applications/
```

## macOS 权限说明（重要）

`IOHIDDeviceOpen` 在 macOS 上受 TCC「输入监控」管控，行为按进程启动方式不同：

| 启动方式 | 权限来源 | 结果 |
|---|---|---|
| 终端里直接跑二进制 / CLI | 继承 Terminal 的输入监控授权 | ✅ 正常 |
| Finder / `open` / LaunchAgent 启动的 .app | 需要 app 自己获得授权 | ⚠️ 可能 `kIOReturnNotPermitted` (`0xE00002E2`) |

授予方式：**系统设置 → 隐私与安全性 → 输入监控** 里添加 `RazerLights.app` 并打开开关，
然后重启 app。也可以用 `IOHIDCheckAccess(kIOHIDRequestTypeListenEvent)` 判断当前状态
（返回 `1` = Denied，此时系统不会再弹窗询问）。

如果这台机器上怎么都授不下来（部分 macOS 版本对本地签名 app 很严），还有一条绕开 TCC 的路：
做一个 **root LaunchDaemon** 专管 HID 命令，菜单栏 app 通过本地 socket 调用它。代码没包含，
但协议层 `RazerHID.swift` 可以直接复用。

## 命令行工具

```bash
cd <repo>

python3 tools/razerctl.py info            # 设备/固件/序列号/亮度
python3 tools/razerctl.py brightness 60   # 亮度 0-100%
python3 tools/razerctl.py static ff0033   # 静态颜色
python3 tools/razerctl.py off             # 关灯
python3 tools/razerctl.py spectrum        # 光谱循环
python3 tools/razerctl.py wave left       # 波浪
python3 tools/razerctl.py breathing       # 随机呼吸
python3 tools/razerctl.py breathing 00aaff
python3 tools/razerctl.py fill 00ff88 5 15  # 整片刷色
python3 tools/razerctl.py key 0 3 ff0000    # 单格测试，用来标定键位
```

依赖：`brew install hidapi`（已装）。

## 逐键自定义

`custom` 命令吃一个 JSON（5 行 × 15 列的 RGB）：

```json
{ "rows": [
  [[255,0,0],[255,0,0],[255,0,0],[255,0,0],[255,0,0],[255,0,0],[255,0,0],[255,0,0],[255,0,0],[255,0,0],[255,0,0],[255,0,0],[255,0,0],[255,0,0],[255,0,0]],
  [[0,255,0],[0,255,0],[0,255,0],[0,255,0],[0,255,0],[0,255,0],[0,255,0],[0,255,0],[0,255,0],[0,255,0],[0,255,0],[0,255,0],[0,255,0],[0,255,0],[0,255,0]],
  [[0,0,255],[0,0,255],[0,0,255],[0,0,255],[0,0,255],[0,0,255],[0,0,255],[0,0,255],[0,0,255],[0,0,255],[0,0,255],[0,0,255],[0,0,255],[0,0,255],[0,0,255]],
  [[255,255,0],[255,255,0],[255,255,0],[255,255,0],[255,255,0],[255,255,0],[255,255,0],[255,255,0],[255,255,0],[255,255,0],[255,255,0],[255,255,0],[255,255,0],[255,255,0],[255,255,0]],
  [[255,0,255],[255,0,255],[255,0,255],[255,0,255],[255,0,255],[255,0,255],[255,0,255],[255,0,255],[255,0,255],[255,0,255],[255,0,255],[255,0,255],[255,0,255],[255,0,255],[255,0,255]]
] }
```

行列 → 物理键的映射还没标定，用 `key ROW COL ffffff` 一个个试最靠谱，标完之后就能画任意图案/打字高亮。

## 已知边界

- **不能**导入 Windows 上 Synapse 的配置 —— 那些存在 Windows 侧，mac 读不到。
- **不能**做"按键触发灯效"（除非再加一层键盘事件监听）。
- 亮度/静态色是写进键盘的，**掉电后可能不保留**（板载配置文件另说）。
- 官方图形界面没有，`razer-macos`（1kc/razer-macos）只支持到 macOS 12，当前系统跑不了；OpenRGB 的 macOS 版可以当 GUI 备选。

## 逐键映射标定

图形界面菜单里的「逐键」不需要标定就能用（矩阵坐标直接上色）。只有**打字高亮**这类功能需要
知道每个格子是哪个物理键，跑一次标定即可：

```bash
cd <repo>
python3 tools/calibrate.py
```

它会一次点亮一个格子（白光，其余暗蓝），你输入对应的键名；回车=沿用建议值，`-`=这个格子没灯，
`q`=保存退出。结果写入 `keymap.json`（5 行 × 15 列）。

## 文件

- `tools/razerctl.py` — 主工具（hidapi + Razer 协议）
- `tools/hid_selftest.swift` — 最小 IOKit 验证（30 行读固件）
- `tools/razer_probe.py` — HID 接口枚举探测
- `tools/razer_proto.py` — 协议收发测试
- `tools/razer_desc.py` — report descriptor 解析
- `tools/razer_matrix_test.py` — 矩阵参数组合测试（就是靠它找到 15 列 / data_size 的规律）
- `tools/calibrate.py` — 逐键映射标定
- `menubar/RazerHID.swift` — Swift + IOKit 的 HID 灯控层
- `menubar/AudioPulse.swift` — 麦克风音量包络
- `menubar/main.swift` — 菜单栏 UI
- `menubar/build.sh` — 一键构建 .app（签名身份从 `CODESIGN_IDENTITY` 或本机证书自动挑选）

## 发布前脱敏（每次上传到任何地方都要做）

这个项目天然会沾上本机信息，提交/上传前必须扫一遍：

```bash
grep -rIn -E "序列号|/Users/[a-zA-Z0-9]+|Apple Development|TeamIdentifier|@[a-z]+\.(com|cn|net)" \
     . --exclude-dir=.git --exclude-dir=RazerLights.app
```

必须清理的项：

| 类别 | 例子 | 处理 |
|---|---|---|
| 设备序列号 | 键盘 SN | 替换为 `<DEVICE_SERIAL>` |
| 家目录 / 用户名 | `/Users/<name>/...` | 换成 `<repo>` 或相对路径 |
| 代码签名身份 | `Apple Development: xxx@yyy (TEAMID)` | 从脚本里删掉，改成环境变量/自动探测 |
| 日志与构建产物 | `*.log`、`RazerLights`、`.app/`、`keymap.json` | 写进 `.gitignore` |

## License

MIT —— 见 [LICENSE](LICENSE)。

协议层的 90 字节 report 结构、命令编码与设备矩阵参数来自以下项目的逆向结果，
本仓库是按 macOS/IOKit 独立实现的：

- [OpenRazer](https://github.com/openrazer/openrazer)（GPL-2.0）
- [OpenRGB](https://github.com/CalcProgrammer1/OpenRGB)（GPL-2.0）
