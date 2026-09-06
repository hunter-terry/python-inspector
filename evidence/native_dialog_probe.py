"""Inspect only this process's native dialog controls, then cancel safely."""
import ctypes
import json
import os
import threading
import time
import sys
from ctypes import wintypes
from tkinter import Tk, filedialog

user32 = ctypes.windll.user32
callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = wintypes.LPARAM

def describe(hwnd):
    cls = ctypes.create_unicode_buffer(256)
    text = ctypes.create_unicode_buffer(1024)
    user32.GetClassNameW(hwnd, cls, 256)
    user32.GetWindowTextW(hwnd, text, 1024)
    return {"hwnd": hwnd, "class": cls.value, "text": text.value,
            "id": user32.GetDlgCtrlID(hwnd)}

def inspect(destination=None):
    time.sleep(1)
    def visit(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        info = describe(hwnd)
        if pid.value == os.getpid() and info["class"] == "#32770":
            controls = []
            def child(ch, _):
                controls.append(describe(ch))
                return True
            user32.EnumChildWindows(hwnd, callback_type(child), 0)
            if destination is None:
                print(json.dumps(controls), flush=True)
                user32.PostMessageW(hwnd, 0x0111, 2, 0)
            else:
                edit = next(c for c in controls if c["class"] == "Edit" and c["id"] in (1001, 1152))
                value = ctypes.create_unicode_buffer(str(destination))
                user32.SendMessageW(edit["hwnd"], 0x000C, 0, ctypes.addressof(value))
                user32.PostMessageW(hwnd, 0x0111, 1, 0)
                if edit["id"] == 1152:
                    # Folder selection navigates into a typed path first.
                    time.sleep(0.5)
                    user32.PostMessageW(hwnd, 0x0111, 1, 0)
                time.sleep(3)
                if user32.IsWindowVisible(hwnd):
                    user32.PostMessageW(hwnd, 0x0111, 2, 0)
        return True
    user32.EnumWindows(callback_type(visit), 0)

if __name__ == "__main__":
    root = Tk()
    root.withdraw()
    threading.Thread(target=inspect, daemon=True).start()
    if "--folder" in sys.argv:
        filedialog.askdirectory(parent=root, title="Python Inspector native folder probe")
    else:
        filedialog.asksaveasfilename(parent=root, title="Python Inspector native save probe", defaultextension=".md")
    root.destroy()
