"""Real Tk timing probe; synthetic findings isolate UI cost from scanner cost."""
import dataclasses
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import customtkinter as ctk
from inspector_app.mock_data import _MOCK_FINDINGS
from inspector_app.models import ScanResult, SourceKind
from inspector_app.state import Screen
from inspector_app.ui.app_window import AppController

root = ctk.CTk()
root.title("Python Inspector UI responsiveness probe")
root.geometry("1000x680")
app = AppController(root)
count = int(sys.argv[1]) if len(sys.argv) > 1 else 400
result = ScanResult("UI stress fixture", SourceKind.LOCAL_FOLDER, datetime.now(timezone.utc),
                    datetime.now(timezone.utc), tuple(dataclasses.replace(_MOCK_FINDINGS[0],
                    finding_id=f"F-{i}") for i in range(count)))
ticks = []
started = time.perf_counter()

def heartbeat():
    ticks.append(time.perf_counter())
    root.after(50, heartbeat)

def show():
    app.state.scan_result = result
    app.state.screen = Screen.RESULTS
    app.render()
    print("render returned", flush=True)

def finish():
    intervals = [b-a for a,b in zip(ticks, ticks[1:])]
    print(json.dumps({"findings": count, "elapsed": time.perf_counter()-started,
                      "max_heartbeat_gap": max(intervals, default=0),
                      "cards": len(app.screens[Screen.RESULTS].scroll.winfo_children())}), flush=True)
    root.destroy()

root.after(50, heartbeat)
root.after(200, show)
def revisit():
    app.open_repair_details("F-0")
    root.after(100, app.back_to_results)

root.after(20000, revisit)
root.after(35000, revisit)
root.after(50000, finish)
root.mainloop()
