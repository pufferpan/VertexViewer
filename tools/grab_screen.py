"""抓整屏（用于验证加载界面的小方框），不依赖目标窗口标题。

用法： python tools/grab_screen.py <输出png> [延迟毫秒]
"""
import os
import sys
import time

from PIL import ImageGrab

out = sys.argv[1] if len(sys.argv) > 1 else r"G:\xmcl-fetch\work\screen.png"
delay = int(sys.argv[2]) if len(sys.argv) > 2 else 0
if delay:
    time.sleep(delay / 1000.0)
os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
ImageGrab.grab().save(out)
print("saved", out)
