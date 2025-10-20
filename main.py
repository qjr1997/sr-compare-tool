#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
超分辨率图像对比工具主应用 - 重构版本
"""

import tkinter as tk
from tkinter import ttk
from typing import Optional, Dict
from collections import OrderedDict
from PIL import Image
import time

from config import Config
from strategies import DrawStrategy, SideBySideStrategy, ToggleStrategy, SliderStrategy, \
    MagnifierStrategy, DifferenceStrategy

# 导入重构后的模块
from ui_manager import UIManager
from file_manager import FileManager
from view_controller import ViewController
from psnr_calculator import PSNRCalculator


class SRCompareApp:
    """超分辨率图像对比工具主应用类"""

    def __init__(self, root: tk.Tk) -> None:
        """
        初始化应用

        Args:
            root: Tkinter根窗口
        """
        self.root = root
        root.title("超分图像对比工具 - 重构版")

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

        # 交互状态
        self.toggle_idx: int = 1
        self.split_pos: float = 0.5
        self.slider_drag: bool = False
        self.toggle_pressed: bool = False
        self.dragging: bool = False
        self.last_drag_x: int = 0
        self.last_drag_y: int = 0

        # 绘制策略（延迟初始化，避免启动卡顿）
        self._draw_strategies: Dict[str, DrawStrategy] = {}
        self.mode: str = "side_by_side"

        # 导入配置
        self.config = Config

        # 初始化各个管理模块
        self.ui_manager = UIManager(self)
        self.file_manager = FileManager(self)
        self.view_controller = ViewController(self)
        self.psnr_calculator = PSNRCalculator(self)

        # UI初始化常数
        self._tk_anchor_nw: tk._tkinter.TkinterAnchor = tk.NW  # 用于避免重复导入tkinter

        self.ui_manager.build_ui()

        # 初始化模式
        self.ui_manager.mode_var.set("并排对比")
        self.ui_manager.on_mode_change()

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

    # 保持对各模块的引用以维持向后兼容性
    @property
    def canvas_left(self):
        return self.ui_manager.canvas_left

    @property
    def canvas_right(self):
        return self.ui_manager.canvas_right

    @property
    def zoom(self):
        return self.view_controller.zoom

    @zoom.setter
    def zoom(self, value):
        self.view_controller.zoom = value

    @property
    def pan_x(self):
        return self.view_controller.pan_x

    @pan_x.setter
    def pan_x(self, value):
        self.view_controller.pan_x = value

    @property
    def pan_y(self):
        return self.view_controller.pan_y

    @pan_y.setter
    def pan_y(self, value):
        self.view_controller.pan_y = value

    @property
    def _current_psnr(self):
        return self.psnr_calculator.current_psnr

    @_current_psnr.setter
    def _current_psnr(self, value):
        self.psnr_calculator.current_psnr = value

    @property
    def res_lbl(self):
        return self.ui_manager.res_lbl

    @property
    def zoom_lbl(self):
        return self.ui_manager.zoom_lbl

    @property
    def status_lbl(self):
        return self.ui_manager.status_lbl

    @property
    def folder_status_label(self):
        return self.ui_manager.folder_status_label

    @property
    def mode_var(self):
        return self.ui_manager.mode_var

    @property
    def compare_mode_var(self):
        return self.ui_manager.compare_mode_var

    @property
    def page_label(self):
        return self.ui_manager.page_label

    @property
    def width_var(self):
        return self.ui_manager.width_var

    @property
    def height_var(self):
        return self.ui_manager.height_var

    @property
    def single_frame(self):
        return self.ui_manager.single_frame

    @property
    def folder_frame(self):
        return self.ui_manager.folder_frame

    @property
    def _psnr_calculation_in_progress(self):
        return self.psnr_calculator._calculation_in_progress

    @_psnr_calculation_in_progress.setter
    def _psnr_calculation_in_progress(self, value):
        self.psnr_calculator._calculation_in_progress = value

    @property
    def _psnr_thread(self):
        return self.psnr_calculator._psnr_thread

    @_psnr_thread.setter
    def _psnr_thread(self, value):
        self.psnr_calculator._psnr_thread = value

    # 重定向方法调用到对应模块
    def set_loading(self, flag, text=""):
        self.ui_manager.set_loading(flag, text)

    def load_im1(self):
        self.file_manager.load_im1()

    def load_im2(self):
        self.file_manager.load_im2()

    def update_path_lbl(self):
        pass  # 保留以维持兼容性

    # 重定向交互方法到ui_manager
    def on_b1_down(self, event):
        self.ui_manager.on_b1_down(event)

    def on_b1_move(self, event):
        self.ui_manager.on_b1_move(event)

    def on_b1_up(self, event):
        self.ui_manager.on_b1_up(event)

    def on_move(self, event):
        self.ui_manager.on_move(event)

    def on_key_press(self, event):
        self.ui_manager.on_key_press(event)

    def on_mouse_wheel(self, event):
        self.ui_manager.on_mouse_wheel(event)

    # 重定向视图控制方法到view_controller
    def zoom_in(self):
        self.view_controller.zoom_in()

    def zoom_out(self):
        self.view_controller.zoom_out()

    def zoom_1x(self):
        self.view_controller.zoom_1x()

    def fit_win(self):
        self.view_controller.fit_win()

    # 重定向画布到图像坐标转换
    def canvas_to_image(self, cx, cy, for_left=True):
        return self.view_controller.canvas_to_image(cx, cy, for_left)

    # 重定向绘制辅助方法到view_controller
    def _get_disp_image(self, im: Optional[Image.Image]) -> Optional[Image.Image]:
        """返回缓存的缩放图像，使用LRU缓存策略"""
        return self.view_controller.get_disp_image(im)

    def _image_display_params_for_canvas(self, im, canvas):
        """计算图像在画布上的显示参数"""
        return self.view_controller.image_display_params_for_canvas(im, canvas)

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

    # 重定向PSNR计算方法到psnr_calculator
    def _start_psnr_calculation(self):
        self.psnr_calculator.start_calculation()

    def _update_status_with_psnr(self):
        self.ui_manager._update_status_with_psnr()

    # 重定向文件夹对比方法到file_manager
    def switch_compare_mode(self):
        self.ui_manager.switch_compare_mode()

    def load_folder1(self):
        self.file_manager.load_folder1()

    def load_folder2(self):
        self.file_manager.load_folder2()

    def set_uniform_size(self):
        self.file_manager.set_uniform_size()

    def prev_image(self):
        self.file_manager.prev_image()

    def next_image(self):
        self.file_manager.next_image()

    def load_current_image_pair(self):
        self.file_manager.load_current_image_pair()

    # 重定向UI状态更新方法到ui_manager
    def _update_folder_status(self):
        self.ui_manager.update_folder_status()

    def _update_page_label(self):
        self.ui_manager.update_page_label()

    # 重定向其他方法到对应的模块
    def toggle(self):
        """切换模式的通用方法"""
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
