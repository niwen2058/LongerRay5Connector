import requests
import json
import socket
import time
import re
import os
import sys
import threading
import logging
import urllib.parse
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("connector.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False

# Set console output to UTF-8 for Windows
if sys.platform == "win32":
    import codecs
    try:
        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())
    except:
        pass

class Ray5Client:
    def __init__(self, ip="192.168.1.101", port=8848):
        self.ip = ip
        self.port = port
        self.base_url = f"http://{ip}:{port}"
        self.mac = None

    def get_files(self, path="/"):
        try:
            encoded_path = urllib.parse.quote(path)
            r = requests.get(f"{self.base_url}/files?path={encoded_path}", timeout=5)
            if r.status_code == 200:
                data = json.loads(r.content.decode('utf-8', errors='ignore'))
                return data.get("files", [])
            logging.error(f"Failed to get files: HTTP {r.status_code}")
            return []
        except Exception as e:
            logging.error(f"Error getting files: {e}")
            return []

    def upload_file(self, local_path, remote_path="/"):
        filename = os.path.basename(local_path)
        filesize = os.path.getsize(local_path)
        encoded_path = urllib.parse.quote(remote_path)
        url = f"{self.base_url}/upload?path={encoded_path}"
        
        try:
            with open(local_path, "rb") as f:
                data = {
                    'path': remote_path,
                    'size': str(filesize)
                }
                files = {'file': (filename, f, 'application/octet-stream')}
                r = requests.post(url, data=data, files=files, timeout=60)
                if r.status_code == 200:
                    logging.info(f"Uploaded {filename} successfully")
                    return "Upload successful"
                logging.error(f"Upload failed: {r.status_code} {r.text}")
                return f"Upload failed: {r.status_code}"
        except Exception as e:
            logging.error(f"Upload error for {filename}: {e}")
            return f"Upload error: {e}"

    def delete_file(self, filename, path="/"):
        try:
            # Manufacturer uses /command?commandText=$SD/Delete=filename
            encoded_filename = urllib.parse.quote(filename)
            url = f"{self.base_url}/command?commandText=$SD/Delete={encoded_filename}"
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                logging.info(f"Deleted {filename} successfully")
                return "Delete command sent"
            logging.error(f"Delete failed for {filename}: HTTP {r.status_code}")
            return f"Delete failed: {r.status_code}"
        except Exception as e:
            logging.error(f"Delete error for {filename}: {e}")
            return f"Delete error: {e}"

    def send_command(self, cmd):
        try:
            encoded_cmd = urllib.parse.quote(cmd)
            r = requests.get(f"{self.base_url}/command?plain={encoded_cmd}", timeout=5)
            return r.text
        except Exception as e:
            logging.error(f"Command error ({cmd}): {e}")
            return f"Command error: {e}"

class Ray5App:
    def __init__(self, root):
        self.root = root
        self.root.title("Longer Ray5 Connector")
        self.root.geometry("800x600")
        
        # Handle window closing
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.running = True
        
        self.client = Ray5Client()
        self.last_config = self.load_config()
        self.connected = False
        self.current_mac = "Unknown"
        
        self.setup_ui()
        
        # Auto-connect if last IP exists
        if self.last_config.get("last_ip"):
            self.ip_var.set(self.last_config["last_ip"])
            self.connect()
        
        self.start_keepalive()

    def on_closing(self):
        self.running = False
        self.root.destroy()

    def load_config(self):
        if os.path.exists("config.json"):
            try:
                with open("config.json", "r") as f:
                    return json.load(f)
            except Exception as e:
                logging.error(f"Failed to load config: {e}")
        return {}

    def save_config(self, mac, ip):
        try:
            with open("config.json", "w") as f:
                json.dump({"last_mac": mac, "last_ip": ip}, f)
        except Exception as e:
            logging.error(f"Failed to save config: {e}")

    def setup_ui(self):
        # Top Bar: Connection
        conn_frame = ttk.LabelFrame(self.root, text="Connection")
        conn_frame.pack(fill="x", padx=10, pady=5)
        
        ttk.Label(conn_frame, text="IP Address:").pack(side="left", padx=5)
        self.ip_var = tk.StringVar(value="192.168.1.101")
        self.ip_entry = ttk.Entry(conn_frame, textvariable=self.ip_var)
        self.ip_entry.pack(side="left", padx=5)
        
        self.btn_connect = ttk.Button(conn_frame, text="Connect / Scan", command=self.toggle_connect)
        self.btn_connect.pack(side="left", padx=5)
        
        # Status and Keepalive Dot
        status_frame = ttk.Frame(conn_frame)
        status_frame.pack(side="right", padx=10)
        
        self.status_label = ttk.Label(status_frame, text="Disconnected")
        self.status_label.pack(side="left")
        
        self.dot_canvas = tk.Canvas(status_frame, width=12, height=12, highlightthickness=0)
        self.dot_canvas.pack(side="left", padx=5)
        self.dot = self.dot_canvas.create_oval(2, 2, 10, 10, fill="gray", outline="")

        # Main Area: File List
        list_frame = ttk.LabelFrame(self.root, text="Files on Laser")
        list_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        self.tree = ttk.Treeview(list_frame, columns=("name", "size"), show="headings", selectmode="extended")
        self.tree.heading("name", text="Filename")
        self.tree.heading("size", text="Size")
        self.tree.pack(fill="both", expand=True, side="left")
        
        # Define tag for fading effect
        self.tree.tag_configure("new_file", background="#90EE90")
        
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        scrollbar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scrollbar.set)

        # Bottom Bar: Actions
        action_frame = ttk.Frame(self.root)
        action_frame.pack(fill="x", padx=10, pady=5)
        
        ttk.Button(action_frame, text="Refresh List", command=self.refresh_list).pack(side="left", padx=5)
        ttk.Button(action_frame, text="Upload File(s)", command=self.upload).pack(side="left", padx=5)
        ttk.Button(action_frame, text="Delete Selected", command=self.delete).pack(side="left", padx=5)

        # Drag and Drop setup
        if HAS_DND:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind('<<Drop>>', self.handle_drop)

    def handle_drop(self, event):
        if not self.connected:
            logging.warning("Drop ignored: Not connected")
            return
            
        data = event.data
        paths = []
        
        # Simple parser for curly brace format used by tkinterdnd2 on Windows
        if '{' in data:
            paths = re.findall(r'\{(.*?)\}', data)
            # Also find paths without braces if any
            remaining = re.sub(r'\{.*?\}', '', data).split()
            paths.extend(remaining)
        else:
            paths = data.split()
            
        if paths:
            self.perform_upload(paths)

    def toggle_connect(self):
        if self.connected:
            self.disconnect()
        else:
            self.connect()

    def disconnect(self):
        self.connected = False
        self.ip_entry.config(state="normal")
        self.btn_connect.config(text="Connect / Scan")
        self.status_label.config(text="Disconnected")
        self.dot_canvas.itemconfig(self.dot, fill="gray")
        for i in self.tree.get_children():
            self.tree.delete(i)
        logging.info("Disconnected from laser")

    def is_valid_ip(self, ip):
        try:
            socket.inet_aton(ip)
            return True
        except socket.error:
            return False

    def connect(self):
        ip = self.ip_var.get().strip()
        if not self.is_valid_ip(ip):
            logging.error(f"Invalid IP address: {ip}")
            self.status_label.config(text="Invalid IP")
            return

        self.status_label.config(text="Connecting...")
        logging.info(f"Attempting to connect to {ip}...")
        
        def task():
            client = Ray5Client(ip)
            info = client.send_command("[ESP420]")
            if not self.running: return
            if "FW version" in info:
                mac_match = re.search(r"STA \(([0-9A-F:]+)\)", info)
                mac = mac_match.group(1) if mac_match else "Unknown"
                self.client = client
                self.current_mac = mac
                self.save_config(mac, ip)
                logging.info(f"Connected to {ip} (MAC: {mac})")
                if self.running:
                    self.root.after(0, lambda: self.on_connected(ip, mac) if self.running else None)
            else:
                logging.error(f"Could not connect to laser at {ip}. Response: {info}")
                if self.running:
                    self.root.after(0, lambda: self.status_label.config(text="Connection Failed") if self.running else None)
        
        threading.Thread(target=task, daemon=True).start()

    def on_connected(self, ip, mac):
        self.connected = True
        self.ip_entry.config(state="disabled")
        self.btn_connect.config(text="Disconnect")
        self.update_status_text()
        self.refresh_list()

    def update_status_text(self):
        if self.connected:
            self.status_label.config(text=f"Connected: {self.client.ip} ({self.current_mac})")
        else:
            self.status_label.config(text="Disconnected")

    def start_keepalive(self):
        def check():
            if not self.running: return
            if self.connected:
                try:
                    # Simple command to check if alive
                    res = self.client.send_command("[ESP400]")
                    if not self.running: return
                    if "error" not in res.lower():
                        self.root.after(0, lambda: self.flash_dot() if self.running else None)
                    else:
                        logging.debug("Keepalive check failed")
                except Exception as e:
                    logging.debug(f"Keepalive exception: {e}")
            if self.running:
                self.root.after(2000, check)
        
        threading.Thread(target=check, daemon=True).start()

    def flash_dot(self):
        if not self.running: return
        self.dot_canvas.itemconfig(self.dot, fill="#00FF00")
        self.fade_dot(10)

    def fade_dot(self, step):
        if not self.running or step <= 0:
            if self.running:
                self.dot_canvas.itemconfig(self.dot, fill="#004400") # Dark green instead of gray when connected
            return
        
        # Fade from bright green to dark green
        r = 0
        g = int(68 + (255 - 68) * (step / 10))
        b = 0
        color = f'#{r:02x}{g:02x}{b:02x}'
        self.dot_canvas.itemconfig(self.dot, fill=color)
        self.root.after(50, lambda: self.fade_dot(step - 1) if self.running else None)

    def refresh_list(self, new_filenames=None):
        if not self.connected or not self.running: return
        for i in self.tree.get_children():
            self.tree.delete(i)
            
        def task():
            files = self.client.get_files()
            if not self.running: return
            self.root.after(0, lambda: self.populate_tree(files, new_filenames) if self.running else None)
            
        threading.Thread(target=task, daemon=True).start()

    def populate_tree(self, files, new_filenames=None):
        for f in files:
            name = f.get("name")
            item_id = self.tree.insert("", "end", values=(name, f.get("size")))
            if new_filenames and name in new_filenames:
                self.tree.item(item_id, tags=("new_file",))
                self.fade_item(item_id, 15)

    def fade_item(self, item_id, seconds_left):
        if not self.running or not self.tree.exists(item_id):
            return
            
        if seconds_left <= 0:
            self.tree.item(item_id, tags=())
            return
        
        # Calculate color
        total_steps = 15
        step = total_steps - seconds_left
        
        r = int(144 + (255 - 144) * (step / total_steps))
        g = int(238 + (255 - 238) * (step / total_steps))
        b = int(144 + (255 - 144) * (step / total_steps))
        
        color = f'#{r:02x}{g:02x}{b:02x}'
        
        tag_name = f"fade_{item_id}_{seconds_left}"
        self.tree.tag_configure(tag_name, background=color)
        self.tree.item(item_id, tags=(tag_name,))
        
        self.root.after(1000, lambda: self.fade_item(item_id, seconds_left - 1) if self.running else None)

    def upload(self):
        if not self.connected or not self.running: return
        paths = filedialog.askopenfilenames()
        if not paths: return
        self.perform_upload(paths)

    def perform_upload(self, paths):
        if not self.running: return
        self.status_label.config(text=f"Uploading {len(paths)} file(s)...")
        logging.info(f"Starting upload of {len(paths)} files")
        
        def task():
            uploaded_names = []
            for path in paths:
                if not self.running: return
                if os.path.isdir(path): continue
                res = self.client.upload_file(path)
                if "successful" in res.lower():
                    uploaded_names.append(os.path.basename(path))
                else:
                    logging.error(f"Failed to upload {os.path.basename(path)}: {res}")
            
            if self.running:
                self.root.after(0, lambda: self.update_status_text() if self.running else None)
                self.root.after(0, lambda: self.refresh_list(new_filenames=uploaded_names) if self.running else None)
            
        threading.Thread(target=task, daemon=True).start()

    def delete(self):
        if not self.connected or not self.running: return
        selected = self.tree.selection()
        if not selected: return
        
        filenames = [self.tree.item(i)['values'][0] for i in selected]
        
        # Custom confirmation dialog centered on app
        if not self.ask_confirm_centered("Confirm Delete", f"Delete {', '.join(filenames)}?"):
            return
        
        def task():
            for filename in filenames:
                if not self.running: return
                res = self.client.delete_file(filename)
                if "failed" in res.lower() or "error" in res.lower():
                    logging.error(f"Failed to delete {filename}: {res}")
            
            if self.running:
                self.root.after(0, lambda: self.refresh_list() if self.running else None)
            
        threading.Thread(target=task, daemon=True).start()

    def ask_confirm_centered(self, title, message):
        # Create a top-level window for confirmation
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.grab_set()
        
        # Main container to allow flexible sizing
        main_frame = ttk.Frame(dialog, padding=20)
        main_frame.pack(fill="both", expand=True)
        
        label = ttk.Label(main_frame, text=message, wraplength=350, justify="center")
        label.pack(pady=(0, 20))
        
        result = tk.BooleanVar(value=False)
        
        def on_yes():
            result.set(True)
            dialog.destroy()
            
        def on_no():
            result.set(False)
            dialog.destroy()
            
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack()
        
        ttk.Button(btn_frame, text="Yes", command=on_yes).pack(side="left", padx=10)
        ttk.Button(btn_frame, text="No", command=on_no).pack(side="left", padx=10)
        
        # Center the dialog after it calculates its size
        dialog.update_idletasks()
        width = dialog.winfo_reqwidth()
        height = dialog.winfo_reqheight()
        
        # Ensure a minimum size but allow it to grow
        width = max(width, 300)
        height = max(height, 150)
        
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - (width // 2)
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - (height // 2)
        dialog.geometry(f"{width}x{height}+{x}+{y}")
        
        self.root.wait_window(dialog)
        return result.get()



if __name__ == "__main__":
    if HAS_DND:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    app = Ray5App(root)
    root.mainloop()
