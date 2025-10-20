#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
超分图像对比工具 - 优化版（并排两个画布同步缩放；其他模式单画布；滑动更快；局部对比固定裁剪100x100放大2x）
请直接替换原脚本运行。
"""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
import threading
import time
import traceback
from pathlib import Path
from datetime import datetime
import platform

# choose resampling constants depending on PIL version
try:
    RESAMPLE_LANCZOS = Image.Resampling.LANCZOS
    RESAMPLE_BILINEAR = Image.Resampling.BILINEAR
except Exception:
    RESAMPLE_LANCZOS = Image.LANCZOS
    RESAMPLE_BILINEAR = Image.BILINEAR


class SRCompareApp:
    def __init__(self, root):
        self.root = root
        root.title("超分图像对比工具 - 优化版")
        self.im1_orig = None
        self.im2_orig = None
        self.im1_path = ""
        self.im2_path = ""
        self._disp_cache = {}
        self._refresh_after_id = None
        self._loading = False

        # view params
        self.zoom = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0

        self.toggle_idx = 1
        self.split_pos = 0.5
        self.slider_drag = False
        self.toggle_pressed = False

        self.dragging = False
        self.last_drag_x = 0
        self.last_drag_y = 0

        # magnifier params
        self.local_crop_size = 100
        self.local_zoom = 2.0

        self.build_ui()

        # ---- 新增：初始化模式，保证首次显示可拖动 ----
        self.mode_var.set("并排对比")
        self.on_mode_change()

        self.schedule_refresh(immediate=True)

    def build_ui(self):
        main = ttk.Frame(self.root)
        main.pack(fill=tk.BOTH, expand=True)

        # 上方控制区
        ctrl = ttk.Frame(main)
        ctrl.pack(fill=tk.X, side=tk.TOP, padx=6, pady=6)

        # 图像加载区
        load_row = ttk.Frame(ctrl)
        load_row.pack(side=tk.LEFT, padx=4)
        ttk.Button(load_row, text="加载图1", width=10, command=self.load_im1).pack(side=tk.LEFT, padx=2)
        ttk.Button(load_row, text="加载图2", width=10, command=self.load_im2).pack(side=tk.LEFT, padx=2)
        self.res_lbl = ttk.Label(load_row, text="图1: - | 图2: -")
        self.res_lbl.pack(side=tk.LEFT, padx=10)

        # 模式选择
        mode_row = ttk.Frame(ctrl)
        mode_row.pack(side=tk.LEFT, padx=12)
        ttk.Label(mode_row, text="模式:").pack(side=tk.LEFT)
        self.mode_var = tk.StringVar(value="并排对比")
        mode_cb = ttk.Combobox(mode_row, textvariable=self.mode_var,
                               values=["并排对比", "快速切换", "滑动对比", "局部放大"],
                               width=10, state="readonly")
        mode_cb.bind("<<ComboboxSelected>>", self.on_mode_change)
        mode_cb.pack(side=tk.LEFT, padx=4)

        # 缩放控制
        zoom_row = ttk.Frame(ctrl)
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

        # 事件绑定（保持原有逻辑不变）
        self.canvas_left.bind("<Enter>", lambda e: self.canvas_left.focus_set())
        self.canvas_left.bind("<ButtonPress-1>", self.on_b1_down)
        self.canvas_left.bind("<B1-Motion>", self.on_b1_move)
        self.canvas_left.bind("<ButtonRelease-1>", self.on_b1_up)
        self.canvas_left.bind("<Motion>", self.on_move)
        self.canvas_left.bind("<MouseWheel>", self.on_mouse_wheel)
        self.canvas_left.bind("<Configure>", lambda e: self.schedule_refresh(immediate=True))

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
                if slot == 1:
                    self.im1_orig = im
                else:
                    self.im2_orig = im
                self._disp_cache.clear()
                self.set_loading(False, "")
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

            self.root.after(0, finish)
        except Exception as e:
            self.root.after(0, lambda: (self.set_loading(False), self.status_lbl.config(text="加载失败")))
            print("加载图像出错:", e)
            traceback.print_exc()

    # ---------------- interactions ----------------
    def on_mode_change(self, _=None):
        mode_map = {"并排对比": "side_by_side", "快速切换": "toggle",
                    "滑动对比": "slider", "局部放大": "magnifier"}
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
                 "side_by_side": "并排对比：两个画布并排显示，缩放同步"}
        self.status_lbl.config(text=hints.get(self.mode, ""))

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
    def _get_disp_image(self, im):
        """return cached/resized image according to current zoom"""
        if im is None:
            return None
        key = (id(im), round(self.zoom, 6))
        if key in self._disp_cache:
            return self._disp_cache[key]
        try:
            nw = max(1, int(im.width * self.zoom))
            nh = max(1, int(im.height * self.zoom))
            disp = im.resize((nw, nh), RESAMPLE_LANCZOS)
            self._disp_cache[key] = disp
            return disp
        except Exception:
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

    # ---------------- rendering modes ----------------
    def draw_side_by_side(self):
        """左右两个画布分别绘制 im1 和 im2，保持相同的 zoom/pan（同步）"""
        # left canvas draw im1
        disp1, left1, top1 = self._image_display_params_for_canvas(self.im1_orig, self.canvas_left)
        if disp1:
            ph1 = ImageTk.PhotoImage(disp1)
            self.canvas_left.create_image(left1, top1, anchor=tk.NW, image=ph1, tags="img1")
            self.canvas_left.ph = ph1  # keep ref
        # right canvas draw im2 with same zoom/pan mapping
        disp2, left2, top2 = self._image_display_params_for_canvas(self.im2_orig, self.canvas_right)
        # But we must compute left2/top2 such that the center mapping corresponds:
        # We want centers to match relative to each canvas: both canvases use same pan_x/pan_y values,
        # so compute center positions separately
        if disp2:
            ph2 = ImageTk.PhotoImage(disp2)
            self.canvas_right.create_image(left2, top2, anchor=tk.NW, image=ph2, tags="img2")
            self.canvas_right.ph = ph2

    def draw_toggle_single(self):
        cur = self.im1_orig if self.toggle_idx == 1 else self.im2_orig
        disp, left, top = self._image_display_params_for_canvas(cur, self.canvas_left)
        if disp:
            ph = ImageTk.PhotoImage(disp)
            self.canvas_left.create_image(left, top, anchor=tk.NW, image=ph, tags="img")
            self.canvas_left.ph = ph

    def draw_slider_single(self):
        """单画布滑动对比：快速响应，不保留边缘混合（直接 paste），并在分界处加红色竖线"""
        cw, ch = self.canvas_left.winfo_width(), self.canvas_left.winfo_height()
        if cw <= 1 or ch <= 1:
            return

        # 创建背景
        base = Image.new("RGB", (cw, ch), (40, 40, 40))

        # 获取缩放后的显示图像
        disp1, left1, top1 = self._image_display_params_for_canvas(self.im1_orig, self.canvas_left)
        disp2 = self._get_disp_image(self.im2_orig)

        # 先贴 im1
        if disp1:
            base.paste(disp1, (left1, top1))

        # 计算 im2 的贴图位置
        if disp2:
            disp2_exact, left2, top2 = self._image_display_params_for_canvas(self.im2_orig, self.canvas_left)
            # 计算分割线在 canvas 上的 x 坐标
            if disp1:
                iw_disp = disp1.width
                split_x_canvas = left1 + int(iw_disp * self.split_pos)
            else:
                split_x_canvas = int(cw * self.split_pos)

            # 创建 mask，右侧显示 im2
            px = split_x_canvas - left2
            px = max(0, min(disp2_exact.width, px))
            mask = Image.new("L", (disp2_exact.width, disp2_exact.height), 0)
            if px < disp2_exact.width:
                mask.paste(255, (px, 0, disp2_exact.width, disp2_exact.height))
            base.paste(disp2_exact, (left2, top2), mask)

        # 在分界处绘制红色竖线
        if disp1:
            from PIL import ImageDraw
            draw = ImageDraw.Draw(base)
            draw.line([(split_x_canvas, 0), (split_x_canvas, ch)], fill=(255, 0, 0), width=2)

        # 显示到 canvas
        ph = ImageTk.PhotoImage(base)
        self.canvas_left.create_image(0, 0, anchor=tk.NW, image=ph, tags="img")
        self.canvas_left.ph = ph

    def draw_magnifier_single(self):
        """局部放大镜：裁剪 100x100 放大 2x，靠边时不填充，直接显示背景"""
        cw, ch = self.canvas_left.winfo_width(), self.canvas_left.winfo_height()
        if cw <= 1 or ch <= 1:
            return

        # 背景显示图1（缩放后）
        disp, left, top = self._image_display_params_for_canvas(self.im1_orig, self.canvas_left)
        if disp:
            ph = ImageTk.PhotoImage(disp)
            self.canvas_left.create_image(left, top, anchor=tk.NW, image=ph)
            self.canvas_left.ph_main = ph

        # 鼠标位置对应图像坐标
        mx = self.canvas_left.winfo_pointerx() - self.canvas_left.winfo_rootx()
        my = self.canvas_left.winfo_pointery() - self.canvas_left.winfo_rooty()
        ix, iy = self.canvas_to_image(mx, my, for_left=True)

        half = self.local_crop_size // 2

        # 裁剪区域，不超出图像边界
        left_i = max(0, ix - half)
        top_i = max(0, iy - half)
        right_i = min(self.im1_orig.width, ix + half)
        bottom_i = min(self.im1_orig.height, iy + half)

        reg1 = self.im1_orig.crop((left_i, top_i, right_i, bottom_i))
        reg2 = self.im2_orig.crop((left_i, top_i, right_i, bottom_i))

        # 放大到 200x200（根据实际裁剪大小放大）
        ds_w = int(reg1.width * self.local_zoom)
        ds_h = int(reg1.height * self.local_zoom)
        reg1 = reg1.resize((ds_w, ds_h), RESAMPLE_BILINEAR)
        reg2 = reg2.resize((ds_w, ds_h), RESAMPLE_BILINEAR)

        # 拼接两个放大图
        out = Image.new("RGBA", (ds_w * 2, ds_h), (0, 0, 0, 0))  # 透明背景
        out.paste(reg1, (0, 0))
        out.paste(reg2, (ds_w, 0))

        ph = ImageTk.PhotoImage(out)

        # 放大镜位置跟随鼠标
        offset_x, offset_y = 20, 20
        x = min(max(0, mx + offset_x), cw - out.width)
        y = min(max(0, my + offset_y), ch - out.height)
        self.canvas_left.create_image(x, y, anchor=tk.NW, image=ph, tags="local_compare")
        self.canvas_left.ph_local = ph

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

    def _do_refresh(self):
        # clear canvas and draw according to mode
        try:
            self.canvas_left.delete("all")
            self.canvas_right.delete("all")
            mode = getattr(self, "mode", "side_by_side")
            if mode == "side_by_side":
                # if both images available, ensure both canvases visible
                self.draw_side_by_side()
            elif mode == "toggle":
                # single canvas, show one or the other
                self.draw_toggle_single()
            elif mode == "slider":
                self.draw_slider_single()
            elif mode == "magnifier":
                self.draw_magnifier_single()
            # update status zoom text
            self.zoom_lbl.config(text=f"缩放: {int(self.zoom*100)}%")
        except Exception as e:
            print("刷新出错:", e)
            traceback.print_exc()

    # ---------------- utility / debug ----------------
    def toggle(self):
        if self.mode == "toggle" and self.im1_orig and self.im2_orig:
            self.toggle_idx = 3 - self.toggle_idx
            self.schedule_refresh(immediate=True)


def main():
    root = tk.Tk()
    root.geometry("1200x700")
    app = SRCompareApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
