# -*- coding: utf-8 -*-
"""
桌面桌宠 MVP —— Python + Tkinter + Pillow
功能：左键拖动 / 右键设置 / 自定义皮肤 / 自定义动作绑定
作者：仅依赖 Pillow（pip install pillow）
"""

import os
import sys
import json
import time
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk

# ============================================================
# 全局常量
# ============================================================
# PyInstaller 打包后 __file__ 指向临时目录，需要用 sys.executable 定位 exe 旁边
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
SKINS_DIR = os.path.join(BASE_DIR, "assets", "skins")

# 窗口透明色（近黑微绿：肉眼≈黑，但不与灰阶像素冲突）
TRANSPARENT_COLOR = "#000100"
TRANSPARENT_RGB = (0, 1, 0)

# 屏幕底部任务栏高度预估值（像素），复位位置用
TASKBAR_PADDING = 60

# 默认动作列表（设置面板下拉会用到）
AVAILABLE_ACTIONS = ["idle", "happy", "play", "drag", "blink", "curious", "sleep", "dance"]


# ============================================================
# 配置读写
# ============================================================
DEFAULT_CONFIG = {
    "skin": "default",
    "pet_size": 128,
    "frame_interval_ms": 150,
    "window_pos": [200, 400],
    "topmost": True,
    "bg_tolerance": 30,          # 抠背景容差（内部使用，不在设置中暴露）
    "alpha_threshold": 128,      # alpha二值化阈值 0~255，越小保留越多像素，越大抠得越狠
    "actions": {
        "idle": "idle",
        "left_click": "happy",
        "left_double": "play",
        "drag": "drag",
        "hover": "blink",
        "right_click": "curious",
    },
}


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        # 合并默认值，避免缺字段崩
        merged = {**DEFAULT_CONFIG, **cfg}
        merged["actions"] = {**DEFAULT_CONFIG["actions"], **cfg.get("actions", {})}
        return merged
    except Exception:
        return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[WARN] 保存配置失败: {e}")
        return False


# ============================================================
# 皮肤系统（自定义GIF/PNG皮肤）
# ============================================================
class SkinManager:
    """负责按动作名产出帧序列。每帧是固定尺寸的Image，背景为透明色。"""

    def __init__(self, size: int, bg_tolerance: int = 30, alpha_threshold: int = 128):
        self.size = size
        self.bg_tolerance = max(0, min(120, int(bg_tolerance)))
        self.alpha_threshold = max(1, min(255, int(alpha_threshold)))
        # 缓存：{skin_name: {action_name: [Image, Image, ...]}}
        self._cache = {}

    # -------- 外部接口 --------
    def get_frames(self, skin_name: str, action_name: str):
        """返回某个皮肤某个动作的帧列表；缺的动作回退到 idle，绝不返回蓝猫。"""
        skin = self._load_skin(skin_name)
        if action_name in skin and skin[action_name]:
            return skin[action_name]
        # 回退到 idle
        if "idle" in skin and skin["idle"]:
            return skin["idle"]
        # idle 也没有 → 返回空列表（上层会跳过渲染，不会画蓝猫）
        return []

    def get_frame_durations(self, skin_name: str, action_name: str, n_frames: int):
        """返回某个动作的每帧时长（毫秒）。找不到时回退到 idle，再不行用默认 100ms。"""
        cache = getattr(self, "_dur_cache", {})
        # 优先用 action 自身的时长
        durs = cache.get((skin_name, action_name))
        if durs and len(durs) >= n_frames:
            return durs[:n_frames]
        # 回退到 idle 的时长
        durs = cache.get((skin_name, "idle"))
        if durs and len(durs) >= n_frames:
            return durs[:n_frames]
        # 全都没有 → 用全局 frame_interval_ms 兜底（由调用方传入更合适，这里直接返回 None 表示用全局）
        return None

    def list_skins(self):
        """返回所有可用皮肤名（default 永远存在，再加 assets/skins 下的目录）"""
        skins = ["default"]
        if os.path.isdir(SKINS_DIR):
            for name in sorted(os.listdir(SKINS_DIR)):
                path = os.path.join(SKINS_DIR, name)
                if os.path.isdir(path) and name.lower() != "default":
                    skins.append(name)
        return skins

    # -------- 内部 --------
    def _load_skin(self, skin_name: str):
        if skin_name in self._cache:
            return self._cache[skin_name]
        # 只从磁盘加载，不内置任何画
        data = self._load_skin_from_disk(skin_name)
        self._cache[skin_name] = data if data else {}
        return data if data else {}

    def reload(self):
        self._cache.clear()
        if hasattr(self, "_dur_cache"):
            self._dur_cache.clear()

    def set_size(self, new_size: int):
        if new_size != self.size:
            self.size = new_size
            self._cache.clear()
            if hasattr(self, "_dur_cache"):
                self._dur_cache.clear()

    # ---------- 从磁盘加载自定义皮肤 ----------
    def _load_skin_from_disk(self, skin_name: str):
        """目录结构：assets/skins/<skin_name>/<action_name>/<0.png 1.png ...>
        也支持直接放 <action_name>.gif 作为单文件动画。"""
        skin_dir = os.path.join(SKINS_DIR, skin_name)
        if not os.path.isdir(skin_dir):
            return {}
        data = {}
        # 同时记录每个 action 的每帧时长（毫秒），key: action_name → [int, ...]
        dur_data = {}
        supported_exts = (".png", ".jpg", ".jpeg", ".gif", ".webp")
        # 收集所有帧（统一为带alpha策略后的帧）
        def post_process(frames, has_native_transparency: bool):
            """自带有效透明通道的帧保持RGBA传给_fit_frame；无透明的自动抠背景后传RGB。"""
            out = []
            for fr in frames:
                if has_native_transparency and self._has_real_alpha(fr):
                    out.append(self._fit_frame(fr))
                else:
                    fr = self._auto_remove_background(fr)
                    out.append(self._fit_frame(fr))
            return out

        for entry in sorted(os.listdir(skin_dir)):
            full = os.path.join(skin_dir, entry)
            action = os.path.splitext(entry)[0]
            if os.path.isdir(full):
                frames, has_trans, durs = self._load_frames_dir(full, supported_exts)
                if frames:
                    data[action] = post_process(frames, has_trans)
                    dur_data[action] = durs
            elif os.path.isfile(full) and entry.lower().endswith(supported_exts):
                frames, has_trans, durs = self._load_gif_or_image(full)
                if frames:
                    data[action] = post_process(frames, has_trans)
                    dur_data[action] = durs
        # 把时长列表挂到 cache 里（key: (skin_name, action_name)）
        if not hasattr(self, "_dur_cache"):
            self._dur_cache = {}
        for action, durs in dur_data.items():
            self._dur_cache[(skin_name, action)] = durs
        return data

    def _has_real_alpha(self, img: Image.Image):
        """检查图里是否真的存在透明像素（alpha<255）。"""
        try:
            rgba = img.convert("RGBA")
            alpha = rgba.split()[3]
            hist = alpha.histogram()
            # alpha=0 的像素数 > 总像素的 1% 才算真透明
            return hist[0] > (rgba.size[0] * rgba.size[1] // 100)
        except Exception:
            return False

    def _load_frames_dir(self, d, exts):
        files = [f for f in sorted(os.listdir(d)) if f.lower().endswith(exts)]
        frames = []
        durations = []
        any_has_transparency = False
        for f in files:
            try:
                img = Image.open(os.path.join(d, f))
                has_trans = (img.mode == "RGBA" or "transparency" in img.info)
                if has_trans:
                    any_has_transparency = True
                    frames.append(img.convert("RGBA").copy())
                else:
                    frames.append(img.convert("RGB"))
                # 每张图默认 100ms（PNG 序列无法从文件读时长）
                durations.append(int(img.info.get("duration", 100) or 100))
            except Exception:
                pass
        return frames, any_has_transparency, durations

    def _load_gif_or_image(self, path):
        """返回 (帧列表, 是否原生带透明通道, 每帧时长ms列表)。帧保持原始格式，不提前合成。"""
        try:
            img = Image.open(path)
            has_native_trans = (img.mode == "RGBA" or "transparency" in img.info)
            frames_raw = []
            durations = []
            if getattr(img, "is_animated", False):
                for i in range(img.n_frames):
                    img.seek(i)
                    frames_raw.append(img.convert("RGBA" if has_native_trans else "RGB").copy())
                    # GIF 原始帧时长（毫秒），缺省 100ms
                    dur = img.info.get("duration", 100) or 100
                    durations.append(int(dur))
            else:
                frames_raw.append(img.convert("RGBA" if has_native_trans else "RGB"))
                durations.append(100)
            return frames_raw, has_native_trans, durations
        except Exception:
            return [], False, []

    # ---------- 自动抠背景：四角独立采样 + 多参考色判定（支持渐变背景）----------
    def _auto_remove_background(self, img: Image.Image):
        """仅对无透明通道的帧调用。返回 RGB 图（背景已替换为 TRANSPARENT_RGB）。
        对渐变背景友好：四角各自采样，像素离任一角参考色够近就判为背景。"""
        try:
            # 先缩放到目标尺寸附近再抠，省算力也避免大图像素抖动影响采样
            max_side = max(img.size)
            if max_side > self.size * 2:
                scale = (self.size * 2) / max_side
                img = img.resize((max(1, int(img.size[0] * scale)),
                                  max(1, int(img.size[1] * scale))),
                                 Image.LANCZOS)
            rgb = img.convert("RGB")
            w, h = rgb.size
            if w < 4 or h < 4:
                return rgb

            # 四角各取 3x3 patch 的平均色作为该角参考色（4 个独立参考色，支持渐变）
            def sample_color(cx, cy):
                rs, gs, bs = [], [], []
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        x, y = cx + dx, cy + dy
                        if 0 <= x < w and 0 <= y < h:
                            r, g, b = rgb.getpixel((x, y))[:3]
                            rs.append(r); gs.append(g); bs.append(b)
                if not rs:
                    return None
                return (sum(rs)//len(rs), sum(gs)//len(gs), sum(bs)//len(bs))

            # 四角参考色 + 四边中点参考色（共 8 个独立参考点，覆盖线性/径向渐变）
            refs = []
            sample_pts = [
                (1, 1), (w - 2, 1), (1, h - 2), (w - 2, h - 2),
                (w // 2, 1), (w // 2, h - 2), (1, h // 2), (w - 2, h // 2),
            ]
            for (cx, cy) in sample_pts:
                c = sample_color(cx, cy)
                if c:
                    refs.append(c)
            if not refs:
                return rgb

            tol = self.bg_tolerance
            tol_sq = tol * tol

            # 逐像素生成 alpha mask：离任一参考色距离 <= tol 则判为背景
            try:
                import numpy as np
                arr = np.asarray(rgb, dtype=np.int32)
                # 初始 mask：全部不透明（True）
                is_bg = np.zeros((h, w), dtype=bool)
                for ref in refs:
                    dr = arr[:, :, 0] - ref[0]
                    dg = arr[:, :, 1] - ref[1]
                    db = arr[:, :, 2] - ref[2]
                    dist_sq = dr * dr + dg * dg + db * db
                    is_bg |= (dist_sq <= tol_sq)

                # 连通性过滤：只保留和四角种子连通的背景区域。
                # 角色内部的误判背景点被前景包围，不连通到边缘 → 移除，避免"中间虚无"。
                is_bg = self._floodfill_connected(is_bg, w, h)

                alpha = np.where(is_bg, 0, 255).astype(np.uint8)
                rgba = np.concatenate([arr.astype(np.uint8), alpha[:, :, None]], axis=2)
                out_img = Image.fromarray(rgba, mode="RGBA")
            except Exception:
                # 纯 Python 兜底
                out_img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                for y in range(h):
                    for x in range(w):
                        r, g, b = rgb.getpixel((x, y))[:3]
                        is_background = False
                        for ref in refs:
                            d2 = (r - ref[0]) ** 2 + (g - ref[1]) ** 2 + (b - ref[2]) ** 2
                            if d2 <= tol_sq:
                                is_background = True
                                break
                        a = 0 if is_background else 255
                        out_img.putpixel((x, y), (r, g, b, a))

            # 将抠好的 RGBA 合成到色键背景，交给窗口 transparentcolor 统一抠
            final = Image.new("RGB", out_img.size, TRANSPARENT_RGB)
            final.paste(out_img, mask=out_img.split()[3])
            return final
        except Exception as e:
            print(f"[WARN] 抠背景失败：{e}")
            return img.convert("RGB")

    @staticmethod
    def _floodfill_connected(is_bg, w, h):
        """连通性过滤：只保留和四角种子连通的背景区域。
        用 numpy 迭代膨胀实现，比纯 Python BFS 快很多。
        角色内部的误判背景点不连通到边缘 → 被移除，避免"中间虚无"。"""
        import numpy as np
        # 种子：四角中是背景的像素
        seed = np.zeros_like(is_bg)
        seed[0, 0] = is_bg[0, 0]
        seed[0, w - 1] = is_bg[0, w - 1]
        seed[h - 1, 0] = is_bg[h - 1, 0]
        seed[h - 1, w - 1] = is_bg[h - 1, w - 1]
        if not seed.any():
            return is_bg  # 四角都不是背景，跳过过滤

        # 迭代膨胀：每次把"相邻于已连通背景 且 自身是背景"的像素加入
        # 最多迭代 max(w,h)*2 次就能覆盖全图
        connected = seed.copy()
        max_iter = max(w, h) * 2
        for _ in range(max_iter):
            # 四方向膨胀
            dilated = np.zeros_like(connected)
            dilated[1:, :] |= connected[:-1, :]   # 上邻居
            dilated[:-1, :] |= connected[1:, :]    # 下邻居
            dilated[:, 1:] |= connected[:, :-1]    # 左邻居
            dilated[:, :-1] |= connected[:, 1:]    # 右邻居
            new_connected = connected | (dilated & is_bg)
            if np.array_equal(new_connected, connected):
                break  # 收敛
            connected = new_connected
        return connected

    def _fit_frame(self, img: Image.Image):
        """把任意尺寸图片贴到固定画布中心，保持比例缩放+透明背景填充。
        先在RGBA域缩放，再合成到色键背景，避免插值混合污染色键。"""
        # 如果输入已经是RGB（已合成），直接缩放贴入
        if img.mode != "RGBA":
            target = Image.new("RGB", (self.size, self.size), TRANSPARENT_RGB)
            w, h = img.size
            if w <= 0 or h <= 0:
                return target
            scale = min((self.size - 4) / w, (self.size - 4) / h)
            nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
            resized = img.resize((nw, nh), Image.LANCZOS)
            target.paste(resized, ((self.size - nw) // 2, (self.size - nh) // 2))
            return target
        # RGBA：先缩放帧+alpha，再合成到色键背景
        w, h = img.size
        if w <= 0 or h <= 0:
            return Image.new("RGB", (self.size, self.size), TRANSPARENT_RGB)
        scale = min((self.size - 4) / w, (self.size - 4) / h)
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        # 用 NEAREST 缩放 alpha 通道（避免半透明），LANCZOS 缩放 RGB
        rgba = img.convert("RGBA")
        rgb_resized = rgba.convert("RGB").resize((nw, nh), Image.LANCZOS)
        alpha = rgba.split()[3]
        alpha_bin = alpha.point(lambda a: 255 if a > self.alpha_threshold else 0)
        alpha_resized = alpha_bin.resize((nw, nh), Image.NEAREST)

        # 形态学闭运算：膨胀→腐蚀，填补角色内部的小透明点（破洞），同时保持边缘形状
        try:
            import numpy as np
            from PIL import ImageFilter
            # 闭运算：先用最大滤波膨胀（填补破洞），再用最小滤波腐蚀（恢复边缘）
            # 半径 2 像素，能填补大多数零散透明点
            alpha_dilated = alpha_resized.filter(ImageFilter.MaxFilter(3))
            alpha_closed = alpha_dilated.filter(ImageFilter.MinFilter(3))
            alpha_resized = alpha_closed
        except Exception as e:
            print(f"[WARN] alpha 闭运算失败: {e}")

        resized_rgba = Image.merge("RGBA", (*rgb_resized.split(), alpha_resized))
        # 合成前：把角色身上接近色键 (0,1,0) 的暗色像素微调，避免被 transparentcolor 误抠
        # 肉眼几乎看不出差异（纯黑→极暗灰），但能避开色键精确匹配
        try:
            import numpy as np
            arr_rgb = np.asarray(rgb_resized, dtype=np.int32)
            # 判定条件：R<8 且 G<8 且 B<8（覆盖纯黑和极暗色）
            is_dark = (arr_rgb[:, :, 0] < 8) & (arr_rgb[:, :, 1] < 8) & (arr_rgb[:, :, 2] < 8)
            if is_dark.any():
                # 把暗色像素的 G 通道 +8（从 0/1 → 8/9），远离色键 (0,1,0)
                arr_rgb[is_dark, 1] = np.minimum(255, arr_rgb[is_dark, 1] + 8)
                rgb_resized = Image.fromarray(arr_rgb.astype(np.uint8), mode="RGB")
                resized_rgba = Image.merge("RGBA", (*rgb_resized.split(), alpha_resized))
        except Exception as e:
            print(f"[WARN] 暗色像素微调失败: {e}")
        # 合成到色键背景
        target = Image.new("RGB", (self.size, self.size), TRANSPARENT_RGB)
        target.paste(resized_rgba, ((self.size - nw) // 2, (self.size - nh) // 2),
                     mask=resized_rgba.split()[3])
        return target


# ============================================================
# 桌宠主窗口
# ============================================================
class PetApp:
    def __init__(self):
        self.cfg = load_config()
        self.skin_mgr = SkinManager(
            self.cfg["pet_size"],
            bg_tolerance=self.cfg.get("bg_tolerance", 30),
            alpha_threshold=self.cfg.get("alpha_threshold", 128),
        )

        # Tk 根窗口
        self.root = tk.Tk()
        self.root.title("Pet")
        self.root.overrideredirect(True)        # 无边框
        self.root.attributes("-topmost", True)
        # Windows 透明色
        try:
            self.root.attributes("-transparentcolor", TRANSPARENT_COLOR)
            self.win_transparent_ok = True
        except tk.TclError:
            self.win_transparent_ok = False
            self.root.configure(bg=TRANSPARENT_COLOR)
        # macOS/Linux 下备用（-alpha 整体透明，效果不如 transparentcolor，但能用）
        if not self.win_transparent_ok:
            try:
                self.root.attributes("-alpha", 0.95)
            except Exception:
                pass

        # Windows 下用 API 强制置顶（Tkinter 的 -topmost 不可靠）
        self._topmost_hwnd = None
        if sys.platform.startswith("win"):
            self._setup_win_topmost()

        # 屏幕尺寸（用于复位位置）
        self.screen_w = self.root.winfo_screenwidth()
        self.screen_h = self.root.winfo_screenheight()
        self.taskbar_y = self.screen_h - TASKBAR_PADDING

        # 初始位置
        wp = self.cfg.get("window_pos", [200, 400])
        self.win_x, self.win_y = int(wp[0]), int(wp[1])
        self._set_geometry()

        # 宠物显示控件
        self.label = tk.Label(
            self.root,
            bg=TRANSPARENT_COLOR,
            bd=0,
            highlightthickness=0,
        )
        self.label.pack(fill="both", expand=True)
        # 确保 label 引用挂到 root，防 PhotoImage GC 丢失
        self.root.pet_label = self.label

        # 动作状态
        self.cur_action = self.cfg["actions"].get("idle", "idle")
        self.action_timer_until = 0  # 临时动作到期时间戳（ms）
        self.frame_index = 0
        self._action_frame_cache = {}  # (skin,action,size) -> [PhotoImage]

        # 拖拽相关
        self.dragging = False
        self.drag_start_mouse = (0, 0)
        self.drag_start_win = (0, 0)

        # 绑定事件
        self.label.bind("<ButtonPress-1>", self._on_left_press)
        self.label.bind("<B1-Motion>", self._on_left_drag)
        self.label.bind("<ButtonRelease-1>", self._on_left_release)
        self.label.bind("<Double-Button-1>", self._on_left_double)
        self.label.bind("<Enter>", self._on_hover_enter)
        self.label.bind("<Leave>", self._on_hover_leave)
        # 右键
        self.label.bind("<Button-3>", self._on_right_click)       # Windows/Linux
        self.label.bind("<Button-2>", self._on_right_click)       # macOS
        # 全局右键菜单（窗口背景也能弹）
        self.root.bind("<Button-3>", self._on_right_click)
        self.root.bind("<Button-2>", self._on_right_click)

        # 右键菜单对象
        self.ctx_menu = tk.Menu(self.root, tearoff=0)
        self._build_context_menu()

        # 启动动画循环
        self.root.after(50, self._tick)

        # 关闭事件：保存位置
        self.root.protocol("WM_DELETE_WINDOW", self.on_quit)

    # ---------- Windows 强制置顶 ----------
    def _setup_win_topmost(self):
        """获取真实 HWND 并设置 WS_EX_TOPMOST + SetWindowPos 永久置顶。"""
        try:
            import ctypes
            from ctypes import wintypes

            # 声明函数签名（64位安全）
            user32 = ctypes.windll.user32
            user32.GetParent.argtypes = [wintypes.HWND]
            user32.GetParent.restype = wintypes.HWND
            user32.SetWindowPos.argtypes = [
                wintypes.HWND, wintypes.HWND,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                ctypes.c_uint,
            ]
            user32.SetWindowPos.restype = wintypes.BOOL
            user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]

            self.root.update_idletasks()
            # 尝试获取真正的顶层窗口句柄：
            # Tkinter 的 winfo_id() 有时返回子窗口，GetParent 能拿到真实 HWND；
            # 但根窗口本身没有父，GetParent 返回 0，这时直接用 winfo_id()。
            raw = self.root.winfo_id()
            hwnd = user32.GetParent(raw)
            if not hwnd:
                hwnd = raw
            if not hwnd:
                print("[WARN] 无法获取窗口句柄，置顶失败")
                return

            self._topmost_hwnd = hwnd

            # 1) 设置 WS_EX_TOPMOST 扩展样式（系统级永久置顶）
            GWL_EXSTYLE = -20
            WS_EX_TOPMOST = 0x00000008
            ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style | WS_EX_TOPMOST)

            # 2) 立即应用 SetWindowPos
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
            user32.SetWindowPos(hwnd, wintypes.HWND(-1), 0, 0, 0, 0, flags)
        except Exception as e:
            print(f"[WARN] 设置置顶失败: {e}")

    def _reassert_topmost(self):
        """周期性重新断言置顶（被其他窗口抢前后调用）。
        降频：每 ~2 秒一次即可，避免每帧 150ms 调一次系统 API。"""
        if not self._topmost_hwnd:
            return
        now = int(time.time())
        if now - getattr(self, "_last_topmost_assert", 0) < 2:
            return
        self._last_topmost_assert = now
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOACTIVATE = 0x0010
            flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
            user32.SetWindowPos(self._topmost_hwnd, wintypes.HWND(-1),
                                0, 0, 0, 0, flags)
        except Exception:
            pass

    # ---------- 几何 ----------
    def _set_geometry(self):
        size = self.cfg["pet_size"]
        # 限制不越屏
        self.win_x = max(0, min(self.screen_w - size, self.win_x))
        self.win_y = max(0, min(self.screen_h - size, self.win_y))
        self.root.geometry(f"{size}x{size}+{self.win_x}+{self.win_y}")

    # ---------- 动作与帧 ----------
    def _get_current_tk_frames(self):
        skin = self.cfg["skin"]
        action = self.cur_action
        key = (skin, action, self.cfg["pet_size"])
        if key in self._action_frame_cache:
            return self._action_frame_cache[key]
        pil_frames = self.skin_mgr.get_frames(skin, action)
        # ============== DEBUG：如果帧来源是回退的 idle 而非 action 自身，打印日志 ==============
        if not pil_frames:
            # 完全没帧（极端情况）
            print(f"[DEBUG] 动作无帧: {action}, skin={skin}")
        else:
            # 间接判断：动作不是 idle 但帧数量等于 idle 的帧数量，且 skin 缓存里 action 本身没数据 → 说明是回退
            sm = self.skin_mgr
            skin_data = sm._cache.get(skin, {})
            if action != "idle" and action not in skin_data:
                print(f"[DEBUG] {action}.gif 不存在，帧回退到了 idle（cur_action={action} 但显示 idle.gif）")
        # ====================================================================================
        tk_frames = [ImageTk.PhotoImage(img) for img in pil_frames]
        self._action_frame_cache[key] = tk_frames
        return tk_frames

    def _set_action(self, action_name, duration_ms=None):
        """设置动作。duration_ms 为临时时长（毫秒），到期自动回到 idle。
        duration_ms=None 表示无时限（持续到下次切换），必须强制清零计时器。"""
        # duration_ms=None 时：无论是否同动作，都要清零计时器（否则之前的临时计时会切走当前动作）
        if duration_ms is None:
            if action_name == self.cur_action and not self.action_timer_until:
                return  # 同动作且无计时器，确实无需操作
            self.cur_action = action_name
            self.frame_index = 0
            self.action_timer_until = 0
            return
        # duration_ms 有值：正常设置临时动作
        if action_name == self.cur_action and self.action_timer_until:
            # 同动作且已有计时器：只刷新时长
            self.action_timer_until = self._now_ms() + duration_ms
            return
        self.cur_action = action_name
        self.frame_index = 0
        self.action_timer_until = self._now_ms() + duration_ms

    def _restore_idle_if_due(self):
        now = self._now_ms()
        if self.action_timer_until and now >= self.action_timer_until:
            # 防御：拖拽期间绝不允许自动切回 idle（否则长按会闪回待机）
            if self.dragging:
                self.action_timer_until = 0
                return
            self.action_timer_until = 0
            self.cur_action = self.cfg["actions"].get("idle", "idle")
            self.frame_index = 0

    @staticmethod
    def _now_ms():
        return int(time.time() * 1000)

    # ---------- 主循环 ----------
    def _tick(self):
        # 默认间隔（兜底，GIF 没读到时长时用）
        interval = max(20, int(self.cfg.get("frame_interval_ms", 100)))

        # ============== 拖拽强制锁：每帧锁死 drag 动作，绝不允许被任何代码偷改 ==============
        if self.dragging:
            drag_act = self.cfg["actions"].get("drag", "drag")
            if self.cur_action != drag_act:
                # 被偷偷改了！记录来源并强行改回
                print(f"[DEBUG] 拖拽期间动作被偷改: {self.cur_action} → 强制恢复为 {drag_act}")
                self.cur_action = drag_act
                self.action_timer_until = 0
                self.frame_index = 0
        # ====================================================================================

        # 动作到期回 idle
        self._restore_idle_if_due()

        # 周期性强制置顶（Windows 下 -topmost 会丢）
        self._reassert_topmost()

        # 渲染一帧
        try:
            frames = self._get_current_tk_frames()
            if frames:
                if self.frame_index >= len(frames):
                    self.frame_index = 0
                # 把 PhotoImage 存到 label，避免被 GC
                self.label._current_img = frames[self.frame_index]
                self.label.configure(image=frames[self.frame_index])
                # 用 GIF 原始帧时长调度下一帧（让动画按作者设计播放）
                skin = self.cfg["skin"]
                action = self.cur_action
                durs = self.skin_mgr.get_frame_durations(skin, action, len(frames))
                if durs:
                    # 当前帧的时长，下限 20ms 避免卡死
                    cur_dur = durs[self.frame_index] if self.frame_index < len(durs) else durs[-1]
                    interval = max(20, int(cur_dur))
                self.frame_index += 1
        except Exception as e:
            print(f"[WARN] render: {e}")

        self.root.after(interval, self._tick)

    # ---------- 鼠标事件 ----------
    def _on_left_press(self, ev):
        # 开始拖拽：直接切到 drag 动作，无时限
        self.dragging = True
        self.drag_start_mouse = (ev.x_root, ev.y_root)
        self.drag_start_win = (self.win_x, self.win_y)
        drag_act = self.cfg["actions"].get("drag", "drag")
        # duration_ms=None 强制清零计时器，保证拖拽期间不会被切走
        self._set_action(drag_act, duration_ms=None)

    def _on_left_drag(self, ev):
        if not self.dragging:
            return
        mx, my = ev.x_root, ev.y_root
        dx = mx - self.drag_start_mouse[0]
        dy = my - self.drag_start_mouse[1]
        self.win_x = self.drag_start_win[0] + dx
        self.win_y = self.drag_start_win[1] + dy
        self._set_geometry()

    def _on_left_release(self, ev):
        if self.dragging:
            self.dragging = False
            # 松手回到 idle
            self._set_action(self.cfg["actions"].get("idle", "idle"))

    def _on_left_double(self, ev):
        # 双击：先结束拖拽状态（双击前会先触发两次 press/release）
        if self.dragging:
            self.dragging = False
        act = self.cfg["actions"].get("left_double", "play")
        # 双击动作持续 10 秒
        self._set_action(act, duration_ms=10000)

    def _on_hover_enter(self, ev):
        # 有计时中的临时动作（双击/跳舞等）时不打断
        if self.action_timer_until:
            return
        act = self.cfg["actions"].get("hover")
        if act and act != self.cfg["actions"].get("idle", "idle"):
            self._set_action(act, duration_ms=500)

    def _on_hover_leave(self, ev):
        # 拖拽中 / 有计时中的临时动作 → 不打断
        if self.dragging or self.action_timer_until:
            return
        self._set_action(self.cfg["actions"].get("idle", "idle"))

    def _on_right_click(self, ev):
        # 触发"被右键"动作
        act = self.cfg["actions"].get("right_click", "curious")
        self._set_action(act, duration_ms=700)
        # 弹菜单
        try:
            self.ctx_menu.tk_popup(ev.x_root, ev.y_root)
        finally:
            self.ctx_menu.grab_release()

    # ---------- 右键菜单 ----------
    def _build_context_menu(self):
        m = self.ctx_menu
        m.delete(0, tk.END)
        m.add_command(label="🔧 设置", command=self._safe_open_settings)
        m.add_separator()
        # 快速切换皮肤子菜单
        sub = tk.Menu(m, tearoff=0)
        try:
            skins = self.skin_mgr.list_skins()
        except Exception:
            skins = [self.cfg.get("skin", "default")]
        for skin in skins:
            mark = "✓ " if skin == self.cfg["skin"] else "  "
            sub.add_command(label=mark + skin,
                            command=lambda s=skin: self.switch_skin(s))
        m.add_cascade(label="🎨 切换皮肤", menu=sub)
        m.add_separator()
        m.add_command(label="💃 跳舞(10秒)", command=self.manual_dance)
        m.add_command(label="📌 复位位置", command=self.reset_position)
        m.add_separator()
        # 开机自启开关（boot_var 挂到 self，避免 GC 后开关状态错乱）
        self._autostart_var = tk.BooleanVar(value=self._is_autostart_enabled())
        m.add_checkbutton(label="🚀 开机自启", variable=self._autostart_var,
                          command=lambda: self.toggle_autostart(self._autostart_var))
        m.add_separator()
        m.add_command(label="❌ 退出", command=self.on_quit)

    def _safe_open_settings(self):
        try:
            # 先关闭右键菜单（否则会浮在设置窗口上面）
            try:
                self.ctx_menu.unpost()
            except Exception:
                pass
            self.open_settings()
        except Exception as e:
            print(f"[WARN] 打开设置失败: {e}")
            try:
                from tkinter import messagebox
                messagebox.showerror("打开设置失败", str(e))
            except Exception:
                pass

    # ---------- 菜单操作 ----------
    def switch_skin(self, skin_name):
        try:
            self.cfg["skin"] = skin_name
            self.skin_mgr.reload()
            save_config(self.cfg)
            self._rebuild_menu_and_refresh()
        except Exception as e:
            print(f"[WARN] 切换皮肤失败: {e}")
            try:
                from tkinter import messagebox
                messagebox.showerror("切换皮肤失败", str(e))
            except Exception:
                pass

    # （旧 toggle_topmost 方法已移除：置顶始终开启，不暴露开关）
    def toggle_topmost(self, var):
        """保留的占位方法，兼容历史调用。置顶始终开启。"""
        return

    # ---------- 开机自启 ----------
    def _get_autostart_path(self):
        """返回自启快捷方式路径（Windows用注册表，其他平台用文件路径）"""
        if sys.platform.startswith("win"):
            import winreg
            return ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Run", "DesktopPet")
        elif sys.platform == "darwin":
            return os.path.expanduser("~/Library/LaunchAgents/com.desktoppet.plist")
        else:
            return os.path.expanduser("~/.config/autostart/desktoppet.desktop")

    def _is_autostart_enabled(self):
        try:
            if sys.platform.startswith("win"):
                import winreg
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Run",
                    0, winreg.KEY_READ)
                try:
                    winreg.QueryValueEx(key, "DesktopPet")
                    winreg.CloseKey(key)
                    return True
                except FileNotFoundError:
                    winreg.CloseKey(key)
                    return False
            elif sys.platform == "darwin":
                return os.path.exists(self._get_autostart_path())
            else:
                return os.path.exists(self._get_autostart_path())
        except Exception:
            return False

    def _build_autostart_command(self):
        """返回自启命令行（区分 PyInstaller 打包态和源码态）。"""
        if getattr(sys, 'frozen', False):
            # 打包成 EXE：直接指向 EXE 本体
            exe = sys.executable
            return f'"{exe}"'
        else:
            # 源码态：pythonw main.py（无黑框）
            exe_dir = os.path.dirname(sys.executable)
            pythonw = os.path.join(exe_dir, "pythonw.exe")
            if os.path.exists(pythonw):
                exe = pythonw
            else:
                exe = sys.executable
            script = os.path.join(BASE_DIR, "main.py")
            return f'"{exe}" "{script}"'

    def toggle_autostart(self, var):
        try:
            enable = bool(var.get())
        except Exception:
            enable = True
        try:
            if sys.platform.startswith("win"):
                import winreg
                key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
                if enable:
                    cmd = self._build_autostart_command()
                    key = winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
                    winreg.SetValueEx(key, "DesktopPet", 0, winreg.REG_SZ, cmd)
                    winreg.CloseKey(key)
                else:
                    key = winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
                    try:
                        winreg.DeleteValue(key, "DesktopPet")
                    except FileNotFoundError:
                        pass
                    winreg.CloseKey(key)
            elif sys.platform == "darwin":
                path = self._get_autostart_path()
                if enable:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    cmd_parts = []
                    if getattr(sys, 'frozen', False):
                        cmd_parts = [sys.executable]
                    else:
                        cmd_parts = [sys.executable,
                                     os.path.join(BASE_DIR, "main.py")]
                    arr = "".join(f"        <string>{s}</string>\n" for s in cmd_parts)
                    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>com.desktoppet</string>
    <key>ProgramArguments</key>
    <array>
{arr}</array>
    <key>RunAtLoad</key><true/>
</dict>
</plist>"""
                    with open(path, "w") as f:
                        f.write(plist)
                else:
                    if os.path.exists(path):
                        os.remove(path)
            else:
                path = self._get_autostart_path()
                if enable:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    if getattr(sys, 'frozen', False):
                        exec_line = sys.executable
                    else:
                        exec_line = f'{sys.executable} "{os.path.join(BASE_DIR, "main.py")}"'
                    desktop = f"""[Desktop Entry]
Type=Application
Name=DesktopPet
Exec={exec_line}
Terminal=false
X-GNOME-Autostart-enabled=true
"""
                    with open(path, "w") as f:
                        f.write(desktop)
                else:
                    if os.path.exists(path):
                        os.remove(path)
        except Exception as e:
            print(f"[WARN] 开机自启设置失败: {e}")
            try:
                from tkinter import messagebox
                messagebox.showerror("开机自启设置失败", str(e))
            except Exception:
                pass

    def reset_position(self):
        try:
            self.win_x = int(self.screen_w * 0.15)
            self.win_y = self.taskbar_y - self.cfg["pet_size"]
            self._set_geometry()
            self.cfg["window_pos"] = [self.win_x, self.win_y]
            save_config(self.cfg)
        except Exception as e:
            print(f"[WARN] 复位位置失败: {e}")

    def manual_dance(self):
        """手动跳舞：持续 10 秒后自动回到 idle。"""
        try:
            # 先关闭右键菜单
            try:
                self.ctx_menu.unpost()
            except Exception:
                pass
            self._set_action("play", duration_ms=10000)
        except Exception as e:
            print(f"[WARN] 跳舞失败: {e}")

    def _rebuild_menu_and_refresh(self):
        self._action_frame_cache.clear()
        self._build_context_menu()
        self._set_action(self.cfg["actions"].get("idle", "idle"))

    # ---------- 设置面板 ----------
    def open_settings(self):
        SettingsWindow(self)

    # ---------- 生命周期 ----------
    def on_quit(self):
        self.cfg["window_pos"] = [self.win_x, self.win_y]
        save_config(self.cfg)
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.mainloop()


# ============================================================
# 设置面板窗口
# ============================================================
class SettingsWindow:
    def __init__(self, app: PetApp):
        self.app = app
        self.win = tk.Toplevel(app.root)
        self.win.title("桌宠设置")
        self.win.attributes("-topmost", True)
        self.win.resizable(False, False)
        pad = {"padx": 10, "pady": 5}

        try:
            self.tmp = json.loads(json.dumps(app.cfg))
        except Exception:
            self.tmp = json.loads(json.dumps(DEFAULT_CONFIG))
        row = 0

        # --- 皮肤 ---
        ttk.Label(self.win, text="🎨 皮肤").grid(row=row, column=0, sticky="w", **pad)
        self.skin_var = tk.StringVar(value=self.tmp["skin"])
        try:
            skin_list = app.skin_mgr.list_skins()
        except Exception:
            skin_list = [self.tmp.get("skin", "default")]
        ttk.Combobox(self.win, textvariable=self.skin_var, state="readonly",
                     values=skin_list, width=16).grid(
            row=row, column=1, sticky="we", **pad)
        row += 1

        # --- 大小（带实时数值显示）---
        ttk.Label(self.win, text="📐 大小").grid(row=row, column=0, sticky="w", **pad)
        self.size_var = tk.IntVar(value=self.tmp["pet_size"])
        size_frame = ttk.Frame(self.win)
        size_frame.grid(row=row, column=1, sticky="we", **pad)
        scale = ttk.Scale(size_frame, from_=64, to=384, orient="horizontal",
                          variable=self.size_var, length=140)
        scale.pack(side="left")
        self.size_label_var = tk.StringVar(value=str(self.tmp["pet_size"]))
        ttk.Label(size_frame, textvariable=self.size_label_var, width=6,
                  anchor="e").pack(side="left", padx=(4, 0))
        self.size_var.trace_add("write",
                                lambda *a: self.size_label_var.set(str(int(self.size_var.get()))))
        row += 1

        ttk.Separator(self.win, orient="horizontal").grid(
            row=row, column=0, columnspan=2, sticky="we", pady=4)
        row += 1

        # --- 动作绑定 ---
        ttk.Label(self.win, text="⚙️ 动作绑定",
                  font=("", 10, "bold")).grid(row=row, column=0, columnspan=2, sticky="w", **pad)
        row += 1

        event_meta = [
            ("idle", "待机"),
            ("left_click", "左键单击"),
            ("left_double", "左键双击"),
            ("drag", "拖动时"),
            ("hover", "悬停"),
            ("right_click", "右键点击"),
        ]
        self.action_vars = {}
        for ev_key, ev_desc in event_meta:
            ttk.Label(self.win, text=ev_desc, width=10).grid(
                row=row, column=0, sticky="w", **pad)
            v = tk.StringVar(value=self.tmp["actions"].get(ev_key, "idle"))
            ttk.Combobox(self.win, textvariable=v, state="readonly",
                         values=AVAILABLE_ACTIONS, width=16).grid(
                row=row, column=1, sticky="we", **pad)
            self.action_vars[ev_key] = v
            row += 1

        # --- 按钮 ---
        ttk.Button(self.win, text="✅ 应用",
                   command=self.apply_and_save).grid(
            row=row, column=0, columnspan=2, pady=(8, 12))

    def apply_and_save(self):
        try:
            a = self.app
            old_skin = a.cfg["skin"]
            a.cfg["skin"] = self.skin_var.get() or "default"
            new_size = int(self.size_var.get())
            if a.cfg["pet_size"] != new_size:
                a.cfg["pet_size"] = new_size
                a.skin_mgr.set_size(new_size)
                a._set_geometry()
            if old_skin != a.cfg["skin"]:
                a.skin_mgr.reload()
            a.cfg["actions"] = {k: v.get() for k, v in self.action_vars.items()}
            a._action_frame_cache.clear()
            a._build_context_menu()
            a._set_action(a.cfg["actions"].get("idle", "idle"))
            save_config(a.cfg)
        except Exception as e:
            print(f"[WARN] 应用设置失败: {e}")
            try:
                from tkinter import messagebox
                messagebox.showerror("应用设置失败", str(e))
            except Exception:
                pass
        try:
            self.win.destroy()
        except Exception:
            pass


# ============================================================
# 入口
# ============================================================
def main():
    # 依赖检查
    try:
        import PIL  # noqa: F401
    except ImportError:
        print("=" * 50)
        print("❌ 缺少依赖 Pillow，请先运行：")
        print("   pip install pillow")
        print("   或：pip install -r requirements.txt")
        print("=" * 50)
        sys.exit(1)
    os.chdir(BASE_DIR)
    PetApp().run()


if __name__ == "__main__":
    main()
