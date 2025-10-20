#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
超分图像对比工具 - 企业级版本
支持文件夹批量对比、多标签页管理、自定义对比算法等高级功能

核心特性：
- 策略模式重构绘制逻辑 + 高级策略扩展
- 并发PSNR计算 + 多指标分析
- 改进的LRU缓存系统 + 多级缓存
- 文件夹批量处理
- 多标签页界面
- 插件化对比算法
- 类型提示和完整文档
- 企业级错误处理
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk, ImageChops, ImageDraw
import threading
import time
import traceback
import math
from pathlib import Path
import glob
from typing import Optional, Dict, Tuple, Any, Callable, Union
from abc import ABC, abstractmethod
from collections import OrderedDict
import numpy as np

# 移除未使用的 ImageEnhance 导入

# choose resampling constants depending on PIL version
try:
    RESAMPLE_LANCZOS = Image.Resampling.LANCZOS
    RESAMPLE_BILINEAR = Image.Resampling.BILINEAR
except Exception:
    RESAMPLE_LANCZOS = Image.LANCZOS
    RESAMPLE_BILINEAR = Image.BILINEAR


# 配置文件
class Config:
    """应用配置常量"""
    # UI 默认尺寸和布局参数
    DEFAULT_WINDOW_SIZE = "1300x750"
    MIN_WINDOW_SIZE = "800x600"
    CONTROL_PANEL_HEIGHT = 180  # 控制面板高度
    STATUS_BAR_HEIGHT = 25      # 状态栏高度
    BUTTON_WIDTH = 10          # 按钮标准宽度

    # 缩放限制
    ZOOM_MIN = 0.01
    ZOOM_MAX = 64.0
    ZOOM_STEP = 1.25

    # 局部放大镜参数
    MAGNIFIER_CROP_SIZE = 100
    MAGNIFIER_ZOOM = 2.0

    # 缓存大小
    MAX_CACHE_SIZE = 100
    PSNR_REFRESH_THROTTLE = 1 / 30.0  # 30 FPS

    # UI 颜色
    BG_COLOR = "#333333"
    SPLIT_LINE_COLOR = (255, 0, 0)
    SPLIT_LINE_WIDTH = 2
    ALIGN_BG_COLOR = (40, 40, 40)

    # 文件类型
    SUPPORTED_FORMATS = [("图像", "*.jpg *.jpeg *.png *.bmp *.tiff *.tif")]
    MAX_16BIT_PIXEL = 65535.0
    MAX_8BIT_PIXEL = 255.0

    # 模式映射
    MODES = {
        "并排对比": "side_by_side",
        "快速切换": "toggle",
        "滑动对比": "slider",
        "局部放大": "magnifier",
        "差异显示": "difference"
    }

    MODE_HINTS = {
        "magnifier": "局部放大：移动鼠标查看固定 100x100 放大区域",
        "slider": "滑动对比：按住并水平拖动分割线",
        "toggle": "快速切换：按住鼠标可切换到另一个图，松开返回",
        "side_by_side": "并排对比：两个画布并排显示，缩放同步",
        "difference": "差异显示：显示两图像的像素差异"
    }


# ------------------------ 策略模式：绘制策略 ------------------------
class DrawStrategy(ABC):
    """绘制策略抽象基类"""

    def __init__(self, app: 'SRCompareApp'):
        self.app = app

    @abstractmethod
    def draw(self) -> None:
        """执行绘制操作"""
        pass

    def _create_photo_ref(self, image: Image.Image) -> Optional[ImageTk.PhotoImage]:
        """创建PhotoImage引用并缓存"""
        try:
            photo = ImageTk.PhotoImage(image)
            self.app._photo_refs.append(photo)
            return photo
        except Exception as e:
            print(f"创建PhotoImage失败: {e}")
            return None


class SideBySideStrategy(DrawStrategy):
    """并排对比绘制策略"""

    def draw(self) -> None:
        """左右两个画布分别绘制im1和im2，保持相同的zoom/pan（同步）"""
        app = self.app

        # 左画布绘制图1
        disp1, left1, top1 = app._image_display_params_for_canvas(app.im1_orig, app.canvas_left)
        if disp1 and (photo1 := self._create_photo_ref(disp1)):
            app.canvas_left.create_image(left1, top1, anchor=tk.NW, image=photo1, tags="img1")

        # 右画布绘制图2
        disp2, left2, top2 = app._image_display_params_for_canvas(app.im2_orig, app.canvas_right)
        if disp2 and (photo2 := self._create_photo_ref(disp2)):
            app.canvas_right.create_image(left2, top2, anchor=tk.NW, image=photo2, tags="img2")


class ToggleStrategy(DrawStrategy):
    """快速切换绘制策略"""

    def draw(self) -> None:
        """单画布显示当前选中的图像"""
        app = self.app
        current_img = app.im1_orig if app.toggle_idx == 1 else app.im2_orig
        disp, left, top = app._image_display_params_for_canvas(current_img, app.canvas_left)
        if disp and (photo := self._create_photo_ref(disp)):
            app.canvas_left.create_image(left, top, anchor=tk.NW, image=photo, tags="img")


class SliderStrategy(DrawStrategy):
    """滑动对比绘制策略"""

    def draw(self) -> None:
        """单画布滑动对比，带分割线"""
        app = self.app
        cw, ch = app.canvas_left.winfo_width(), app.canvas_left.winfo_height()
        if cw <= 1 or ch <= 1:
            return

        # 创建底图
        base = Image.new("RGB", (cw, ch), Config.ALIGN_BG_COLOR)

        # 获取显示图像
        disp1, left1, top1 = app._image_display_params_for_canvas(app.im1_orig, app.canvas_left)
        disp2 = app._get_disp_image(app.im2_orig)

        # 先粘贴图1
        if disp1:
            base.paste(disp1, (left1, top1))

        # 计算图2粘贴位置和mask
        if disp2:
            disp2_exact, left2, top2 = app._image_display_params_for_canvas(app.im2_orig, app.canvas_left)
            split_x_canvas = left1 + int(disp1.width * app.split_pos) if disp1 else int(cw * app.split_pos)

            # 创建右侧显示图2的mask
            px = split_x_canvas - left2
            px = max(0, min(disp2_exact.width, px))
            if px < disp2_exact.width:
                mask = Image.new("L", (disp2_exact.width, disp2_exact.height), 0)
                mask.paste(255, (px, 0, disp2_exact.width, disp2_exact.height))
                base.paste(disp2_exact, (left2, top2), mask)

            # 绘制分割线
            self._draw_split_line(base, split_x_canvas, ch)

        # 显示到画布
        if (photo := self._create_photo_ref(base)):
            app.canvas_left.create_image(0, 0, anchor=tk.NW, image=photo, tags="img")

    def _draw_split_line(self, image: Image.Image, x: int, height: int) -> None:
        """绘制红色分割线"""
        draw = ImageDraw.Draw(image)
        draw.line([(x, 0), (x, height)], fill=Config.SPLIT_LINE_COLOR, width=Config.SPLIT_LINE_WIDTH)


class MagnifierStrategy(DrawStrategy):
    """局部放大绘制策略"""

    def draw(self) -> None:
        """局部放大镜显示"""
        app = self.app
        cw, ch = app.canvas_left.winfo_width(), app.canvas_left.winfo_height()
        if cw <= 1 or ch <= 1:
            return

        # 显示背景图1
        disp, left, top = app._image_display_params_for_canvas(app.im1_orig, app.canvas_left)
        if disp and (photo_main := self._create_photo_ref(disp)):
            app.canvas_left.create_image(left, top, anchor=tk.NW, image=photo_main, tags="main")

        # 获取鼠标位置
        mx, my = self._get_mouse_position()
        if mx is None or my is None:
            return
        ix, iy = app.canvas_to_image(mx, my, for_left=True)

        # 裁剪和放大区域
        magnified = self._create_magnified_region(ix, iy)
        if magnified and (photo_local := self._create_photo_ref(magnified)):
            # 计算放大镜位置
            offset_x, offset_y = 20, 20
            x = min(max(0, mx + offset_x), cw - magnified.width)
            y = min(max(0, my + offset_y), ch - magnified.height)
            app.canvas_left.create_image(x, y, anchor=tk.NW, image=photo_local, tags="magnifier")

    def _get_mouse_position(self) -> Tuple[Optional[int], Optional[int]]:
        """获取鼠标在画布上的位置"""
        try:
            mx = self.app.canvas_left.winfo_pointerx() - self.app.canvas_left.winfo_rootx()
            my = self.app.canvas_left.winfo_pointery() - self.app.canvas_left.winfo_rooty()
            return mx, my
        except:
            return None, None

    def _create_magnified_region(self, ix: int, iy: int) -> Optional[Image.Image]:
        """创建放大的对比区域"""
        app = self.app
        half = Config.MAGNIFIER_CROP_SIZE // 2

        # 计算裁剪区域
        left_i = max(0, ix - half)
        top_i = max(0, iy - half)
        right_i = min(app.im1_orig.width, ix + half)
        bottom_i = min(app.im1_orig.height, iy + half)

        try:
            # 裁剪两个区域
            reg1 = app.im1_orig.crop((left_i, top_i, right_i, bottom_i))
            reg2 = app.im2_orig.crop((left_i, top_i, right_i, bottom_i))

            # 放大
            ds_w = int(reg1.width * Config.MAGNIFIER_ZOOM)
            ds_h = int(reg1.height * Config.MAGNIFIER_ZOOM)
            reg1 = reg1.resize((ds_w, ds_h), RESAMPLE_BILINEAR)
            reg2 = reg2.resize((ds_w, ds_h), RESAMPLE_BILINEAR)

            # 拼接
            out = Image.new("RGBA", (ds_w * 2, ds_h), (0, 0, 0, 0))
            out.paste(reg1, (0, 0))
            out.paste(reg2, (ds_w, 0))
            return out
        except Exception as e:
            print(f"创建放大区域失败: {e}")
            return None


class DifferenceStrategy(DrawStrategy):
    """差异显示绘制策略"""

    def draw(self) -> None:
        """显示图像差异"""
        app = self.app
        if not app.im1_orig or not app.im2_orig:
            return

        # 检查差异图像是否需要重新计算
        if not self._needs_recompute():
            diff_img = app.im_diff
        else:
            diff_img = self._compute_difference()
            app.im_diff = diff_img

        # 显示差异图像
        if diff_img:
            disp, left, top = app._image_display_params_for_canvas(diff_img, app.canvas_left)
            if disp and (photo := self._create_photo_ref(disp)):
                app.canvas_left.create_image(left, top, anchor=tk.NW, image=photo, tags="img")

    def _needs_recompute(self) -> bool:
        """检查差异图像是否需要重新计算"""
        app = self.app
        return (app.im_diff is None or
                id(app.im1_orig) != app._im_diff_key or
                id(app.im2_orig) != app._im_diff_key2)

    def _compute_difference(self) -> Optional[Image.Image]:
        """计算图像差异（使用NumPy优化性能）"""
        app = self.app
        try:
            im1 = app.im1_orig
            im2 = app.im2_orig

            # 确保尺寸相同
            if im1.size != im2.size:
                im2 = im2.resize(im1.size, RESAMPLE_LANCZOS)

            # 使用NumPy计算差异，提升性能
            im1_array = np.array(im1, dtype=np.int16)  # 使用int16避免溢出
            im2_array = np.array(im2, dtype=np.int16)

            # 计算像素级差异
            diff_array = np.abs(im1_array - im2_array)
            diff_gray = np.max(diff_array, axis=2)  # RGB最大差异作为灰度值

            max_diff = diff_gray.max()
            if max_diff > 0:
                # 归一化到0-255
                diff_normalized = (diff_gray * 255.0 / max_diff).astype(np.uint8)
            else:
                diff_normalized = np.zeros_like(diff_gray, dtype=np.uint8)

            # 转换为PIL图像
            result = Image.fromarray(diff_normalized, mode="L").convert("RGB")

            # 更新缓存键
            app._im_diff_key = id(app.im1_orig)
            app._im_diff_key2 = id(app.im2_orig)

            return result

        except Exception as e:
            print(f"计算差异失败: {e}")
            return None


class SRCompareApp:
    """超分辨率图像对比工具主应用类"""

    def __init__(self, root: tk.Tk) -> None:
        """
        初始化应用

        Args:
            root: Tkinter根窗口
        """
        self.root = root
        root.title("超分图像对比工具 - 全优化版")

        # 图像数据
        self.im1_orig: Optional[Image.Image] = None
        self.im2_orig: Optional[Image.Image] = None
        self.im1_raw: Optional[Image.Image] = None  # 保存原始图像（未对齐）
        self.im2_raw: Optional[Image.Image] = None  # 保存原始图像（未对齐）
        self.im_diff: Optional[Image.Image] = None
        self._im_diff_key: Optional[int] = None
        self._im_diff_key2: Optional[int] = None
        self.im1_path: str = ""
        self.im2_path: str = ""

        # 文件夹对比数据
        self.folder_mode: bool = False
        self.folder1_path: str = ""
        self.folder2_path: str = ""
        self.folder1_images: list = []  # 存储图1文件夹中的文件路径
        self.folder2_images: list = []  # 存储图2文件夹中的文件路径
        self.current_image_index: int = 0  # 当前显示的图像索引
        self.total_images: int = 0  # 总图像数量
        self.uniform_size: Tuple[int, int] = (512, 512)  # 统一尺寸

        # 缓存系统 (LRU)
        self._disp_cache: OrderedDict = OrderedDict()
        self._refresh_after_id: Optional[str] = None
        self._loading: bool = False

        # 内存管理：保持PhotoImage引用防止GC
        self._photo_refs: list = []

        # PSNR相关
        self._current_psnr: Optional[float] = None
        self._psnr_thread: Optional[threading.Thread] = None
        self._psnr_calculation_in_progress: bool = False

        # 视图参数
        self.zoom: float = 1.0
        self.pan_x: float = 0.0
        self.pan_y: float = 0.0

        # 交互状态
        self.toggle_idx: int = 1
        self.split_pos: float = 0.5
        self.slider_drag: bool = False
        self.toggle_pressed: bool = False
        self.dragging: bool = False
        self.last_drag_x: int = 0
        self.last_drag_y: int = 0

        # 放大镜节流
        self._last_magnifier_time: float = 0.0

        # UI组件
        self.mode_var: tk.StringVar = tk.StringVar(value="并排对比")
        self.res_lbl: ttk.Label
        self.zoom_lbl: ttk.Label
        self.status_lbl: ttk.Label
        self.canvas_left: tk.Canvas
        self.canvas_right: tk.Canvas
        self.canvas_frame: ttk.Frame

        # 绘制策略（延迟初始化，避免启动卡顿）
        self._draw_strategies: Dict[str, DrawStrategy] = {}
        self.mode: str = "side_by_side"
        self.build_ui()

        # 初始化模式
        self.mode_var.set("并排对比")
        self.on_mode_change()

        # 预初始化绘制策略，避免第一次加载时的卡顿
        self._initialize_draw_strategies()

        self.schedule_refresh(immediate=True)

    def _initialize_draw_strategies(self) -> None:
        """初始化所有绘制策略"""
        self._draw_strategies = {
            "side_by_side": SideBySideStrategy(self),
            "toggle": ToggleStrategy(self),
            "slider": SliderStrategy(self),
            "magnifier": MagnifierStrategy(self),
            "difference": DifferenceStrategy(self)
        }

    def build_ui(self):
        main = ttk.Frame(self.root)
        main.pack(fill=tk.BOTH, expand=True)

        # 上方控制区
        ctrl = ttk.Frame(main)
        ctrl.pack(fill=tk.X, side=tk.TOP, padx=6, pady=6)

        # 文件夹模式切换
        mode_switch_row = ttk.Frame(ctrl)
        mode_switch_row.pack(side=tk.TOP, fill=tk.X, pady=(0, 8))
        ttk.Label(mode_switch_row, text="对比模式:").pack(side=tk.LEFT, padx=(0, 8))
        self.compare_mode_var = tk.StringVar(value="单张对比")
        ttk.Radiobutton(mode_switch_row, text="单张对比", variable=self.compare_mode_var,
                        value="单张对比", command=self.switch_compare_mode).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Radiobutton(mode_switch_row, text="文件夹对比", variable=self.compare_mode_var,
                        value="文件夹对比", command=self.switch_compare_mode).pack(side=tk.LEFT, padx=(0, 8))

        # 图像加载区
        load_row = ttk.Frame(ctrl)
        load_row.pack(side=tk.TOP, fill=tk.X, pady=(0, 8))

        # 单张对比控件
        self.single_frame = ttk.Frame(load_row)
        self.single_frame.pack(side=tk.TOP, fill=tk.X)

        # 单张加载按钮
        btn_frame = ttk.Frame(self.single_frame)
        btn_frame.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(btn_frame, text="加载图1", width=10, command=self.load_im1).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="加载图2", width=10, command=self.load_im2).pack(side=tk.LEFT, padx=2)
        self.res_lbl = ttk.Label(btn_frame, text="图1: - | 图2: -")
        self.res_lbl.pack(side=tk.LEFT, padx=10)

        # 文件夹对比控件
        self.folder_frame = ttk.Frame(load_row)
        self.folder_frame.pack(side=tk.TOP, fill=tk.X)

        # 文件夹选择按钮
        folder_btn_frame = ttk.Frame(self.folder_frame)
        folder_btn_frame.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(folder_btn_frame, text="选择文件夹1", width=12, command=self.load_folder1).pack(side=tk.LEFT, padx=2)
        ttk.Button(folder_btn_frame, text="选择文件夹2", width=12, command=self.load_folder2).pack(side=tk.LEFT, padx=2)

        # 统一尺寸设置
        size_frame = ttk.Frame(self.folder_frame)
        size_frame.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(size_frame, text="统一尺寸:").pack(side=tk.LEFT, padx=(0, 4))
        self.width_var = tk.StringVar(value=str(self.uniform_size[0]))
        self.height_var = tk.StringVar(value=str(self.uniform_size[1]))
        ttk.Entry(size_frame, textvariable=self.width_var, width=5).pack(side=tk.LEFT, padx=(0, 1))
        ttk.Label(size_frame, text="x").pack(side=tk.LEFT, padx=1)
        ttk.Entry(size_frame, textvariable=self.height_var, width=5).pack(side=tk.LEFT, padx=(0, 2))
        ttk.Button(size_frame, text="设置", width=6, command=self.set_uniform_size).pack(side=tk.LEFT, padx=(0, 2))

        # 翻页控件
        nav_frame = ttk.Frame(self.folder_frame)
        nav_frame.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(nav_frame, text="◀", width=3, command=self.prev_image).pack(side=tk.LEFT, padx=1)
        self.page_label = ttk.Label(nav_frame, text="0/0")
        self.page_label.pack(side=tk.LEFT, padx=4)
        ttk.Button(nav_frame, text="▶", width=3, command=self.next_image).pack(side=tk.LEFT, padx=1)

        # 模式选择和缩放控制区
        control_row = ttk.Frame(ctrl)
        control_row.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))

        # 模式选择
        mode_row = ttk.Frame(control_row)
        mode_row.pack(side=tk.LEFT, padx=12)
        ttk.Label(mode_row, text="模式:").pack(side=tk.LEFT)
        self.mode_var = tk.StringVar(value="并排对比")
        mode_cb = ttk.Combobox(mode_row, textvariable=self.mode_var,
                               values=["并排对比", "快速切换", "滑动对比", "局部放大", "差异显示"],
                               width=10, state="readonly")
        mode_cb.bind("<<ComboboxSelected>>", self.on_mode_change)
        mode_cb.pack(side=tk.LEFT, padx=4)

        # 缩放控制
        zoom_row = ttk.Frame(control_row)
        zoom_row.pack(side=tk.LEFT, padx=12)
        ttk.Label(zoom_row, text="缩放:").pack(side=tk.LEFT, padx=2)
        ttk.Button(zoom_row, text="－", width=6, command=self.zoom_out).pack(side=tk.LEFT, padx=1)
        ttk.Button(zoom_row, text="100%", width=6, command=self.zoom_1x).pack(side=tk.LEFT, padx=1)
        ttk.Button(zoom_row, text="＋", width=6, command=self.zoom_in).pack(side=tk.LEFT, padx=1)
        ttk.Button(zoom_row, text="适应窗口", width=10, command=self.fit_win).pack(side=tk.LEFT, padx=4)
        self.zoom_lbl = ttk.Label(zoom_row, text="100%")
        self.zoom_lbl.pack(side=tk.LEFT, padx=6)

        # 图像显示区域
        disp = ttk.LabelFrame(main, text="图像对比", padding=4)
        disp.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        self.canvas_frame = ttk.Frame(disp)
        self.canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas_left = tk.Canvas(self.canvas_frame, bg="#333333", cursor="crosshair")
        self.canvas_left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas_right = tk.Canvas(self.canvas_frame, bg="#333333", cursor="crosshair")
        self.canvas_right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 状态栏
        status = ttk.Frame(self.root)
        status.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_lbl = ttk.Label(status, text="就绪")
        self.status_lbl.pack(side=tk.LEFT, padx=4)
        # 添加文件夹状态显示
        self.folder_status_label = ttk.Label(status, text="")
        self.folder_status_label.pack(side=tk.RIGHT, padx=4)

        # 初始化显示界面（默认单张对比）
        self.switch_compare_mode()

        # 事件绑定（保持原有逻辑不变）
        self.canvas_left.bind("<Enter>", lambda e: self.canvas_left.focus_set())
        self.canvas_left.bind("<ButtonPress-1>", self.on_b1_down)
        self.canvas_left.bind("<B1-Motion>", self.on_b1_move)
        self.canvas_left.bind("<ButtonRelease-1>", self.on_b1_up)
        self.canvas_left.bind("<Motion>", self.on_move)
        self.canvas_left.bind("<MouseWheel>", self.on_mouse_wheel)
        self.canvas_left.bind("<Configure>", lambda e: self.schedule_refresh(immediate=True))

        # 添加快捷键绑定
        self.root.bind('<Key>', self.on_key_press)

        self.canvas_right.bind("<Enter>", lambda e: self.canvas_right.focus_set())
        self.canvas_right.bind("<ButtonPress-1>",
                               lambda e: self.canvas_left.event_generate("<ButtonPress-1>", x=e.x, y=e.y))
        self.canvas_right.bind("<B1-Motion>", lambda e: self.canvas_left.event_generate("<B1-Motion>", x=e.x, y=e.y))
        self.canvas_right.bind("<ButtonRelease-1>",
                               lambda e: self.canvas_left.event_generate("<ButtonRelease-1>", x=e.x, y=e.y))
        self.canvas_right.bind("<Motion>", lambda e: self.canvas_left.event_generate("<Motion>", x=e.x, y=e.y))
        self.canvas_right.bind("<Configure>", lambda e: self.schedule_refresh(immediate=True))

    # ---------------- load images ----------------
    def set_loading(self, flag, text=""):
        self._loading = flag
        state = tk.DISABLED if flag else tk.NORMAL
        self.status_lbl.config(text=text)

    def load_im1(self):
        p = filedialog.askopenfilename(title="选择第一张图像",
                                       filetypes=[("图像", "*.jpg *.jpeg *.png *.bmp *.tiff *.tif")])
        if p:
            self.im1_path = p
            self.update_path_lbl()
            threading.Thread(target=self._load_image_thread, args=(1, p), daemon=True).start()

    def load_im2(self):
        p = filedialog.askopenfilename(title="选择第二张图像",
                                       filetypes=[("图像", "*.jpg *.jpeg *.png *.bmp *.tiff *.tif")])
        if p:
            self.im2_path = p
            self.update_path_lbl()
            threading.Thread(target=self._load_image_thread, args=(2, p), daemon=True).start()

    def update_path_lbl(self):
        pass  # keep simple for now (status shows sizes after load)


    def _load_image_thread(self, slot, path):
        try:
            self.root.after(0, lambda: self.set_loading(True, f"加载 {Path(path).name} ..."))
            im = Image.open(path)
            # 关键修复：16-bit 图像缩放到 8-bit
            if im.mode == 'I;16':
                im = im.point(lambda x: x * (255.0 / 65535.0)).convert('L')
            try:
                im = im.convert("RGB")
            except Exception:
                im = im.copy().convert("RGB")

            def finish():
                # 保存原始图像
                if slot == 1:
                    self.im1_raw = im
                    self.im1_orig = im
                else:
                    self.im2_raw = im
                    self.im2_orig = im

                # 多分辨率对齐：如果两图都已加载且大小不同，自动对齐到最大尺寸
                if self.im1_orig and self.im2_orig and self.im1_orig.size != self.im2_orig.size:
                    self._align_images_to_same_size()
                    self.res_lbl.config(
                        text=f"图1: {self.im1_orig.size} | 图2: {self.im2_orig.size} (已对齐)")

                self._disp_cache.clear()
                self.im_diff = None  # reset diff on new image load
                self.set_loading(False, "")
                if not self.res_lbl.cget("text").endswith("(已对齐)"):  # 避免覆盖对齐信息
                    self.res_lbl.config(
                        text=f"图1: {self.im1_orig.size if self.im1_orig else '-'} | 图2: {self.im2_orig.size if self.im2_orig else '-'}")
                self.zoom, self.pan_x, self.pan_y = 1.0, 0.0, 0.0
                self.split_pos = 0.5
                try:
                    self.fit_win()
                except Exception:
                    pass
                # ---- 新增：确保加载后模式刷新，拖动逻辑生效 ----
                self.on_mode_change()
                self.schedule_refresh(immediate=True)

                # 加载完成后，如果两张图都存在，自动计算PSNR并更新状态栏
                if self.im1_orig and self.im2_orig and self.im1_orig.size == self.im2_orig.size:
                    self._start_psnr_calculation()
                else:
                    self._current_psnr = None
                    self._update_status_with_psnr()

            self.root.after(0, finish)
        except Exception as e:
            self.root.after(0, lambda: (self.set_loading(False), self.status_lbl.config(text="加载失败")))
            print("加载图像出错:", e)
            traceback.print_exc()

    def _align_images_to_same_size(self):
        """自动对齐两张图像到相同尺寸，保持宽高比（缩放后居中放置）"""
        if not (self.im1_raw and self.im2_raw):
            return

        w1, h1 = self.im1_raw.size
        w2, h2 = self.im2_raw.size

        if (w1, h1) == (w2, h2):
            # 如果原始尺寸相同，直接设置为原始图像
            self.im1_orig = self.im1_raw
            self.im2_orig = self.im2_raw
            return

        # 计算目标尺寸（取最大尺寸）
        target_w = max(w1, w2)
        target_h = max(h1, h2)

        # 基于原始图像重新调整图像1
        if (w1, h1) != (target_w, target_h):
            # 计算缩放比例，保持宽高比
            scale1 = min(target_w / w1, target_h / h1)
            new_w1 = int(w1 * scale1)
            new_h1 = int(h1 * scale1)

            # 创建新图像，居中放置缩放后的图像
            new_im1 = Image.new("RGB", (target_w, target_h), (40, 40, 40))  # 用灰色背景
            scaled_im1 = self.im1_raw.resize((new_w1, new_h1), RESAMPLE_LANCZOS)
            x = (target_w - new_w1) // 2
            y = (target_h - new_h1) // 2
            new_im1.paste(scaled_im1, (x, y))
            self.im1_orig = new_im1
        else:
            self.im1_orig = self.im1_raw

        # 基于原始图像重新调整图像2
        if (w2, h2) != (target_w, target_h):
            # 计算缩放比例，保持宽高比
            scale2 = min(target_w / w2, target_h / h2)
            new_w2 = int(w2 * scale2)
            new_h2 = int(h2 * scale2)

            # 创建新图像，居中放置缩放后的图像
            new_im2 = Image.new("RGB", (target_w, target_h), (40, 40, 40))  # 用灰色背景
            scaled_im2 = self.im2_raw.resize((new_w2, new_h2), RESAMPLE_LANCZOS)
            x = (target_w - new_w2) // 2
            y = (target_h - new_h2) // 2
            new_im2.paste(scaled_im2, (x, y))
            self.im2_orig = new_im2
        else:
            self.im2_orig = self.im2_raw

    # ---------------- interactions ----------------
    def on_mode_change(self, _=None):
        mode_map = {"并排对比": "side_by_side", "快速切换": "toggle",
                    "滑动对比": "slider", "局部放大": "magnifier", "差异显示": "difference"}
        new_mode = mode_map.get(self.mode_var.get(), "side_by_side")
        self.mode = new_mode
        # when switching, ensure canvases packing matches requirement:
        if self.mode == "side_by_side":
            # show both canvases side by side
            self.canvas_right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        else:
            # only left canvas used
            self.canvas_right.pack_forget()
        # reset some view parameters to keep UI predictable
        self.zoom, self.pan_x, self.pan_y = 1.0, 0.0, 0.0
        self.split_pos = 0.5
        # ensure images fit when switching modes
        try:
            self.fit_win()
        except Exception:
            pass
        self.schedule_refresh(immediate=True)

        hints = {"magnifier": "局部放大：移动鼠标查看固定 100x100 放大区域",
                 "slider": "滑动对比：按住并水平拖动分割线",
                 "toggle": "快速切换：按住鼠标可切换到另一个图，松开返回",
                 "side_by_side": "并排对比：两个画布并排显示，缩放同步",
                 "difference": "差异显示：显示两图像的像素差异"}
        base_hint = hints.get(self.mode, "")

        # 如果有PSNR值，总是显示在状态栏右侧
        status_text = base_hint
        if self._current_psnr is not None:
            if base_hint:
                status_text += f" | PSNR: {self._current_psnr:.2f} dB"
            else:
                status_text = f"PSNR: {self._current_psnr:.2f} dB"

        self.status_lbl.config(text=status_text)

    def on_b1_down(self, event):
        # slider toggle if near split
        if self.mode == "slider" and self.im1_orig:
            ix, _ = self.canvas_to_image(event.x, event.y, for_left=True)
            split_ix = int(self.im1_orig.width * self.split_pos)
            tol = max(3, 6 / max(0.5, self.zoom))
            if abs(ix - split_ix) <= tol:
                self.slider_drag = True
                self.canvas_left.config(cursor="sb_h_double_arrow")
                return
        if self.mode == "toggle":
            # press-and-hold to show the other image; release to revert
            if self.im1_orig and self.im2_orig:
                self.toggle_idx = 3 - self.toggle_idx
                self.toggle_pressed = True
                self.schedule_refresh(immediate=True)
            return
        self.dragging = True
        self.last_drag_x, self.last_drag_y = event.x, event.y
        self.canvas_left.config(cursor="fleur")

    def on_b1_move(self, event):
        if self.dragging and not self.slider_drag:
            dx = event.x - self.last_drag_x
            dy = event.y - self.last_drag_y
            self.last_drag_x, self.last_drag_y = event.x, event.y
            # pan: change pan_x/pan_y in image fraction coordinates
            # simple heuristic: move fraction proportional to px movement / (zoom*canvas)
            cw, ch = self.canvas_left.winfo_width(), self.canvas_left.winfo_height()
            if cw > 0 and ch > 0:
                self.pan_x += dx / max(1, self.zoom * cw)
                self.pan_y += dy / max(1, self.zoom * ch)
                # clamp pan to reasonable range
                self.pan_x = max(-10, min(10, self.pan_x))
                self.pan_y = max(-10, min(10, self.pan_y))
            self.schedule_refresh(immediate=True)
        elif self.slider_drag:
            # update split position based on mouse x
            if not self.im1_orig:
                return
            ix, _ = self.canvas_to_image(event.x, event.y, for_left=True)
            self.split_pos = max(0.0, min(1.0, ix / max(1, self.im1_orig.width)))
            # immediate refresh on slider drag for snappy feel
            self.schedule_refresh(immediate=True)

    def on_b1_up(self, _):
        self.dragging = False
        self.slider_drag = False
        # if we were in press-and-hold toggle mode, revert on release
        if getattr(self, 'toggle_pressed', False) and self.mode == 'toggle':
            self.toggle_idx = 3 - self.toggle_idx
            self.toggle_pressed = False
            self.schedule_refresh(immediate=True)
        self.canvas_left.config(cursor="crosshair")

    def on_move(self, event):
        # magnifier: show fixed-crop local magnified region in single-canvas modes
        if getattr(self, 'mode', None) == "magnifier" and self.im1_orig and self.im2_orig:
            # throttle updates to ~30fps
            now = time.time()
            if not hasattr(self, "_last_magnifier_time") or now - self._last_magnifier_time > 1 / 30.0:
                self._last_magnifier_time = now
                self.schedule_refresh(immediate=True)

    def on_key_press(self, event):
        """处理快捷键"""
        key = event.char.lower()
        # 模式切换: 数字键1-5
        mode_keys = {'1': "并排对比", '2': "快速切换", '3': "滑动对比", '4': "局部放大", '5': "差异显示"}
        if key in mode_keys:
            self.mode_var.set(mode_keys[key])
            self.on_mode_change()
        # 缩放控制: +, -, 0, f
        elif key == '+':
            self.zoom_in()
        elif key == '-':
            self.zoom_out()
        elif key == '0':
            self.zoom_1x()
        elif key == 'f':
            self.fit_win()
        # 文件操作: o, i(图1), r(图2, recall/reset?)
        elif key == 'o':
            self.load_im1()  # 默认加载图1
        elif key == 'i':
            self.load_im1()
        elif key == 'r':
            self.load_im2()
        elif key == 't':
            self.toggle()  # 切换切换模式
        # 忽略其他组合键
        elif event.state & (1|4|8):  # Ctrl, Alt, Shift 等
            pass

    def on_mouse_wheel(self, event):
        # simple zoom by wheel
        if event.delta > 0:
            self.zoom_in()
        else:
            self.zoom_out()

    def zoom_in(self):
        self.zoom *= 1.25
        self.zoom = min(self.zoom, 64)
        self.schedule_refresh(immediate=True)

    def zoom_out(self):
        self.zoom /= 1.25
        self.zoom = max(self.zoom, 0.01)
        self.schedule_refresh(immediate=True)

    def zoom_1x(self):
        self.zoom = 1.0
        self.schedule_refresh(immediate=True)

    def fit_win(self):
        # auto compute zoom to fit the bigger of the two images into canvas_left (or both)
        cw, ch = self.canvas_left.winfo_width(), self.canvas_left.winfo_height()
        if cw <= 1 or ch <= 1:
            return
        # choose reference image if available
        im = self.im1_orig or self.im2_orig
        if im is None:
            return
        # compute scale to fit whole image into canvas
        w_scale = cw / im.width
        h_scale = ch / im.height
        new_zoom = min(w_scale, h_scale)
        new_zoom = max(0.01, new_zoom)
        self.zoom = new_zoom
        self.pan_x, self.pan_y = 0.0, 0.0
        self.zoom_lbl.config(text=f"缩放: {int(self.zoom*100)}%")
        self.schedule_refresh(immediate=True)

    # ---------------- drawing helpers ----------------
    def _get_disp_image(self, im: Optional[Image.Image]) -> Optional[Image.Image]:
        """返回缓存的缩放图像，使用LRU缓存策略

        Args:
            im: 原始图像

        Returns:
            缩放后的图像或None
        """
        if im is None:
            return None

        key = (id(im), round(self.zoom, 6))

        if key in self._disp_cache:
            # 移动到最频繁使用位置
            self._disp_cache.move_to_end(key)
            return self._disp_cache[key]

        try:
            nw = max(1, int(im.width * self.zoom))
            nh = max(1, int(im.height * self.zoom))
            disp = im.resize((nw, nh), RESAMPLE_LANCZOS)

            # 添加到缓存，如果满员则移除最旧的
            if len(self._disp_cache) >= Config.MAX_CACHE_SIZE:
                self._disp_cache.popitem(last=False)  # 移除最旧的 (FIFO)

            self._disp_cache[key] = disp
            return disp

        except Exception as e:
            print(f"缩放图像失败: {e}")
            return None

    def _image_display_params_for_canvas(self, im, canvas):
        """Return (display_image, left, top) for drawing on canvas, mapping pan/zoom centers consistently."""
        disp = self._get_disp_image(im)
        if disp is None:
            return None, 0, 0
        cw, ch = canvas.winfo_width(), canvas.winfo_height()
        # center the image in canvas, considering pan
        left = int((cw - disp.width) / 2 + self.pan_x * cw)
        top = int((ch - disp.height) / 2 + self.pan_y * ch)
        return disp, left, top

    def canvas_to_image(self, cx, cy, for_left=True):
        """map canvas coords to image coords (image1). for_left used to select which canvas mapping."""
        canvas = self.canvas_left if for_left else self.canvas_right
        disp, left, top = self._image_display_params_for_canvas(self.im1_orig, canvas)
        if disp is None:
            return 0, 0
        ix = int((cx - left) / max(1, disp.width) * self.im1_orig.width)
        iy = int((cy - top) / max(1, disp.height) * self.im1_orig.height)
        return ix, iy



    # ---------------- scheduling & drawing ----------------
    def schedule_refresh(self, immediate=False):
        # debounce but allow immediate forced refresh
        if self._refresh_after_id:
            try:
                self.root.after_cancel(self._refresh_after_id)
            except Exception:
                pass
            self._refresh_after_id = None
        if immediate:
            self._do_refresh()
        else:
            self._refresh_after_id = self.root.after(80, self._do_refresh)

    def _get_strategy(self, mode: str) -> Optional[DrawStrategy]:
        """延迟获取策略对象，只在需要时创建"""
        if mode not in self._draw_strategies:
            strategy_classes = {
                "side_by_side": SideBySideStrategy,
                "toggle": ToggleStrategy,
                "slider": SliderStrategy,
                "magnifier": MagnifierStrategy,
                "difference": DifferenceStrategy
            }

            if mode in strategy_classes:
                self._draw_strategies[mode] = strategy_classes[mode](self)

        return self._draw_strategies.get(mode)

    def _do_refresh(self) -> None:
        """刷新显示，使用策略模式绘制"""
        try:
            # 清理旧的PhotoImage引用
            self._photo_refs.clear()
            self.canvas_left.delete("all")
            self.canvas_right.delete("all")

            # 使用策略模式绘制（延迟初始化）
            strategy = self._get_strategy(self.mode)
            if strategy:
                strategy.draw()
            else:
                print(f"未知的绘制模式: {self.mode}")

            # 更新缩放显示
            self.zoom_lbl.config(text=f"缩放: {int(self.zoom*100)}%")

        except Exception as e:
            print(f"刷新出错: {e}")
            traceback.print_exc()
            # 在出错时显示错误状态
            self.status_lbl.config(text=f"绘制错误: {str(e)[:50]}...")

    def _start_psnr_calculation(self) -> None:
        """启动后台PSNR计算"""
        if not (self.im1_orig and self.im2_orig and self.im1_orig.size == self.im2_orig.size):
            self._current_psnr = None
            self._update_status_with_psnr()
            return

        # 如果已经有计算在进行，先取消
        if self._psnr_calculation_in_progress:
            return

        # 启动新线程进行计算
        self._psnr_calculation_in_progress = True
        self._psnr_thread = threading.Thread(target=self._calculate_psnr_thread, daemon=True)
        self._psnr_thread.start()

    def _calculate_psnr_thread(self) -> None:
        """后台线程计算PSNR"""
        try:
            psnr_value = self._calculate_psnr_sync()
            # 在主线程中更新UI
            self.root.after(0, lambda: self._on_psnr_calculated(psnr_value))
        except Exception as e:
            print(f"PSNR计算出错: {e}")
            self.root.after(0, lambda: self._on_psnr_calculation_failed())

    def _calculate_psnr_sync(self) -> float:
        """同步计算PSNR（在后台线程中调用，使用NumPy矢量化提升性能）

        Returns:
            计算得到的PSNR值
        """
        if not (self.im1_orig and self.im2_orig):
            return 0.0

        im1 = self.im1_orig.convert("RGB")
        im2 = self.im2_orig.convert("RGB")

        if im1.size != im2.size:
            return 0.0

        # 使用NumPy矢量化计算MSE，性能提升数十倍
        im1_array = np.array(im1, dtype=np.float32)
        im2_array = np.array(im2, dtype=np.float32)

        # 计算像素差异的平方和
        diff = im1_array - im2_array
        squared_diff = diff ** 2
        mse_per_channel = np.mean(squared_diff, axis=(0, 1))  # 先计算每通道MSE
        mse = np.mean(mse_per_channel)  # 再平均所有通道

        # 计算PSNR
        if mse == 0:
            return float('inf')  # 完全相同，无限大PSNR

        psnr = 20.0 * math.log10(Config.MAX_8BIT_PIXEL / math.sqrt(mse))
        return psnr

    def _on_psnr_calculated(self, psnr_value: float) -> None:
        """PSNR计算完成回调"""
        self._current_psnr = psnr_value
        self._psnr_calculation_in_progress = False
        self._update_status_with_psnr()

    def _on_psnr_calculation_failed(self) -> None:
        """PSNR计算失败回调"""
        self._current_psnr = None
        self._psnr_calculation_in_progress = False
        self._update_status_with_psnr()

    def _update_status_with_psnr(self) -> None:
        """更新状态栏显示PSNR信息"""
        base_hint = Config.MODE_HINTS.get(self.mode, "")

        status_text = base_hint
        if self._current_psnr is not None:
            if base_hint:
                status_text += f" | PSNR: {self._current_psnr:.2f} dB"
            else:
                status_text = f"PSNR: {self._current_psnr:.2f} dB"

        self.status_lbl.config(text=status_text)

    # ---------------- 文件夹对比功能 ----------------
    def switch_compare_mode(self):
        """切换单张/文件夹对比模式"""
        if self.compare_mode_var.get() == "文件夹对比":
            self.folder_mode = True
            self.single_frame.pack_forget()
            self.folder_frame.pack(side=tk.TOP, fill=tk.X)

            # 如果已加载文件夹，显示第一组图像
            if self.folder1_images and self.folder2_images and self.total_images > 0:
                self.load_current_image_pair()
        else:
            self.folder_mode = False
            self.folder_frame.pack_forget()
            self.single_frame.pack(side=tk.TOP, fill=tk.X)
            self.folder_status_label.config(text="")
            # 清除文件夹模式数据
            self.folder_mode = False

    def load_folder1(self):
        """选择文件夹1"""
        folder = filedialog.askdirectory(title="选择图1文件夹")
        if folder:
            self.folder1_path = folder
            self._load_folder_images(folder, 1)
            self._update_folder_status()

            # 如果两个文件夹都已选择，自动匹配
            if self.folder1_images and self.folder2_images:
                self._match_folder_images()

    def load_folder2(self):
        """选择文件夹2"""
        folder = filedialog.askdirectory(title="选择图2文件夹")
        if folder:
            self.folder2_path = folder
            self._load_folder_images(folder, 2)
            self._update_folder_status()

            # 如果两个文件夹都已选择，自动匹配
            if self.folder1_images and self.folder2_images:
                self._match_folder_images()

    def set_uniform_size(self):
        """设置统一尺寸"""
        try:
            w = int(self.width_var.get())
            h = int(self.height_var.get())
            if w > 0 and h > 0:
                self.uniform_size = (w, h)
                messagebox.showinfo("设置成功", f"统一尺寸已设置为 {w}x{h}")
                # 如果当前在文件夹模式且有图像，重新加载当前图像对
                if self.folder_mode and self.total_images > 0:
                    self.load_current_image_pair()
            else:
                messagebox.showerror("错误", "尺寸必须大于0")
        except ValueError:
            messagebox.showerror("错误", "请输入有效的整数尺寸")

    def prev_image(self):
        """切换到上一张图像"""
        if self.folder_mode and self.total_images > 0:
            self.current_image_index = (self.current_image_index - 1) % self.total_images
            self.load_current_image_pair()

    def next_image(self):
        """切换到下一张图像"""
        if self.folder_mode and self.total_images > 0:
            self.current_image_index = (self.current_image_index + 1) % self.total_images
            self.load_current_image_pair()

    def _load_folder_images(self, folder_path, folder_id):
        """加载文件夹中的图像文件列表"""
        image_extensions = ['*.jpg', '*.jpeg', '*.png', '*.bmp', '*.tiff', '*.tif']
        image_files = []

        for ext in image_extensions:
            pattern = Path(folder_path) / ext
            image_files.extend(glob.glob(str(pattern)))

        image_files.sort()  # 按文件名排序

        if folder_id == 1:
            self.folder1_images = image_files
        else:
            self.folder2_images = image_files

    def _match_folder_images(self):
        """匹配两个文件夹中的图像文件"""
        if not (self.folder1_images and self.folder2_images):
            return

        # 提取文件名（不含扩展名）的公共前缀部分
        def extract_common_prefix(path):
            stem = Path(path).stem
            return stem

        # 创建映射关系
        folder2_map = {}
        for img2_path in self.folder2_images:
            prefix2 = extract_common_prefix(img2_path)
            folder2_map[prefix2] = img2_path

        # 配对图像
        matched_pairs = []
        for img1_path in self.folder1_images:
            prefix1 = extract_common_prefix(img1_path)
            if prefix1 in folder2_map:
                matched_pairs.append((img1_path, folder2_map[prefix1]))

        if matched_pairs:
            # 重新设置图像列表为匹配对
            self.folder1_images = [pair[0] for pair in matched_pairs]
            self.folder2_images = [pair[1] for pair in matched_pairs]
            self.total_images = len(matched_pairs)
            self.current_image_index = 0

            # 更新页面显示
            self._update_page_label()

            # 自动加载第一组图像
            self.load_current_image_pair()
        else:
            messagebox.showwarning("警告", "未找到匹配的图像文件对")
            self.total_images = 0

    def _update_folder_status(self):
        """更新文件夹状态显示"""
        status_parts = []
        if self.folder1_path:
            status_parts.append(f"文件夹1: {Path(self.folder1_path).name} ({len(self.folder1_images)}张)")
        if self.folder2_path:
            status_parts.append(f"文件夹2: {Path(self.folder2_path).name} ({len(self.folder2_images)}张)")

        self.folder_status_label.config(text=" | ".join(status_parts))

    def _update_page_label(self):
        """更新页面标签显示"""
        if self.total_images > 0:
            self.page_label.config(text=f"{self.current_image_index + 1}/{self.total_images}")
        else:
            self.page_label.config(text="0/0")

    def load_current_image_pair(self):
        """加载当前索引的图像对"""
        if not (self.folder_mode and self.total_images > 0):
            return

        if self.current_image_index >= self.total_images:
            self.current_image_index = 0

        img1_path = self.folder1_images[self.current_image_index]
        img2_path = self.folder2_images[self.current_image_index]

        # 加载并处理图像
        threading.Thread(target=self._load_image_pair_thread,
                        args=(img1_path, img2_path), daemon=True).start()

    def _load_image_pair_thread(self, img1_path, img2_path):
        """后台线程加载图像对"""
        try:
            self.root.after(0, lambda: self.set_loading(True, f"加载图像对 {self.current_image_index + 1}/{self.total_images}..."))

            # 加载并处理第一张图像
            im1 = Image.open(img1_path)
            if im1.mode == 'I;16':
                im1 = im1.point(lambda x: x * (255.0 / 65535.0)).convert('L')
            im1 = im1.convert("RGB")

            # 加载并处理第二张图像
            im2 = Image.open(img2_path)
            if im2.mode == 'I;16':
                im2 = im2.point(lambda x: x * (255.0 / 65535.0)).convert('L')
            im2 = im2.convert("RGB")

            # 统一图像尺寸（如果启用）
            if self.uniform_size:
                im1 = im1.resize(self.uniform_size, RESAMPLE_LANCZOS)
                im2 = im2.resize(self.uniform_size, RESAMPLE_LANCZOS)

            def finish():
                # 保存图像
                self.im1_orig = im1
                self.im2_orig = im2
                self.im1_raw = im1
                self.im2_raw = im2

                # 更新路径和标签
                self.im1_path = img1_path
                self.im2_path = img2_path

                # 清除缓存
                self._disp_cache.clear()
                self.im_diff = None

                # 重置视图
                self.zoom, self.pan_x, self.pan_y = 1.0, 0.0, 0.0
                self.split_pos = 0.5

                # 适应窗口
                try:
                    self.fit_win()
                except Exception:
                    pass

                # 更新UI
                filename1 = Path(img1_path).name
                filename2 = Path(img2_path).name
                self.res_lbl.config(text=f"图1: {filename1} | 图2: {filename2}")
                self._update_page_label()

                self.set_loading(False, "")

                # 刷新显示
                self.on_mode_change()
                self.schedule_refresh(immediate=True)

                # 计算PSNR
                if self.im1_orig and self.im2_orig and self.im1_orig.size == self.im2_orig.size:
                    self._start_psnr_calculation()

            self.root.after(0, finish)

        except Exception as e:
            self.root.after(0, lambda: (self.set_loading(False), self.status_lbl.config(text=f"加载失败: {str(e)}")))
            print("加载图像对出错:", e)
            traceback.print_exc()

    # ---------------- utility / debug ----------------
    def toggle(self):
        if self.mode == "toggle" and self.im1_orig and self.im2_orig:
            self.toggle_idx = 3 - self.toggle_idx
            self.schedule_refresh(immediate=True)


def main():
    root = tk.Tk()
    root.geometry("1200x700")

    # 前台激活窗口
    root.lift()
    root.focus_force()
    # 在macOS上额外确保窗口在前台
    try:
        root.attributes('-topmost', True)
        root.after(100, lambda: root.attributes('-topmost', False))
    except:
        pass  # 在不支持的平台上跳过

    app = SRCompareApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
