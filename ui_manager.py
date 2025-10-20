#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UI管理器 - 处理界面构建和交互逻辑
"""

import tkinter as tk
from tkinter import ttk
from pathlib import Path
import time


class UIManager:
    """UI组件管理和交互处理"""

    def __init__(self, app):
        self.app = app
        self.root = app.root

        # UI组件引用
        self.mode_var: tk.StringVar = tk.StringVar(value="并排对比")
        self.res_lbl: ttk.Label = None
        self.zoom_lbl: ttk.Label = None
        self.status_lbl: ttk.Label = None
        self.canvas_left: tk.Canvas = None
        self.canvas_right: tk.Canvas = None
        self.canvas_frame: ttk.Frame = None

        # 文件夹UI组件
        self.compare_mode_var = tk.StringVar(value="单张对比")
        self.single_frame: ttk.Frame = None
        self.folder_frame: ttk.Frame = None
        self.width_var = tk.StringVar(value="512")
        self.height_var = tk.StringVar(value="512")
        self.page_label: ttk.Label = None
        self.folder_status_label: ttk.Label = None

        # 放大镜节流
        self._last_magnifier_time: float = 0.0

    def build_ui(self):
        """构建整个UI界面"""
        main = tk.ttk.Frame(self.root)
        main.pack(fill=tk.BOTH, expand=True)

        # 上方控制区
        ctrl = tk.ttk.Frame(main)
        ctrl.pack(fill=tk.X, side=tk.TOP, padx=6, pady=6)

        self._build_top_controls(ctrl)

        # 图像显示区域
        self._build_display_area(main)

        # 状态栏
        self._build_status_bar()

        # 初始化显示界面
        self.switch_compare_mode()

        # 事件绑定
        self._bind_events()

    def _build_top_controls(self, ctrl):
        """构建上方面板控制区"""

        # 文件夹模式切换
        self._build_mode_switch(ctrl)

        # 图像加载区
        load_row = tk.ttk.Frame(ctrl)
        load_row.pack(side=tk.TOP, fill=tk.X, pady=(0, 8))

        # 单张对比控件
        self._build_single_controls(load_row)

        # 文件夹对比控件
        self._build_folder_controls(load_row)

        # 模式选择和缩放控制区
        self._build_mode_and_zoom_controls(ctrl)

    def _build_mode_switch(self, ctrl):
        """构建对比模式切换控件"""
        mode_switch_row = tk.ttk.Frame(ctrl)
        mode_switch_row.pack(side=tk.TOP, fill=tk.X, pady=(0, 8))
        tk.ttk.Label(mode_switch_row, text="对比模式:").pack(side=tk.LEFT, padx=(0, 8))

        tk.ttk.Radiobutton(mode_switch_row, text="单张对比", variable=self.compare_mode_var,
                          value="单张对比", command=self.switch_compare_mode).pack(side=tk.LEFT, padx=(0, 8))
        tk.ttk.Radiobutton(mode_switch_row, text="文件夹对比", variable=self.compare_mode_var,
                          value="文件夹对比", command=self.switch_compare_mode).pack(side=tk.LEFT, padx=(0, 8))

    def _build_single_controls(self, load_row):
        """构建单张对比控件"""
        self.single_frame = tk.ttk.Frame(load_row)
        self.single_frame.pack(side=tk.TOP, fill=tk.X)

        # 单张加载按钮
        btn_frame = tk.ttk.Frame(self.single_frame)
        btn_frame.pack(side=tk.LEFT, padx=(0, 10))
        tk.ttk.Button(btn_frame, text="加载图1", width=10, command=self.app.file_manager.load_im1).pack(side=tk.LEFT, padx=2)
        tk.ttk.Button(btn_frame, text="加载图2", width=10, command=self.app.file_manager.load_im2).pack(side=tk.LEFT, padx=2)
        self.res_lbl = tk.ttk.Label(btn_frame, text="图1: - | 图2: -")
        self.res_lbl.pack(side=tk.LEFT, padx=10)

    def _build_folder_controls(self, load_row):
        """构建文件夹对比控件"""
        self.folder_frame = tk.ttk.Frame(load_row)
        self.folder_frame.pack(side=tk.TOP, fill=tk.X)

        # 文件夹选择按钮
        folder_btn_frame = tk.ttk.Frame(self.folder_frame)
        folder_btn_frame.pack(side=tk.LEFT, padx=(0, 10))
        tk.ttk.Button(folder_btn_frame, text="选择文件夹1", width=12, command=self.app.file_manager.load_folder1).pack(side=tk.LEFT, padx=2)
        tk.ttk.Button(folder_btn_frame, text="选择文件夹2", width=12, command=self.app.file_manager.load_folder2).pack(side=tk.LEFT, padx=2)

        # 统一尺寸设置
        size_frame = tk.ttk.Frame(self.folder_frame)
        size_frame.pack(side=tk.LEFT, padx=(0, 10))
        tk.ttk.Label(size_frame, text="统一尺寸:").pack(side=tk.LEFT, padx=(0, 4))
        self.width_var.set(str(self.app.uniform_size[0]))
        self.height_var.set(str(self.app.uniform_size[1]))
        tk.ttk.Entry(size_frame, textvariable=self.width_var, width=5).pack(side=tk.LEFT, padx=(0, 1))
        tk.ttk.Label(size_frame, text="x").pack(side=tk.LEFT, padx=1)
        tk.ttk.Entry(size_frame, textvariable=self.height_var, width=5).pack(side=tk.LEFT, padx=(0, 2))
        tk.ttk.Button(size_frame, text="设置", width=6, command=self.app.file_manager.set_uniform_size).pack(side=tk.LEFT, padx=(0, 2))

        # 翻页控件
        nav_frame = tk.ttk.Frame(self.folder_frame)
        nav_frame.pack(side=tk.LEFT, padx=(0, 10))
        tk.ttk.Button(nav_frame, text="◀", width=3, command=self.app.file_manager.prev_image).pack(side=tk.LEFT, padx=1)
        self.page_label = tk.ttk.Label(nav_frame, text="0/0")
        self.page_label.pack(side=tk.LEFT, padx=4)
        tk.ttk.Button(nav_frame, text="▶", width=3, command=self.app.file_manager.next_image).pack(side=tk.LEFT, padx=1)

    def _build_mode_and_zoom_controls(self, ctrl):
        """构建模式选择和缩放控件"""
        control_row = tk.ttk.Frame(ctrl)
        control_row.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))

        # 模式选择
        mode_row = tk.ttk.Frame(control_row)
        mode_row.pack(side=tk.LEFT, padx=12)
        tk.ttk.Label(mode_row, text="模式:").pack(side=tk.LEFT)
        self.mode_var.set("并排对比")
        mode_cb = tk.ttk.Combobox(mode_row, textvariable=self.mode_var,
                                 values=["并排对比", "快速切换", "滑动对比", "局部放大", "差异显示"],
                                 width=10, state="readonly")
        mode_cb.bind("<<ComboboxSelected>>", self.on_mode_change)
        mode_cb.pack(side=tk.LEFT, padx=4)

        # 缩放控制
        zoom_row = tk.ttk.Frame(control_row)
        zoom_row.pack(side=tk.LEFT, padx=12)
        tk.ttk.Label(zoom_row, text="缩放:").pack(side=tk.LEFT, padx=2)
        tk.ttk.Button(zoom_row, text="－", width=6, command=self.app.view_controller.zoom_out).pack(side=tk.LEFT, padx=1)
        tk.ttk.Button(zoom_row, text="100%", width=6, command=self.app.view_controller.zoom_1x).pack(side=tk.LEFT, padx=1)
        tk.ttk.Button(zoom_row, text="＋", width=6, command=self.app.view_controller.zoom_in).pack(side=tk.LEFT, padx=1)
        tk.ttk.Button(zoom_row, text="适应窗口", width=10, command=self.app.view_controller.fit_win).pack(side=tk.LEFT, padx=4)
        self.zoom_lbl = tk.ttk.Label(zoom_row, text="100%")
        self.zoom_lbl.pack(side=tk.LEFT, padx=6)

    def _build_display_area(self, main):
        """构建图像显示区域"""
        disp = tk.ttk.LabelFrame(main, text="图像对比", padding=4)
        disp.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        self.canvas_frame = tk.ttk.Frame(disp)
        self.canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas_left = tk.Canvas(self.canvas_frame, bg=self.app.config.BG_COLOR, cursor="crosshair")
        self.canvas_left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.canvas_right = tk.Canvas(self.canvas_frame, bg=self.app.config.BG_COLOR, cursor="crosshair")
        self.canvas_right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def _build_status_bar(self):
        """构建状态栏"""
        status = tk.ttk.Frame(self.root)
        status.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_lbl = tk.ttk.Label(status, text="就绪")
        self.status_lbl.pack(side=tk.LEFT, padx=4)
        # 添加文件夹状态显示
        self.folder_status_label = tk.ttk.Label(status, text="")
        self.folder_status_label.pack(side=tk.RIGHT, padx=4)

    def switch_compare_mode(self):
        """切换单张/文件夹对比模式"""
        if self.compare_mode_var.get() == "文件夹对比":
            self.app.folder_mode = True
            self.single_frame.pack_forget()
            self.folder_frame.pack(side=tk.TOP, fill=tk.X)

            # 如果已加载文件夹，显示第一组图像
            if self.app.folder1_images and self.app.folder2_images and self.app.total_images > 0:
                self.app.file_manager.load_current_image_pair()
        else:
            self.app.folder_mode = False
            self.folder_frame.pack_forget()
            self.single_frame.pack(side=tk.TOP, fill=tk.X)
            self.folder_status_label.config(text="")
            # 清除文件夹模式数据
            self.app.folder_mode = False

    def _bind_events(self):
        """绑定所有事件"""

        # 快捷键绑定
        self.root.bind_all('<Key>', self.on_key_press)

        # 鼠标事件 - 左画布
        self.canvas_left.bind("<Enter>", lambda e: self.canvas_left.focus_set())
        self.canvas_left.bind("<ButtonPress-1>", self.on_b1_down)
        self.canvas_left.bind("<B1-Motion>", self.on_b1_move)
        self.canvas_left.bind("<ButtonRelease-1>", self.on_b1_up)
        self.canvas_left.bind("<Motion>", self.on_move)
        self.canvas_left.bind("<MouseWheel>", self.on_mouse_wheel)
        self.canvas_left.bind("<Configure>", lambda e: self.app.schedule_refresh(immediate=True))

        # 鼠标事件 - 右画布 (代理到左画布)
        self.canvas_right.bind("<Enter>", lambda e: self.canvas_right.focus_set())
        self.canvas_right.bind("<ButtonPress-1>",
                               lambda e: self.canvas_left.event_generate("<ButtonPress-1>", x=e.x, y=e.y))
        self.canvas_right.bind("<B1-Motion>", lambda e: self.canvas_left.event_generate("<B1-Motion>", x=e.x, y=e.y))
        self.canvas_right.bind("<ButtonRelease-1>",
                               lambda e: self.canvas_left.event_generate("<ButtonRelease-1>", x=e.x, y=e.y))
        self.canvas_right.bind("<Motion>", lambda e: self.canvas_left.event_generate("<Motion>", x=e.x, y=e.y))
        self.canvas_right.bind("<Configure>", lambda e: self.app.schedule_refresh(immediate=True))

    def on_mode_change(self, _=None):
        """模式切换处理"""
        mode_map = self.app.config.MODES
        new_mode = mode_map.get(self.mode_var.get(), "side_by_side")
        self.app.mode = new_mode

        # 根据模式调整画布显示
        if self.app.mode == "side_by_side":
            self.canvas_right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        else:
            self.canvas_right.pack_forget()

        # 重置视图参数
        self.app.zoom, self.app.pan_x, self.app.pan_y = 1.0, 0.0, 0.0
        self.app.split_pos = 0.5

        # 适应窗口
        try:
            self.app.view_controller.fit_win()
        except Exception:
            pass

        self.app.schedule_refresh(immediate=True)

        # 更新状态栏
        self._update_status_with_psnr()

    def _update_status_with_psnr(self):
        """更新状态栏显示PSNR信息"""
        base_hint = self.app.config.MODE_HINTS.get(self.app.mode, "")

        status_text = base_hint
        if self.app.psnr_calculator.current_psnr is not None:
            if base_hint:
                status_text += f" | PSNR: {self.app.psnr_calculator.current_psnr:.2f} dB"
            else:
                status_text = f"PSNR: {self.app.psnr_calculator.current_psnr:.2f} dB"

        self.status_lbl.config(text=status_text)

    def on_b1_down(self, event):
        """鼠标左键按下处理"""
        # 滑动条拖拽检查
        if self.app.mode == "slider" and self.app.im1_orig:
            ix, _ = self.canvas_to_image(event.x, event.y, for_left=True)
            split_ix = int(self.app.im1_orig.width * self.app.split_pos)
            tol = max(3, 6 / max(0.5, self.app.zoom))
            if abs(ix - split_ix) <= tol:
                self.app.slider_drag = True
                self.canvas_left.config(cursor="sb_h_double_arrow")
                return

        # 切换模式按下处理
        if self.app.mode == "toggle":
            if self.app.im1_orig and self.app.im2_orig:
                self.app.toggle_idx = 3 - self.app.toggle_idx
                self.app.toggle_pressed = True
                self.app.schedule_refresh(immediate=True)
            return

        # 开始拖拽
        self.app.dragging = True
        self.app.last_drag_x, self.app.last_drag_y = event.x, event.y
        self.canvas_left.config(cursor="fleur")

    def on_b1_move(self, event):
        """鼠标左键移动处理"""
        if self.app.dragging and not self.app.slider_drag:
            # 平移处理
            dx = event.x - self.app.last_drag_x
            dy = event.y - self.app.last_drag_y
            self.app.last_drag_x, self.app.last_drag_y = event.x, event.y

            cw, ch = self.canvas_left.winfo_width(), self.canvas_left.winfo_height()
            if cw > 0 and ch > 0:
                self.app.pan_x += dx / max(1, self.app.zoom * cw)
                self.app.pan_y += dy / max(1, self.app.zoom * ch)
                # 限制平移范围
                self.app.pan_x = max(-10, min(10, self.app.pan_x))
                self.app.pan_y = max(-10, min(10, self.app.pan_y))
            self.app.schedule_refresh(immediate=True)

        elif self.app.slider_drag:
            # 滑动条位置更新
            if not self.app.im1_orig:
                return
            ix, _ = self.canvas_to_image(event.x, event.y, for_left=True)
            self.app.split_pos = max(0.0, min(1.0, ix / max(1, self.app.im1_orig.width)))
            self.app.schedule_refresh(immediate=True)

    def on_b1_up(self, _):
        """鼠标左键释放处理"""
        self.app.dragging = False
        self.app.slider_drag = False

        # 切换模式释放处理
        if getattr(self.app, 'toggle_pressed', False) and self.app.mode == 'toggle':
            self.app.toggle_idx = 3 - self.app.toggle_idx
            self.app.toggle_pressed = False
            self.app.schedule_refresh(immediate=True)

        self.canvas_left.config(cursor="crosshair")

    def on_move(self, event):
        """鼠标移动处理"""
        # 放大镜模式节流更新
        if self.app.mode == "magnifier" and self.app.im1_orig and self.app.im2_orig:
            now = time.time()
            if now - self._last_magnifier_time > 1 / 30.0:
                self._last_magnifier_time = now
                self.app.schedule_refresh(immediate=True)

    def on_key_press(self, event):
        """快捷键处理"""
        key = event.char.lower()

        # 模式切换: 数字键1-5
        mode_keys = {'1': "并排对比", '2': "快速切换", '3': "滑动对比", '4': "局部放大", '5': "差异显示"}
        if key in mode_keys:
            self.mode_var.set(mode_keys[key])
            self.on_mode_change()

        # 缩放控制: +, -, 0, f
        elif key == '+':
            self.app.view_controller.zoom_in()
        elif key == '-':
            self.app.view_controller.zoom_out()
        elif key == '0':
            self.app.view_controller.zoom_1x()
        elif key == 'f':
            self.app.view_controller.fit_win()

        # 文件操作: o, i(图1), r(图2), t(切换)
        elif key == 'o':
            self.app.file_manager.load_im1()
        elif key == 'i':
            self.app.file_manager.load_im1()
        elif key == 'r':
            self.app.file_manager.load_im2()
        elif key == 't':
            self.app.toggle()

        # 忽略其他组合键
        elif event.state & (1|4|8):  # Ctrl, Alt, Shift 等
            pass

    def on_mouse_wheel(self, event):
        """鼠标滚轮缩放"""
        if event.delta > 0:
            self.app.view_controller.zoom_in()
        else:
            self.app.view_controller.zoom_out()

    def canvas_to_image(self, cx, cy, for_left=True):
        """画布坐标转图像坐标"""
        return self.app.view_controller.canvas_to_image(cx, cy, for_left)

    def update_folder_status(self):
        """更新文件夹状态显示"""
        status_parts = []
        if self.app.folder1_path:
            status_parts.append(f"文件夹1: {Path(self.app.folder1_path).name} ({len(self.app.folder1_images)}张)")
        if self.app.folder2_path:
            status_parts.append(f"文件夹2: {Path(self.app.folder2_path).name} ({len(self.app.folder2_images)}张)")

        self.folder_status_label.config(text=" | ".join(status_parts))

    def update_page_label(self):
        """更新页面标签显示"""
        if self.app.total_images > 0:
            self.page_label.config(text=f"{self.app.current_image_index + 1}/{self.app.total_images}")
        else:
            self.page_label.config(text="0/0")

    def set_loading(self, flag, text=""):
        """设置加载状态"""
        self.app._loading = flag
        state = tk.DISABLED if flag else tk.NORMAL
        self.status_lbl.config(text=text)
