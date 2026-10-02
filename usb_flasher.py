import os
import sys
import ctypes
import subprocess
import threading
import urllib.request
import urllib.error
import tkinter as tk
from tkinter import messagebox, filedialog
import customtkinter as ctk

APP = "Infinity OS USB Creator"
# Download source. If it ends with ".", the tool downloads numbered parts
# (InfinityOS.iso.001, .002, ...) and rejoins them. Otherwise it's a single-file link.
ISO_URL = "https://github.com/yassincarla0009-wq/InfinityOS-ISO/releases/download/v1.0/InfinityOS.iso."
KNOWN_SHA = "563aaae70ace178f7fc8b4471c65295b6a94874deff5c2c79e7983eb28e3316a"

BG, PANEL, FG, MUTED = "#0b1020", "#161c30", "#e8ecff", "#8fa0c8"
ACC, ACC_H, GOOD, BAD, WARN = "#00e5ff", "#00b8d4", "#00e676", "#ef5350", "#ffb300"

NO_WINDOW = 0x08000000


# ---------- admin ----------
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


if not is_admin():
    # relaunch elevated
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable,
                                        " ".join(f'"{a}"' for a in sys.argv), None, 1)
    sys.exit(0)

ctk.set_appearance_mode("dark")


# ---------- USB enumeration (USB bus only -> never internal disks) ----------
def list_usb_disks():
    # USB bus = both USB flash sticks AND external USB hard drives. Never the boot disk.
    ps = ("Get-Disk | Where-Object { ($_.BusType -eq 'USB') -and (-not $_.IsBoot) -and (-not $_.IsSystem) } | "
          "ForEach-Object { \"$($_.Number)|$($_.FriendlyName)|$([math]::Round($_.Size/1GB,1))\" }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW).stdout
    except Exception:
        out = ""
    disks = []
    for line in out.strip().splitlines():
        parts = line.strip().split("|")
        if len(parts) == 3 and parts[0].isdigit():
            disks.append((int(parts[0]), parts[1], parts[2]))
    return disks


def find_local_iso():
    for d in (os.path.join(os.path.expanduser("~"), "Downloads"),
              os.path.dirname(os.path.abspath(sys.argv[0])),
              os.path.join(os.path.expanduser("~"), "Desktop")):
        p = os.path.join(d, "InfinityOS.iso")
        if os.path.isfile(p):
            return p
    return ""


# ---------- flashing ----------
GENERIC_RW = 0xC0000000
FILE_SHARE_RW = 0x3
OPEN_EXISTING = 3


def flash_iso(iso_path, disk_num, progress_cb, status_cb, done_cb):
    try:
        total = os.path.getsize(iso_path)
        status_cb(f"Clearing disk {disk_num} ...")
        # remove partitions so the physical drive is writable
        subprocess.run(["diskpart"], input=f"select disk {disk_num}\nclean\nrescan\n",
                       text=True, capture_output=True, timeout=120, creationflags=NO_WINDOW)
        status_cb("Opening USB device ...")
        h = ctypes.windll.kernel32.CreateFileW(
            f"\\\\.\\PhysicalDrive{disk_num}", GENERIC_RW, FILE_SHARE_RW, None,
            OPEN_EXISTING, 0, None)
        if h == -1 or h == 0xFFFFFFFFFFFFFFFF:
            raise OSError("Could not open the USB device (is it still plugged in?).")
        written = 0
        buf_size = 4 * 1024 * 1024
        status_cb("Writing Infinity OS to USB ...")
        with open(iso_path, "rb") as f:
            while True:
                chunk = f.read(buf_size)
                if not chunk:
                    break
                # pad final chunk to 512-byte sector alignment
                if len(chunk) % 512:
                    chunk += b"\x00" * (512 - (len(chunk) % 512))
                wrote = ctypes.wintypes.DWORD(0) if hasattr(ctypes, "wintypes") else None
                import ctypes.wintypes as wt
                wrote = wt.DWORD(0)
                ok = ctypes.windll.kernel32.WriteFile(h, chunk, len(chunk), ctypes.byref(wrote), None)
                if not ok:
                    err = ctypes.windll.kernel32.GetLastError()
                    ctypes.windll.kernel32.CloseHandle(h)
                    raise OSError(f"Write failed (error {err}).")
                written += len(chunk)
                progress_cb(min(written, total), total)
        ctypes.windll.kernel32.FlushFileBuffers(h)
        ctypes.windll.kernel32.CloseHandle(h)
        done_cb(True, "Done! Infinity OS USB is ready. Reboot and pick it in the boot menu.")
    except Exception as e:
        done_cb(False, f"Failed: {e}")


# ---------- UI ----------
root = ctk.CTk()
root.title(APP)
root.geometry("660x620")
root.configure(fg_color=BG)
busy = {"v": False}

ctk.CTkLabel(root, text="∞  INFINITY OS", font=ctk.CTkFont(size=30, weight="bold"), text_color=ACC).pack(pady=(16, 0))
ctk.CTkLabel(root, text="USB Creator — download & flash a bootable stick",
             font=ctk.CTkFont(size=13), text_color=MUTED).pack(pady=(0, 10))

# ISO
isf = ctk.CTkFrame(root, fg_color=PANEL, corner_radius=12)
isf.pack(fill="x", padx=20, pady=6)
ctk.CTkLabel(isf, text="1.  Infinity OS ISO", font=ctk.CTkFont(size=14, weight="bold"), text_color=FG).pack(anchor="w", padx=14, pady=(10, 2))
iso_var = tk.StringVar(value=find_local_iso() or "(not downloaded yet)")
rowi = ctk.CTkFrame(isf, fg_color="transparent"); rowi.pack(fill="x", padx=14, pady=4)
ctk.CTkEntry(rowi, textvariable=iso_var, font=ctk.CTkFont(size=11)).pack(side="left", fill="x", expand=True, padx=(0, 6))
def browse():
    p = filedialog.askopenfilename(filetypes=[("Disc image", "*.iso")])
    if p: iso_var.set(p)
ctk.CTkButton(rowi, text="Browse", width=80, fg_color="#263258", hover_color="#31406e", command=browse).pack(side="left")

url_var = tk.StringVar(value=ISO_URL)
ctk.CTkEntry(isf, textvariable=url_var, placeholder_text="Download URL for InfinityOS.iso (paste link)",
             font=ctk.CTkFont(size=11)).pack(fill="x", padx=14, pady=(6, 2))
def download():
    base = url_var.get().strip()
    if not base:
        messagebox.showinfo(APP, "No download link set (or use Browse for a local ISO)."); return
    dest = os.path.join(os.path.expanduser("~"), "Downloads", "InfinityOS.iso")
    status.configure(text="Downloading Infinity OS ...", text_color=MUTED)

    def work():
        try:
            if base.endswith("."):
                # multi-part: base + 001, 002, ... rejoined into one ISO
                with open(dest, "wb") as out:
                    i = 1
                    while True:
                        purl = f"{base}{i:03d}"
                        try:
                            resp = urllib.request.urlopen(purl, timeout=60)
                        except urllib.error.HTTPError as he:
                            if he.code in (403, 404) and i > 1:
                                break  # no more parts
                            raise
                        total = int(resp.headers.get("Content-Length", 0))
                        read = 0
                        root.after(0, lambda ii=i: status.configure(text=f"Downloading part {ii} ...", text_color=MUTED))
                        while True:
                            chunk = resp.read(1024 * 1024)
                            if not chunk:
                                break
                            out.write(chunk)
                            read += len(chunk)
                            if total:
                                root.after(0, lambda r=read, t=total: prog.set(min(r / t, 1.0)))
                        resp.close()
                        i += 1
                if i == 1:
                    raise RuntimeError("No parts found at that link.")
            else:
                def hook(b, bs, t):
                    if t > 0:
                        root.after(0, lambda: prog.set(min(b * bs / t, 1.0)))
                urllib.request.urlretrieve(base, dest, hook)
            root.after(0, lambda: (iso_var.set(dest),
                                   status.configure(text="Download complete — now Flash.", text_color=GOOD),
                                   prog.set(0)))
        except Exception as e:
            root.after(0, lambda: status.configure(text=f"Download failed: {e}", text_color=BAD))
    threading.Thread(target=work, daemon=True).start()
ctk.CTkButton(isf, text="⬇ Download ISO", fg_color=ACC, text_color=BG, command=download).pack(anchor="w", padx=14, pady=(2, 12))

# USB
uf = ctk.CTkFrame(root, fg_color=PANEL, corner_radius=12)
uf.pack(fill="x", padx=20, pady=6)
ctk.CTkLabel(uf, text="2.  Pick your drive (USB sticks & external HDDs — internal disks hidden)",
             font=ctk.CTkFont(size=14, weight="bold"), text_color=FG).pack(anchor="w", padx=14, pady=(10, 2))
disk_var = tk.StringVar(value="")
disk_combo = ctk.CTkComboBox(uf, variable=disk_var, values=[], width=400, button_color=ACC, button_hover_color=ACC_H)
disk_combo.pack(side="left", padx=14, pady=8)
disk_map = {}
def refresh_disks():
    disks = list_usb_disks()
    vals = []
    disk_map.clear()
    for n, name, gb in disks:
        label = f"Disk {n}: {name} ({gb} GB)"
        vals.append(label); disk_map[label] = n
    disk_combo.configure(values=vals)
    disk_var.set(vals[0] if vals else "")
    if not vals:
        status.configure(text="No USB drive detected — plug one in and Refresh.", text_color=WARN)
ctk.CTkButton(uf, text="↻", width=44, fg_color="#263258", hover_color="#31406e", command=refresh_disks).pack(side="left", pady=8)
refresh_disks()

# Flash
def do_flash():
    if busy["v"]:
        return
    iso = iso_var.get()
    if not os.path.isfile(iso):
        messagebox.showwarning(APP, "No ISO. Download it or Browse to a local InfinityOS.iso."); return
    label = disk_var.get()
    if not label or label not in disk_map:
        messagebox.showwarning(APP, "Pick a USB drive."); return
    n = disk_map[label]
    if not messagebox.askyesno("⚠ ERASE WARNING",
        f"This will PERMANENTLY ERASE everything on:\n\n   {label}\n\n"
        "and write Infinity OS to it.\n\nAre you absolutely sure?"):
        return
    confirm = ctk_prompt(f"Type the disk number ({n}) to confirm flashing:")
    if confirm != str(n):
        messagebox.showinfo(APP, "Cancelled (number didn't match)."); return
    busy["v"] = True
    flash_btn.configure(state="disabled", text="Flashing...")
    def pcb(w, t): root.after(0, lambda: (prog.set(w/t), status.configure(
        text=f"Writing... {w//(1024*1024)} / {t//(1024*1024)} MB", text_color=MUTED)))
    def scb(s): root.after(0, lambda: status.configure(text=s, text_color=MUTED))
    def dcb(ok, msg):
        def fin():
            busy["v"] = False; prog.set(0)
            flash_btn.configure(state="normal", text="⚡ Flash to USB")
            (messagebox.showinfo if ok else messagebox.showerror)(APP, msg)
            status.configure(text=msg, text_color=(GOOD if ok else BAD))
        root.after(0, fin)
    threading.Thread(target=flash_iso, args=(iso, n, pcb, scb, dcb), daemon=True).start()

flash_btn = ctk.CTkButton(root, text="⚡ Flash to USB", font=ctk.CTkFont(size=16, weight="bold"),
                          fg_color=GOOD, text_color=BG, height=46, command=do_flash)
flash_btn.pack(pady=(14, 6), padx=20, fill="x")

prog = ctk.CTkProgressBar(root, progress_color=ACC); prog.set(0); prog.pack(fill="x", padx=22, pady=4)
status = ctk.CTkLabel(root, text="Ready.", font=ctk.CTkFont(size=12), text_color=MUTED); status.pack(pady=4)
ctk.CTkLabel(root, text="After flashing: reboot → F12 / Novo button → pick the USB → Try or Install Infinity OS",
             font=ctk.CTkFont(size=11), text_color=MUTED, wraplength=600).pack(pady=6)
ctk.CTkLabel(root, text="Infinity OS — powered by GNOME — built by Yassin",
             font=ctk.CTkFont(size=10), text_color="#5a6b96").pack(side="bottom", pady=8)


def ctk_prompt(text):
    win = ctk.CTkToplevel(root); win.title("Confirm"); win.geometry("360x160"); win.transient(root)
    win.after(150, win.grab_set)
    ctk.CTkLabel(win, text=text, font=ctk.CTkFont(size=13)).pack(pady=(24, 8), padx=16)
    v = tk.StringVar()
    ent = ctk.CTkEntry(win, textvariable=v, width=120, justify="center"); ent.pack(); ent.focus_set()
    res = {"v": None}
    def ok(): res["v"] = v.get().strip(); win.destroy()
    ctk.CTkButton(win, text="Confirm", fg_color=ACC, text_color=BG, command=ok).pack(pady=14)
    ent.bind("<Return>", lambda e: ok())
    win.wait_window()
    return res["v"]


root.mainloop()
