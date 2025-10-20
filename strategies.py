#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
策略模式模块 - 图像绘制策略
"""

from abc import ABC, abstractmethod
from typing import Optional, Tuple, List
import time
from PIL import Image, ImageDraw
import numpy as np
from config import Config, RESAMPLE_LANCZOS, RESAMPLE_BILINEAR


class DrawStrategy(ABC):
    """绘制策略抽象基类"""

    def __init__(self, app: 'SRCompareApp'):
        self.app = app

    @abstractmethod
    def draw(self) -> None:
        """执行绘制操作"""
        pass

    def _create_photo_ref(self, image) -> Optional[any]:
        """创建PhotoImage引用并缓存"""
        try:
            from PIL import ImageTk
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
            app.canvas_left.create_image(left1, top1, anchor=app._tk_anchor_nw, image=photo1, tags="img1")

        # 右画布绘制图2
        disp2, left2, top2 = app._image_display_params_for_canvas(app.im2_orig, app.canvas_right)
        if disp2 and (photo2 := self._create_photo_ref(disp2)):
            app.canvas_right.create_image(left2, top2, anchor=app._tk_anchor_nw, image=photo2, tags="img2")


class ToggleStrategy(DrawStrategy):
    """快速切换绘制策略"""

    def draw(self) -> None:
        """单画布显示当前选中的图像"""
        app = self.app
        current_img = app.im1_orig if app.toggle_idx == 1 else app.im2_orig
        disp, left, top = app._image_display_params_for_canvas(current_img, app.canvas_left)
        if disp and (photo := self._create_photo_ref(disp)):
            app.canvas_left.create_image(left, top, anchor=app._tk_anchor_nw, image=photo, tags="img")


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
            app.canvas_left.create_image(0, 0, anchor=app._tk_anchor_nw, image=photo, tags="img")

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
            app.canvas_left.create_image(left, top, anchor=app._tk_anchor_nw, image=photo_main, tags="main")

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
            app.canvas_left.create_image(x, y, anchor=app._tk_anchor_nw, image=photo_local, tags="magnifier")

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

        # 检查裁剪区域是否有效，避免PIL报错
        if left_i >= right_i or top_i >= bottom_i:
            return None

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
                app.canvas_left.create_image(left, top, anchor=app._tk_anchor_nw, image=photo, tags="img")

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
