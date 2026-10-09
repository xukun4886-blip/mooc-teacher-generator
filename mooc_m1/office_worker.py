"""Private worker: dedicated PowerPoint process, read-only document, macros disabled."""
import os
import sys
import time
import json
from pathlib import Path

from .core import read_json, write_json, run


def main():
    import pythoncom
    import win32com.client
    import win32process
    import win32api
    import win32con
    request = read_json(sys.argv[1])
    pythoncom.CoInitialize()
    app, deck, office_pid, owns_app = None, None, None, False
    start = time.perf_counter()
    def powerpoint_pids():
        raw = run(["powershell", "-NoProfile", "-Command",
                   "@((Get-Process -Name POWERPNT -ErrorAction SilentlyContinue).Id) | ConvertTo-Json -Compress"], 15)["stdout"].strip()
        value = json.loads(raw) if raw else []
        return set(value if isinstance(value, list) else [value])
    try:
        before = powerpoint_pids()
        app = win32com.client.DispatchEx("PowerPoint.Application")
        created = powerpoint_pids() - before
        if len(created) != 1:
            raise RuntimeError("PowerPoint did not create an isolated instance; existing user application is untouched")
        office_pid = created.pop()
        owns_app = True
        # Assign only this dedicated Office instance to the worker's kill-on-close job.
        # If the worker times out, Windows also closes its COM-owned PowerPoint process.
        import win32job
        job = win32job.CreateJobObject(None, "")
        info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        info["BasicLimitInformation"]["LimitFlags"] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
        handle = win32api.OpenProcess(win32con.PROCESS_ALL_ACCESS, False, office_pid)
        win32job.AssignProcessToJobObject(job, handle)
        app.AutomationSecurity = 3
        deck = app.Presentations.Open(request["input"], ReadOnly=True, Untitled=False, WithWindow=False)
        if request.get("convert_to"):
            deck.SaveAs(request["convert_to"], 24)  # ppSaveAsOpenXMLPresentation
            if not Path(request["convert_to"]).is_file():
                raise RuntimeError("Legacy conversion produced no PPTX; save as PPTX manually")
            return
        opened = time.perf_counter()
        height = round(request["width"] * deck.PageSetup.SlideHeight / deck.PageSetup.SlideWidth)
        pages = []
        for index in range(1, deck.Slides.Count + 1):
            name = f"page-{index:03d}.png"
            deck.Slides.Item(index).Export(str(Path(request["output"]) / name), "PNG", request["width"], height)
            pages.append({"source_index": index, "path": name})
        first_export = time.perf_counter()
        warm_dir = Path(request["output"]) / "warm"
        warm_dir.mkdir()
        for index in range(1, deck.Slides.Count + 1):
            deck.Slides.Item(index).Export(str(warm_dir / f"page-{index:03d}.png"), "PNG", request["width"], height)
        warm_export = time.perf_counter()
        write_json(Path(request["output"]) / "render.json",
                   {"schema_version": "m1.render.v1", "renderer": "Microsoft PowerPoint COM",
                    "renderer_version": app.Version, "page_count": len(pages), "pages": pages,
                    "width": request["width"], "height": height,
                    "timings": {"office_start_and_open_seconds": opened - start,
                                "first_export_seconds": first_export - opened,
                                "warm_export_same_loaded_document_seconds": warm_export - first_export},
                    "visual_review": "pending", "embedded_media_policy": "static original-page export"})
    finally:
        if deck is not None:
            deck.Close()
        if app is not None and owns_app:
            app.Quit()
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()
