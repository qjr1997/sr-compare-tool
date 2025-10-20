#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PSNR计算器 - 处理PSNR计算和管理
"""

import threading
from typing import Optional
from image_utils import calculate_psnr_sync


class PSNRCalculator:
    """PSNR计算和管理"""

    def __init__(self, app):
        self.app = app
        self.root = app.root

        # PSNR相关状态
        self.current_psnr: Optional[float] = None
        self._psnr_thread: Optional[threading.Thread] = None
        self._calculation_in_progress: bool = False

    def start_calculation(self) -> None:
        """启动后台PSNR计算"""
        if not (self.app.im1_orig and self.app.im2_orig and self.app.im1_orig.size == self.app.im2_orig.size):
            self.current_psnr = None
            self.app.ui_manager._update_status_with_psnr()
            return

        # 如果已经有计算在进行，先取消
        if self._calculation_in_progress:
            return

        # 启动新线程进行计算
        self._calculation_in_progress = True
        self._psnr_thread = threading.Thread(target=self._calculate_psnr_thread, daemon=True)
        self._psnr_thread.start()

    def _calculate_psnr_thread(self) -> None:
        """后台线程计算PSNR"""
        try:
            psnr_value = calculate_psnr_sync(self.app.im1_orig, self.app.im2_orig)
            # 在主线程中更新UI
            self.root.after(0, lambda: self._on_psnr_calculated(psnr_value))
        except Exception as e:
            print(f"PSNR计算出错: {e}")
            self.root.after(0, lambda: self._on_psnr_calculation_failed())

    def _on_psnr_calculated(self, psnr_value: float) -> None:
        """PSNR计算完成回调"""
        self.current_psnr = psnr_value
        self._calculation_in_progress = False
        self.app.ui_manager._update_status_with_psnr()

    def _on_psnr_calculation_failed(self) -> None:
        """PSNR计算失败回调"""
        self.current_psnr = None
        self._calculation_in_progress = False
        self.app.ui_manager._update_status_with_psnr()
