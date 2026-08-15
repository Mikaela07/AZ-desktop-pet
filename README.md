# AZ 桌宠 🐾

一只轻量的桌面宠物，用 **Python + Tkinter + Pillow** 写成。无边框透明窗口，可以左键拖着走、右键呼出菜单，还支持自定义皮肤（GIF / PNG 序列帧）、自动抠背景和开机自启。

> 无需任何额外运行时，仅依赖 Pillow，直接 `python main.py` 就能跑。

## ✨ 功能特性

- 🪟 **透明无边框**：色键抠图实现透明窗口，宠物真正“悬浮”在桌面上
- 📌 **强制置顶**：Windows 下通过 Win32 API（`WS_EX_TOPMOST`）保持置顶，不会被别的窗口盖住
- 🖱️ **交互丰富**：左键拖动 / 双击触发 / 悬停触发 / 右键菜单
- 🎨 **自定义皮肤**：支持 GIF、WebP 动画和 PNG/JPG 序列帧，一键切换
- 🧹 **自动抠背景**：对不带透明通道的素材，自动识别并去掉背景（四角 + 四边采样，对渐变背景友好）
- ⚙️ **可视化设置面板**：皮肤、尺寸（64–384px）、动作绑定都能调
- 🚀 **开机自启**：Windows 注册表 / macOS LaunchAgents / Linux autostart 三平台支持
- 💾 **配置持久化**：位置、皮肤、尺寸等自动保存到 `config.json`

## 🚀 快速开始

### 环境要求

- Python 3.x（Windows 安装包自带 Tkinter，无需额外配置）

### 安装依赖

```bash
pip install -r requirements.txt
```

（必需依赖只有 Pillow；numpy 为可选，装上能大幅加速自动抠背景和 alpha 处理）

### 运行

```bash
python main.py
```

运行后桌面上会出现一只宠物：**左键按住拖动**移动它，**右键**打开菜单。

## 📦 打包成 EXE（可选）

用 PyInstaller 打包成独立可执行文件：

```bash
pip install pyinstaller
pyinstaller --onefile --windowed main.py
```

打包完成后，需要把 `config.json` 和 `assets/` 文件夹复制到 `DesktopPet.exe` **同级目录**下（程序运行时会在 exe 旁边查找这两者），最终目录结构如下：

```
DesktopPet.exe
config.json
assets/
  └── skins/
      └── default/
          ├── idle.gif
          ├── drag.gif
          └── play.gif
```

## 🎨 自定义皮肤

皮肤放在 `assets/skins/<皮肤名>/` 目录下，每个**动作**对应一个 GIF 文件或一个帧序列文件夹：

```
assets/skins/
├── default/          # 默认皮肤
│   ├── idle.gif      # 待机动作（单文件 GIF 动画）
│   ├── drag.gif      # 拖动动作
│   └── play.gif      # 跳舞动作
└── my_skin/          # 你的自定义皮肤
    ├── idle.gif
    ├── happy/
    │   ├── 00.png    # 帧序列（按文件名顺序播放，建议补零）
    │   ├── 01.png
    │   └── 02.png
    └── dance.webp
```

说明：

- **支持的格式**：`.png`、`.jpg`、`.jpeg`、`.gif`、`.webp`
- **GIF 动画**：直接读取 GIF 自带的每帧时长
- **PNG 序列帧**：默认每帧 100ms（PNG 无法记录时长）
- **透明通道**：素材自带透明通道就原样保留；不带透明通道（如普通 JPG/PNG 背景图）会自动抠背景
- **动作缺省回退**：某个动作的素材缺失时，自动回退到 `idle`

可用的动作名：`idle`、`happy`、`play`、`drag`、`blink`、`curious`、`sleep`、`dance`。

## 🖱️ 操作与动作

| 操作 | 默认动作 | 说明 |
| --- | --- | --- |
| 左键按住拖动 | `drag` | 拖动宠物，松手回到待机 |
| 左键双击 | `play` | 跳舞 10 秒 |
| 鼠标悬停 | `blink` | 眨眼，约 0.5 秒 |
| 右键点击 | `curious` | 好奇，并弹出菜单 |

右键菜单还提供：**设置**、**切换皮肤**、**跳舞(10秒)**、**复位位置**、**开机自启**、**退出**。

这些绑定都可以在「🔧 设置」面板里改成任意动作名。

## ⚙️ 配置说明（`config.json`）

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `skin` | `default` | 当前皮肤名 |
| `pet_size` | `128` | 宠物显示尺寸（正方形，像素） |
| `frame_interval_ms` | `150` | 帧间隔兜底（GIF 无时长信息时） |
| `window_pos` | `[200, 400]` | 窗口初始位置 `[x, y]` |
| `bg_tolerance` | `30` | 自动抠背景的颜色容差（0–120） |
| `alpha_threshold` | `128` | alpha 二值化阈值（0–255），越小保留越多像素 |
| `actions` | — | 动作绑定映射（见上表） |

> 程序退出时会自动把当前位置写回 `window_pos`，下次启动从原位置出现。

## 📁 项目结构

```
AZ/
├── main.py              # 主程序（含皮肤系统、置顶、抠背景、设置面板）
├── config.json          # 运行配置（自动生成/更新）
├── requirements.txt     # 依赖清单
├── assets/
│   └── skins/
│       └── default/     # 默认皮肤（idle / drag / play 三个 GIF）
└── README.md
```

## ⚠️ 平台兼容性

- **Windows**：完整支持，透明窗口 + 强制置顶 + 开机自启效果最佳
- **macOS / Linux**：透明窗口和置顶降级为 `-alpha` 整体透明等备用方案，基本可用

## 📄 许可

MIT License（如需要请自行添加 `LICENSE` 文件）。
