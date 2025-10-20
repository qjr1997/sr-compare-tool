#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图像处理模块 - 图像加载、处理和计算功能
"""

import traceback
import threading
import math
from pathlib import Path
from typing import Optional, Tuple, List
from collections import OrderedDict
from PIL import Image
import tkinter as tk
from config import Config, RESAMPLE_LANCZOS
import numpy as np


def load_single_image(path: str) -> Optional[Image.Image]:
    """加载单个图像文件"""
    try:
        im = Image.open(path)
        # 关键修复：16-bit 图像缩放到 8-bit
        if im.mode == 'I;16':
            im = im.point(lambda x: x * (Config.MAX_8BIT_PIXEL / Config.MAX_16BIT_PIXEL)).convert('L')
        try:
            im = im.convert("RGB")
        except Exception:
            im = im.copy().convert("RGB")
        return im
    except Exception as e:
        print("加载图像出错:", e)
        traceback.print_exc()
        return None


def load_image_pair(img1_path: str, img2_path: str,
                   uniform_size: Optional[Tuple[int, int]] = None) -> Tuple[Optional[Image.Image], Optional[Image.Image]]:
    """加载图像对，用于文件夹对比"""
    try:
        im1 = load_single_image(img1_path)
        im2 = load_single_image(img2_path)

        # 统一图像尺寸（如果启用）
        if uniform_size and im1 and im2:
            im1 = im1.resize(uniform_size, RESAMPLE_LANCZOS)
            im2 = im2.resize(uniform_size, RESAMPLE_LANCZOS)

        return im1, im2
    except Exception as e:
        print("加载图像对出错:", e)
        traceback.print_exc()
        return None, None


def align_images_to_same_size(im1_raw: Image.Image, im2_raw: Image.Image) -> Tuple[Image.Image, Image.Image]:
    """自动对齐两张图像到相同尺寸，保持宽高比（缩放后居中放置）"""
    if not (im1_raw and im2_raw):
        return im1_raw, im2_raw

    w1, h1 = im1_raw.size
    w2, h2 = im2_raw.size

    if (w1, h1) == (w2, h2):
        # 如果原始尺寸相同，直接设置为原始图像
        return im1_raw, im2_raw

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
        new_im1 = Image.new("RGB", (target_w, target_h), Config.ALIGN_BG_COLOR)  # 用灰色背景
        scaled_im1 = im1_raw.resize((new_w1, new_h1), RESAMPLE_LANCZOS)
        x = (target_w - new_w1) // 2
        y = (target_h - new_h1) // 2
        new_im1.paste(scaled_im1, (x, y))
        im1_orig = new_im1
    else:
        im1_orig = im1_raw

    # 基于原始图像重新调整图像2
    if (w2, h2) != (target_w, target_h):
        # 计算缩放比例，保持宽高比
        scale2 = min(target_w / w2, target_h / h2)
        new_w2 = int(w2 * scale2)
        new_h2 = int(h2 * scale2)

        # 创建新图像，居中放置缩放后的图像
        new_im2 = Image.new("RGB", (target_w, target_h), Config.ALIGN_BG_COLOR)  # 用灰色背景
        scaled_im2 = im2_raw.resize((new_w2, new_h2), RESAMPLE_LANCZOS)
        x = (target_w - new_w2) // 2
        y = (target_h - new_h2) // 2
        new_im2.paste(scaled_im2, (x, y))
        im2_orig = new_im2
    else:
        im2_orig = im2_raw

    return im1_orig, im2_orig


def calculate_psnr_sync(im1: Image.Image, im2: Image.Image) -> float:
    """同步计算PSNR（在后台线程中调用，使用NumPy矢量化提升性能）

    Args:
        im1: 第一张图像
        im2: 第二张图像

    Returns:
        计算得到的PSNR值
    """
    try:
        im1 = im1.convert("RGB")
        im2 = im2.convert("RGB")

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

    except Exception as e:
        print(f"PSNR计算出错: {e}")
        return 0.0


def get_disp_image_scaled(im: Image.Image, zoom: float, cache: OrderedDict,
                         max_cache_size: int = Config.MAX_CACHE_SIZE) -> Optional[Image.Image]:
    """返回缓存的缩放图像，使用LRU缓存策略

    Args:
        im: 原始图像
        zoom: 缩放比例
        cache: 缓存字典
        max_cache_size: 最大缓存大小

    Returns:
        缩放后的图像或None
    """
    if im is None:
        return None

    key = (id(im), round(zoom, 6))

    if key in cache:
        # 移动到最频繁使用位置
        cache.move_to_end(key)
        return cache[key]

    try:
        nw = max(1, int(im.width * zoom))
        nh = max(1, int(im.height * zoom))
        disp = im.resize((nw, nh), RESAMPLE_LANCZOS)

        # 添加到缓存，如果满员则移除最旧的
        if len(cache) >= max_cache_size:
            cache.popitem(last=False)  # 移除最旧的 (FIFO)

        cache[key] = disp
        return disp

    except Exception as e:
        print(f"缩放图像失败: {e}")
        return None


def find_matching_images(folder1_files: List[str], folder2_files: List[str]) -> Tuple[List[Tuple[str, str]], int]:
    """匹配两个文件夹中的图像文件

    Args:
        folder1_files: 文件夹1的文件列表
        folder2_files: 文件夹2的文件列表

    Returns:
        匹配的图像对列表和总图像数量
    """
    from pathlib import Path

    # 提取文件名（不含扩展名）的公共前缀部分
    def extract_common_prefix(path):
        stem = Path(path).stem
        return stem

    # 创建映射关系
    folder2_map = {}
    for img2_path in folder2_files:
        prefix2 = extract_common_prefix(img2_path)
        folder2_map[prefix2] = img2_path

    # 配对图像
    matched_pairs = []
    for img1_path in folder1_files:
        prefix1 = extract_common_prefix(img1_path)
        if prefix1 in folder2_map:
            matched_pairs.append((img1_path, folder2_map[prefix1]))

    total_images = len(matched_pairs)
    return matched_pairs, total_images


def load_folder_images(folder_path: str) -> List[str]:
    """加载文件夹中的图像文件列表"""
    from pathlib import Path
    import glob

    image_extensions = ['*.jpg', '*.jpeg', '*.png', '*.bmp', '*.tiff', '*.tif']
    image_files = []

    for ext in image_extensions:
        pattern = Path(folder_path) / ext
        image_files.extend(glob.glob(str(pattern)))

    image_files.sort()  # 按文件名排序
    return image_files
