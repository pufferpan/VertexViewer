"""给正在跑的 VertexViewer 窗口截图（PrintWindow），用来确认软件真的起来了。

    python tools/grab_window.py <输出png> [进程名]
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

OUT = sys.argv[1] if len(sys.argv) > 1 else r"G:\xmcl-fetch\work\app_window.png"
NAME = (sys.argv[2] if len(sys.argv) > 2 else "VertexViewer.exe").lower()


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG),
                ("biPlanes", wt.WORD), ("biBitCount", wt.WORD),
                ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


def pids_of(name):
    import subprocess
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}", "/FO", "CSV"],
                         capture_output=True, text=True, errors="ignore").stdout
    pids = []
    for line in out.splitlines()[1:]:
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[0].lower() == name:
            try:
                pids.append(int(parts[1]))
            except ValueError:
                pass
    return pids


def windows_of(pids):
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids:
            n = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            rect = wt.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            w, h = rect.right - rect.left, rect.bottom - rect.top
            found.append((hwnd, pid.value, buf.value,
                          bool(user32.IsWindowVisible(hwnd)), w, h))
        return True

    user32.EnumWindows(cb, 0)
    return found


def capture(hwnd, w, h, path):
    hdc = user32.GetWindowDC(hwnd)
    mem = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mem, bmp)
    user32.PrintWindow(hwnd, mem, 2)          # PW_RENDERFULLCONTENT
    bi = BITMAPINFOHEADER()
    bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.biWidth, bi.biHeight = w, -h
    bi.biPlanes, bi.biBitCount = 1, 32
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bi), 0)
    from PIL import Image
    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    img.save(path)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(hwnd, hdc)
    return img.size


def main():
    pids = pids_of(NAME)
    if not pids:
        print("进程没起来:", NAME)
        return
    wins = [w for w in windows_of(set(pids)) if w[3] and w[4] > 400 and w[5] > 300]
    wins.sort(key=lambda w: w[4] * w[5], reverse=True)
    print("进程", pids, "可见大窗口", len(wins))
    for hwnd, pid, title, vis, w, h in wins[:4]:
        print(f"  hwnd={hwnd} pid={pid} {title!r} {w}x{h}")
    if not wins:
        return
    hwnd, pid, title, vis, w, h = wins[0]
    size = capture(hwnd, w, h, OUT)
    print("saved", OUT, size, "title:", title)


if __name__ == "__main__":
    main()
