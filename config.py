#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置模块 - 应用配置常量
"""

from typing import Optional, Dict, Tuple, Any, Callable, Union
import tkinter as tk

# 选择合适的采样常量根据PIL版本
try:
    RESAMPLE_LANCZOS = __import__('PIL').Image.Resampling.LANCZOS
    RESAMPLE_BILINEAR = __import__('PIL').Image.Resampling.BILINEAR
except Exception:
    RESAMPLE_LANCZOS = __import__('PIL').Image.LANCZOS
    RESAMPLE_BILINEAR = __import__('PIL').Image.BILINEAR


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
