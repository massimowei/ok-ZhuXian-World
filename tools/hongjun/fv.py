import sys
import os
import time
import traceback
import threading
import subprocess
from datetime import datetime

APP_VERSION = "2026-01-31.4-heavy" # 版本号更新
STEP3_FIXED_POS_2K = (1510, 476) # 保留作为参考，但主要逻辑已弃用

def is_admin():
    try:
        import ctypes

        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def verify_password():
    root = tk.Tk()
    root.withdraw()
    SECRET_KEY = os.environ.get("OK_ZXW_HONGJUN_KEY", "728690198")
    user_input = simpledialog.askstring("鸿钧系统", "请输入启动密码:", parent=root, show="*")
    if user_input == SECRET_KEY:
        root.destroy()
        return True
    root.destroy()
    sys.exit()

# --- 6. 图片配置 ---
IMG_AIM   = 'stepA.png'
IMG_FIRE  = 'redpoint1.png'
IMG_MAP   = 'stepB.png'
IMG_ENTER = 'stepC.png'

class BotFinalRelease:
    def __init__(self, root):
        self.root = root
        self.root.title("鸿钧极速版 (Heavy-Click Mode)")
        self.root.geometry("600x600")
        
        self.is_running = False
        self.status = 0 
        self.templates = {}
        self.dynamic_red_roi = None 
        self.last_log_time = 0.0
        self.last_step3_action_time = 0.0
        self.last_step3_log_time = 0.0
        self.scale_factor = 1.0
        self.aim_pos = None
        self.last_step1_wait_log_time = 0.0
        
        # 新增：任务计时变量
        self.mission_start_time = None
        
        tk.Label(root, text="[鸿钧] 强力排队版 | 解决高负载失效", fg="red", font=("微软雅黑", 14, "bold")).pack(pady=10)
        
        info_frame = tk.Frame(root)
        info_frame.pack(pady=5)
        self.res_info_lbl = tk.Label(info_frame, text="正在检测资源来源...", fg="gray", font=("Consolas", 9))
        self.res_info_lbl.pack()
        
        frame_status = tk.Frame(root, relief="groove", borderwidth=2)
        frame_status.pack(pady=10, fill="x", padx=20)
        self.status_lbl = tk.Label(frame_status, text="状态: 等待指令", fg="blue", font=("微软雅黑", 12))
        self.status_lbl.pack(pady=5)

        self.log_area = scrolledtext.ScrolledText(root, width=70, height=15)
        self.log_area.pack(pady=5, padx=10)
        
        btn_f = tk.Frame(root)
        btn_f.pack(pady=15)
        tk.Button(btn_f, text="🚀 启动挂机", bg="#90EE90", width=18, height=2, font=("微软雅黑", 10, "bold"), command=self.start).grid(row=0, column=0, padx=10)
        tk.Button(btn_f, text="🛑 停止", bg="#FFB6C1", width=15, height=2, font=("微软雅黑", 10, "bold"), command=self.stop).grid(row=0, column=1, padx=10)

        try:
            with mss.mss() as s: 
                self.monitor = s.monitors[1]
            base_w, base_h = 2560, 1440
            self.scale_factor = min(self.monitor['width'] / base_w, self.monitor['height'] / base_h)
        except Exception as e:
            messagebox.showerror("错误", f"获取屏幕失败: {e}")
            self.monitor = {'left': 0, 'top': 0, 'width': 2560, 'height': 1440}
            self.scale_factor = 1.0

        self.log(f"版本: {APP_VERSION}")
        self.log(f"屏幕: {self.monitor['width']}x{self.monitor['height']} | 缩放系数: {self.scale_factor:.2f}")
        self.load_images()

    def log(self, msg):
        t = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        self.log_area.insert(tk.END, f"[{t}] {msg}\n")
        self.log_area.see(tk.END)

    def get_resource_path(self, filename):
        if os.path.exists(filename):
            return filename, "外部文件 (优先)"
        if hasattr(sys, '_MEIPASS'):
            internal_path = os.path.join(sys._MEIPASS, filename)
            if os.path.exists(internal_path):
                return internal_path, "内置核心 (保底)"
        return None, "未找到"

    def load_images(self):
        loaded_count = 0
        source_msg = []
        
        for n in [IMG_AIM, IMG_FIRE, IMG_MAP, IMG_ENTER]:
            real_path, source_type = self.get_resource_path(n)
            
            if real_path:
                try:
                    img = cv2.imread(real_path)
                    if img is None:
                        raise ValueError("cv2.imread 读取失败")
                    if abs(self.scale_factor - 1.0) > 0.01:
                        new_w = max(1, int(img.shape[1] * self.scale_factor))
                        new_h = max(1, int(img.shape[0] * self.scale_factor))
                        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
                    self.templates[n] = {'data': cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), 'w': img.shape[1], 'h': img.shape[0]}
                    loaded_count += 1
                    source_msg.append(f"{n}: {source_type}")
                except Exception as e:
                    self.log(f"❌ 图片损坏 {n}: {e}")
            else:
                self.log(f"⚠️ 缺失图片: {n}")

        if loaded_count == 4:
            self.log("✅ 所有核心资源加载完毕。")
            if "外部" in str(source_msg):
                self.res_info_lbl.config(text="⚠️ 已优先加载外部配置", fg="orange")
            else:
                self.res_info_lbl.config(text="✅ 正在使用内置资源", fg="green")
        else:
            messagebox.showerror("严重错误", "关键图片缺失，脚本无法运行！")

    def fast_click(self, x, y):
        # 普通点击保持轻快
        pydirectinput.moveTo(x, y)
        pydirectinput.click()

    # --- 核心修改：重击模式 ---
    def heavy_click(self, x, y):
        """
        重击模式：应对高负载/掉帧场景
        1. 移动后悬停 0.1s 触发 UI Hover
        2. 按下持续 0.15s 穿透丢帧
        3. 连续操作 2 次
        """
        pydirectinput.moveTo(x, y)
        time.sleep(0.1) # 让游戏UI反应过来鼠标到了
        
        for _ in range(2):
            pydirectinput.mouseDown()
            time.sleep(0.15) # 增加按住时长
            pydirectinput.mouseUp()
            time.sleep(0.05)

    def find_fast(self, sct, img_name, roi=None):
        try:
            scan_area = roi if roi else self.monitor
            sct_img = sct.grab(scan_area)
            screen_gray = cv2.cvtColor(np.array(sct_img), cv2.COLOR_BGRA2GRAY)
            res = cv2.matchTemplate(screen_gray, self.templates[img_name]['data'], cv2.TM_CCOEFF_NORMED)
            _, mv, _, ml = cv2.minMaxLoc(res)
            
            if mv >= 0.8: # 保持 0.8 阈值
                offset_x = scan_area['left']
                offset_y = scan_area['top']
                return (ml[0] + self.templates[img_name]['w']//2 + offset_x, 
                        ml[1] + self.templates[img_name]['h']//2 + offset_y), mv
            return None, mv
        except:
            return None, 0.0

    def calculate_red_roi(self, aim_pos):
        if IMG_AIM not in self.templates: return
        w = self.templates[IMG_AIM]['w']
        h = self.templates[IMG_AIM]['h']
        btn_left = aim_pos[0] - w // 2
        btn_top  = aim_pos[1] - h // 2
        padding = 30
        roi_left = int(btn_left + w * 0.4) - padding
        roi_top  = int(btn_top) - padding
        roi_w    = int(w * 0.6) + (padding * 2)
        roi_h    = int(h * 0.75) + (padding * 2)
        self.dynamic_red_roi = {'left': max(0, roi_left), 'top':  max(0, roi_top), 'width': roi_w, 'height': roi_h}

    def is_step1_fallback_allowed(self):
        now = datetime.now()
        sec = now.hour * 3600 + now.minute * 60 + now.second
        windows = [
            (12 * 3600 + 55 * 60 + 1, 14 * 3600 + 0 * 60 + 0),
            (19 * 3600 + 55 * 60 + 1, 21 * 3600 + 0 * 60 + 0),
        ]
        return any(start <= sec <= end for start, end in windows)

    def run_logic(self):
        try:
            with mss.mss() as sct:
                while self.is_running:
                    if self.status == 0:
                        self.status_lbl.config(text="🔍 全屏搜索入口...", fg="orange")
                        self.mission_start_time = None # 重置计时
                        
                        pos, _ = self.find_fast(sct, IMG_AIM)
                        if pos:
                            self.log("✅ 锁定 -> 死守模式")
                            pydirectinput.moveTo(pos[0], pos[1])
                            self.aim_pos = pos
                            self.calculate_red_roi(pos)
                            self.status = 1
                            time.sleep(0.1)
                        else:
                            time.sleep(0.2) 
                            
                    elif self.status == 1:
                        self.status_lbl.config(text="⚡ 死守点击...", fg="red")
                        roi_to_use = self.dynamic_red_roi if self.dynamic_red_roi else self.monitor
                        fire_pos, _ = self.find_fast(sct, IMG_FIRE, roi=roi_to_use)
                        
                        # 检测到红点
                        if fire_pos:
                            if self.mission_start_time is None: self.mission_start_time = time.time() # 开始计时
                            self.log(">>> [Step 1] 红点触发")
                            self.fast_click(fire_pos[0], fire_pos[1])
                            time.sleep(0.05)
                            self.status = 2
                            continue

                        # 兜底时间检测
                        if self.aim_pos and self.is_step1_fallback_allowed():
                            if self.mission_start_time is None: self.mission_start_time = time.time() # 开始计时
                            self.log(">>> [Step 1] 兜底直点")
                            self.fast_click(self.aim_pos[0], self.aim_pos[1])
                            time.sleep(0.05)
                            self.status = 2
                            continue

                        now = time.time()
                        if now - self.last_step1_wait_log_time > 5.0:
                            self.log("Step 1 等待开放时间或红点...")
                            self.last_step1_wait_log_time = now
                        time.sleep(0.2)
                        
                    elif self.status == 2:
                        self.status_lbl.config(text="寻找地图...", fg="blue")
                        # 地图按钮比较大且稳定，普通点击即可，若失败也无所谓，流程会被卡在这里重试
                        pos, _ = self.find_fast(sct, IMG_MAP)
                        if pos:
                            self.log(">>> [Step 2] 极速点")
                            self.fast_click(pos[0], pos[1])
                            time.sleep(0.05)
                            self.status = 3
                            
                    elif self.status == 3:
                        self.status_lbl.config(text="🔥 暴力排队中...", fg="red")
                        
                        # --- 核心修复：全屏搜索，不再依赖硬坐标ROI ---
                        # 抢排队时窗口可能偏移，全屏搜最稳
                        pos, conf = self.find_fast(sct, IMG_ENTER, roi=self.monitor)
                        
                        if pos:
                            now = time.time()
                            # 冷却防止操作过于密集被判定脚本
                            if now - self.last_step3_action_time < 0.2:
                                continue

                            self.log(f">>> [Step 3] 锁定目标 {pos} (conf:{conf:.2f})")
                            
                            # --- 核心修复：使用重击模式点击真实坐标 ---
                            self.heavy_click(pos[0], pos[1])
                            self.last_step3_action_time = now

                            # --- 核心修复：死循环检查直到按钮消失 ---
                            wait_success = False
                            for _ in range(6): # 检查6次，约0.6秒
                                time.sleep(0.1)
                                # 缩小范围复查，提高速度
                                check_roi_dynamic = {
                                    'left': max(0, pos[0] - 100),
                                    'top': max(0, pos[1] - 50),
                                    'width': 200,
                                    'height': 100
                                }
                                still_pos, _ = self.find_fast(sct, IMG_ENTER, roi=check_roi_dynamic)
                                if not still_pos:
                                    wait_success = True
                                    break

                            if wait_success:
                                # 计算总耗时
                                end_time = time.time()
                                duration = 0.0
                                if self.mission_start_time:
                                    duration = end_time - self.mission_start_time
                                
                                self.log(f"🎉 任务完成！总耗时: {duration:.3f} 秒")
                                self.status_lbl.config(text=f"完成 (耗时 {duration:.2f}s)")
                                self.is_running = False 
                                self.status = 0
                                self.dynamic_red_roi = None
                            else:
                                if now - self.last_step3_log_time > 1.0:
                                    self.log("⚠️ 服务器卡顿/按钮未消失，继续重试...")
                                    self.last_step3_log_time = now
                        else:
                            # 找不到按钮时（可能是被弹窗挡住，或已经进去了）
                            if conf > 0.5: # 如果相似度尚可，可能是模糊了
                                self.log(f"Step 3 搜索中... 相似度: {conf:.2f}")
                            else:
                                # 完全找不到，也许已经进去了？
                                # 这里可以加个超时判断，或者就是这样保持搜索
                                pass
                                
        except Exception as e:
            self.log(f"❌ 错误: {e}")
            traceback.print_exc()
            self.is_running = False
            self.status_lbl.config(text="出错停止")

    def start(self):
        if not self.is_running:
            self.is_running = True
            self.status = 0 
            self.log("🚀 引擎启动...")
            self.thread = threading.Thread(target=self.run_logic, daemon=True)
            self.thread.start()

    def stop(self):
        self.is_running = False
        self.status_lbl.config(text="已停止")
        self.log("已停止")

if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = BotFinalRelease(root)
        root.mainloop()
    except Exception as e:
        pass