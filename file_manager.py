#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件管理器 - 处理文件和文件夹操作管理
"""

from tkinter import filedialog, messagebox
from pathlib import Path
import threading
import traceback
from typing import Optional, Tuple, Any, Callable

from PIL import Image
from image_utils import load_single_image, load_image_pair, align_images_to_same_size, \
    find_matching_images, load_folder_images


class FileManager:
    """文件和文件夹操作管理"""

    def __init__(self, app):
        self.app = app
        self.root = app.root

    def load_im1(self):
        """加载第一张图像"""
        p = filedialog.askopenfilename(title="选择第一张图像",
                                       filetypes=self.app.config.SUPPORTED_FORMATS)
        if p:
            self.app.im1_path = p
            self._update_path_display()
            # 确保对话框关闭后窗口获得焦点
            self.root.focus_force()
            threading.Thread(target=self._load_image_thread, args=(1, p), daemon=True).start()

    def load_im2(self):
        """加载第二张图像"""
        p = filedialog.askopenfilename(title="选择第二张图像",
                                       filetypes=self.app.config.SUPPORTED_FORMATS)
        if p:
            self.app.im2_path = p
            self._update_path_display()
            # 确保对话框关闭后窗口获得焦点
            self.root.focus_force()
            threading.Thread(target=self._load_image_thread, args=(2, p), daemon=True).start()

    def _update_path_display(self):
        """更新路径显示"""
        pass  # 状态显示在其他地方处理

    def _load_image_thread(self, slot, path):
        """后台线程加载单张图像"""
        try:
            self.app.ui_manager.set_loading(True, f"加载 {Path(path).name} ...")
            im = load_single_image(path)

            def finish():
                # 保存原始图像
                if slot == 1:
                    self.app.im1_raw = im
                    self.app.im1_orig = im
                else:
                    self.app.im2_raw = im
                    self.app.im2_orig = im

                # 多分辨率对齐：如果两图都已加载且大小不同，自动对齐到最大尺寸
                if self.app.im1_orig and self.app.im2_orig and self.app.im1_orig.size != self.app.im2_orig.size:
                    self.app.im1_orig, self.app.im2_orig = align_images_to_same_size(self.app.im1_raw, self.app.im2_raw)
                    self.app.ui_manager.res_lbl.config(
                        text=f"图1: {self.app.im1_orig.size} | 图2: {self.app.im2_orig.size} (已对齐)")

                self.app._disp_cache.clear()
                self.app.im_diff = None  # reset diff on new image load
                self.app.ui_manager.set_loading(False, "")
                if not self.app.ui_manager.res_lbl.cget("text").endswith("(已对齐)"):  # 避免覆盖对齐信息
                    self.app.ui_manager.res_lbl.config(
                        text=f"图1: {self.app.im1_orig.size if self.app.im1_orig else '-'} | 图2: {self.app.im2_orig.size if self.app.im2_orig else '-'}")
                self.app.zoom, self.app.pan_x, self.app.pan_y = 1.0, 0.0, 0.0
                self.app.split_pos = 0.5
                try:
                    self.app.view_controller.fit_win()
                except Exception:
                    pass
                # ---- 新增：确保加载后模式刷新，拖动逻辑生效 ----
                self.app.ui_manager.on_mode_change()
                self.app.schedule_refresh(immediate=True)

                # 加载完成后，如果两张图都存在，自动计算PSNR并更新状态栏
                if self.app.im1_orig and self.app.im2_orig and self.app.im1_orig.size == self.app.im2_orig.size:
                    self.app.psnr_calculator.start_calculation()
                else:
                    self.app.psnr_calculator.current_psnr = None
                    self.app.ui_manager._update_status_with_psnr()

            self.root.after(0, finish)
        except Exception as e:
            self.root.after(0, lambda: (self.app.ui_manager.set_loading(False), self.app.ui_manager.status_lbl.config(text="加载失败")))
            traceback.print_exc()

    # ---------------- 文件夹对比功能 ----------------
    def load_folder1(self):
        """选择文件夹1"""
        folder = filedialog.askdirectory(title="选择图1文件夹")
        if folder:
            self.app.folder1_path = folder
            self.app.folder1_images = load_folder_images(folder)
            self.app.ui_manager.update_folder_status()

            # 如果两个文件夹都已选择，自动匹配
            if self.app.folder1_images and self.app.folder2_images:
                matched_pairs, self.app.total_images = find_matching_images(self.app.folder1_images, self.app.folder2_images)
                self.app.folder1_images = [pair[0] for pair in matched_pairs]
                self.app.folder2_images = [pair[1] for pair in matched_pairs]
                self.app.current_image_index = 0

                # 更新页面显示
                self.app.ui_manager.update_page_label()

                # 自动加载第一组图像
                if self.app.total_images > 0:
                    self.load_current_image_pair()
                else:
                    messagebox.showwarning("警告", "未找到匹配的图像文件对")

    def load_folder2(self):
        """选择文件夹2"""
        folder = filedialog.askdirectory(title="选择图2文件夹")
        if folder:
            self.app.folder2_path = folder
            self.app.folder2_images = load_folder_images(folder)
            self.app.ui_manager.update_folder_status()

            # 如果两个文件夹都已选择，自动匹配
            if self.app.folder1_images and self.app.folder2_images:
                matched_pairs, self.app.total_images = find_matching_images(self.app.folder1_images, self.app.folder2_images)
                self.app.folder1_images = [pair[0] for pair in matched_pairs]
                self.app.folder2_images = [pair[1] for pair in matched_pairs]
                self.app.current_image_index = 0

                # 更新页面显示
                self.app.ui_manager.update_page_label()

                # 自动加载第一组图像
                if self.app.total_images > 0:
                    self.load_current_image_pair()
                else:
                    messagebox.showwarning("警告", "未找到匹配的图像文件对")

    def set_uniform_size(self):
        """设置统一尺寸"""
        try:
            w = int(self.app.ui_manager.width_var.get())
            h = int(self.app.ui_manager.height_var.get())
            if w > 0 and h > 0:
                self.app.uniform_size = (w, h)
                messagebox.showinfo("设置成功", f"统一尺寸已设置为 {w}x{h}")
                # 如果当前在文件夹模式且有图像，重新加载当前图像对
                if self.app.folder_mode and self.app.total_images > 0:
                    self.load_current_image_pair()
            else:
                messagebox.showerror("错误", "尺寸必须大于0")
        except ValueError:
            messagebox.showerror("错误", "请输入有效的整数尺寸")

    def prev_image(self):
        """切换到上一张图像"""
        if self.app.folder_mode and self.app.total_images > 0:
            self.app.current_image_index = (self.app.current_image_index - 1) % self.app.total_images
            self.load_current_image_pair()

    def next_image(self):
        """切换到下一张图像"""
        if self.app.folder_mode and self.app.total_images > 0:
            self.app.current_image_index = (self.app.current_image_index + 1) % self.app.total_images
            self.load_current_image_pair()

    def load_current_image_pair(self):
        """加载当前索引的图像对"""
        if not (self.app.folder_mode and self.app.total_images > 0):
            return

        if self.app.current_image_index >= self.app.total_images:
            self.app.current_image_index = 0

        img1_path = self.app.folder1_images[self.app.current_image_index]
        img2_path = self.app.folder2_images[self.app.current_image_index]

        # 加载并处理图像
        threading.Thread(target=self._load_image_pair_thread,
                        args=(img1_path, img2_path), daemon=True).start()

    def _load_image_pair_thread(self, img1_path, img2_path):
        """后台线程加载图像对"""
        try:
            self.app.ui_manager.set_loading(True, f"加载图像对 {self.app.current_image_index + 1}/{self.app.total_images}...")

            im1, im2 = load_image_pair(img1_path, img2_path, self.app.uniform_size)

            def finish():
                # 保存图像
                self.app.im1_orig = im1
                self.app.im2_orig = im2
                self.app.im1_raw = im1
                self.app.im2_raw = im2

                # 更新路径和标签
                self.app.im1_path = img1_path
                self.app.im2_path = img2_path

                # 清除缓存
                self.app._disp_cache.clear()
                self.app.im_diff = None

                # 重置视图
                self.app.zoom, self.app.pan_x, self.app.pan_y = 1.0, 0.0, 0.0
                self.app.split_pos = 0.5

                # 适应窗口
                try:
                    self.app.view_controller.fit_win()
                except Exception:
                    pass

                # 更新UI
                filename1 = Path(img1_path).name
                filename2 = Path(img2_path).name
                self.app.ui_manager.res_lbl.config(text=f"图1: {filename1} | 图2: {filename2}")
                self.app.ui_manager.update_page_label()

                self.app.ui_manager.set_loading(False, "")

                # 恢复窗口焦点，确保快捷键可以正常工作
                self.root.focus_force()

                # 刷新显示
                self.app.ui_manager.on_mode_change()
                self.app.schedule_refresh(immediate=True)

                # 计算PSNR
                if self.app.im1_orig and self.app.im2_orig and self.app.im1_orig.size == self.app.im2_orig.size:
                    self.app.psnr_calculator.start_calculation()

            self.root.after(0, finish)

        except Exception as e:
            self.root.after(0, lambda: (self.app.ui_manager.set_loading(False), self.app.ui_manager.status_lbl.config(text=f"加载失败: {str(e)}")))
            print("加载图像对出错:", e)
            traceback.print_exc()
