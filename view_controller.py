#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视图控制器 - 处理视图状态和控制逻辑
"""

from typing import Optional, Tuple
from PIL import Image
from image_utils import get_disp_image_scaled


class ViewController:
    """视图状态和控制逻辑"""

    def __init__(self, app):
        self.app = app

        # 视图参数
        self.zoom: float = 1.0
        self.pan_x: float = 0.0
        self.pan_y: float = 0.0

        # 交互状态（与app共享，保持原有逻辑）
        # self.app.dragging
        # self.app.slider_drag
        # self.app.last_drag_x
        # self.app.last_drag_y

    def zoom_in(self):
        """放大视图"""
        self.app.zoom *= 1.25
        self.app.zoom = min(self.app.zoom, self.app.config.ZOOM_MAX)
        self.app.schedule_refresh(immediate=True)

    def zoom_out(self):
        """缩小视图"""
        self.app.zoom /= 1.25
        self.app.zoom = max(self.app.zoom, self.app.config.ZOOM_MIN)
        self.app.schedule_refresh(immediate=True)

    def zoom_1x(self):
        """重置缩放为100%"""
        self.app.zoom = 1.0
        self.app.schedule_refresh(immediate=True)

    def fit_win(self):
        """适应窗口大小"""
        # auto compute zoom to fit the bigger of the two images into canvas_left (or both)
        cw, ch = self.app.ui_manager.canvas_left.winfo_width(), self.app.ui_manager.canvas_left.winfo_height()
        if cw <= 1 or ch <= 1:
            return
        # choose reference image if available
        im = self.app.im1_orig or self.app.im2_orig
        if im is None:
            return
        # compute scale to fit whole image into canvas
        w_scale = cw / im.width
        h_scale = ch / im.height
        new_zoom = min(w_scale, h_scale)
        new_zoom = max(0.01, new_zoom)
        self.app.zoom = new_zoom
        self.app.pan_x, self.app.pan_y = 0.0, 0.0
        self.app.ui_manager.zoom_lbl.config(text=f"缩放: {int(self.app.zoom*100)}%")
        self.app.schedule_refresh(immediate=True)

    def get_disp_image(self, im: Optional[Image.Image]) -> Optional[Image.Image]:
        """返回缓存的缩放图像，使用LRU缓存策略"""
        return get_disp_image_scaled(im, self.app.zoom, self.app._disp_cache)

    def image_display_params_for_canvas(self, im, canvas):
        """计算图像在画布上的显示参数"""
        disp = self.get_disp_image(im)
        if disp is None:
            return None, 0, 0
        cw, ch = canvas.winfo_width(), canvas.winfo_height()
        # center the image in canvas, considering pan
        left = int((cw - disp.width) / 2 + self.app.pan_x * cw)
        top = int((ch - disp.height) / 2 + self.app.pan_y * ch)
        return disp, left, top

    def canvas_to_image(self, cx, cy, for_left=True):
        """画布坐标转图像坐标"""
        canvas = self.app.ui_manager.canvas_left if for_left else self.app.ui_manager.canvas_right
        disp, left, top = self.image_display_params_for_canvas(self.app.im1_orig, canvas)
        if disp is None:
            return 0, 0
        ix = int((cx - left) / max(1, disp.width) * self.app.im1_orig.width)
        iy = int((cy - top) / max(1, disp.height) * self.app.im1_orig.height)
        return ix, iy
