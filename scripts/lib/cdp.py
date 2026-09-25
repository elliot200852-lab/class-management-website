#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cdp.py — 用 Chrome DevTools Protocol 驅動本機的無頭 Chrome（只用標準庫）。

給 scripts/verify_site.py 用：開頁、設手機或桌機的畫面大小（用 CDP 模擬，不用 --window-size，
那種做法在窄寬度會出現假的橫向溢出）、收主控台錯誤、截圖。

  · find_chrome()：找這台電腦的 Chrome／Chromium（Mac、Windows、Linux 常見位置＋PATH）。
  · Browser：啟動無頭 Chrome（暫存的使用者資料夾，結束時刪掉），連上瀏覽器層的 WebSocket。
  · Page：一個分頁（flatten session），send() 送指令、events 收事件。

WebSocket 只實作 CDP 用得到的部分（文字框、分段、ping／pong、關閉），不支援壓縮擴充。
"""
import os
import sys
import json
import time
import base64
import shutil
import socket
import struct
import tempfile
import subprocess
import urllib.request


# ── 找 Chrome ─────────────────────────────────────────────────────────
def find_chrome():
    """回傳 Chrome／Chromium 執行檔的絕對路徑，找不到回 None。"""
    env = os.environ.get("CMW_CHROME")
    if env and os.path.isfile(env):
        return env
    cands = []
    if sys.platform == "darwin":
        for base in ("/Applications", os.path.expanduser("~/Applications")):
            cands += [
                os.path.join(base, "Google Chrome.app", "Contents", "MacOS", "Google Chrome"),
                os.path.join(base, "Chromium.app", "Contents", "MacOS", "Chromium"),
                os.path.join(base, "Google Chrome Canary.app", "Contents", "MacOS", "Google Chrome Canary"),
            ]
    elif sys.platform.startswith("win"):
        for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(var)
            if base:
                cands.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
                cands.append(os.path.join(base, "Chromium", "Application", "chrome.exe"))
    for c in cands:
        if os.path.isfile(c):
            return c
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    return None


# ── 最小的 WebSocket 用戶端 ────────────────────────────────────────────
class WebSocket:
    def __init__(self, url, timeout=30):
        if not url.startswith("ws://"):
            raise ValueError("只支援 ws://")
        rest = url[len("ws://"):]
        hostport, _, path = rest.partition("/")
        host, _, port = hostport.partition(":")
        self.sock = socket.create_connection((host, int(port or 80)), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = ("GET /%s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n") % (path, hostport, key)
        self.sock.sendall(req.encode("ascii"))
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("WebSocket 握手失敗")
            buf += chunk
        head, _, rest_bytes = buf.partition(b"\r\n\r\n")
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError("WebSocket 握手被拒：%r" % head.split(b"\r\n", 1)[0])
        # 收到的位元組先全部放進緩衝，湊滿一整個框才解析：
        # 這樣讀到一半逾時（pump 用短逾時收事件）也不會把半個框弄丟。
        self._buf = bytearray(rest_bytes)
        self._parts = []

    def _fill(self):
        chunk = self.sock.recv(1 << 20)
        if not chunk:
            raise ConnectionError("WebSocket 連線中斷")
        self._buf += chunk

    def _try_frame(self):
        """緩衝裡湊滿一個框就取出 (fin, op, data)，不夠回 None。"""
        buf = self._buf
        if len(buf) < 2:
            return None
        b1, b2 = buf[0], buf[1]
        n = b2 & 0x7F
        i = 2
        if n == 126:
            if len(buf) < 4:
                return None
            n = struct.unpack(">H", bytes(buf[2:4]))[0]
            i = 4
        elif n == 127:
            if len(buf) < 10:
                return None
            n = struct.unpack(">Q", bytes(buf[2:10]))[0]
            i = 10
        mask = None
        if b2 & 0x80:
            if len(buf) < i + 4:
                return None
            mask = bytes(buf[i:i + 4])
            i += 4
        if len(buf) < i + n:
            return None
        data = bytes(buf[i:i + n])
        del buf[:i + n]
        if mask:
            data = bytes(b ^ mask[k % 4] for k, b in enumerate(data))
        return bool(b1 & 0x80), b1 & 0x0F, data

    def send(self, text):
        payload = text.encode("utf-8")
        header = bytearray([0x81])
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        mask = os.urandom(4)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def recv(self):
        """回傳一則完整的文字訊息（str）；連線關閉丟 ConnectionError。"""
        while True:
            frame = self._try_frame()
            if frame is None:
                self._fill()
                continue
            fin, op, data = frame
            if op == 0x8:
                raise ConnectionError("WebSocket 被關閉")
            if op == 0x9:  # ping → pong
                self._send_control(0xA, data)
                continue
            if op == 0xA:
                continue
            self._parts.append(data)
            if fin:
                out = b"".join(self._parts).decode("utf-8")
                self._parts = []
                return out

    def _send_control(self, op, data):
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self.sock.sendall(bytes([0x80 | op, 0x80 | len(data)]) + mask + masked)

    def close(self):
        try:
            self._send_control(0x8, b"")
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


# ── 瀏覽器與分頁 ──────────────────────────────────────────────────────
class CDPError(Exception):
    pass


class Browser:
    def __init__(self, chrome_path, timeout=30):
        self.profile = tempfile.mkdtemp(prefix="cmw-chrome-")
        args = [chrome_path, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                "--disable-extensions", "--disable-background-networking", "--disable-sync",
                "--hide-scrollbars", "--mute-audio", "--allow-file-access-from-files",
                "--remote-debugging-port=0", "--user-data-dir=%s" % self.profile]
        # CI 的 Linux 機器有時不准 Chrome 開沙箱：用環境變數 CMW_CHROME_ARGS 補參數（例如 --no-sandbox），
        # 只給 CI 用，老師的電腦不需要。
        args += [a for a in os.environ.get("CMW_CHROME_ARGS", "").split() if a.startswith("--")]
        args.append("about:blank")
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        port_file = os.path.join(self.profile, "DevToolsActivePort")
        deadline = time.time() + timeout
        port = None
        while time.time() < deadline:
            if os.path.exists(port_file):
                try:
                    with open(port_file, encoding="utf-8") as fh:
                        first = fh.readline().strip()
                    if first.isdigit():
                        port = int(first)
                        break
                except OSError:
                    pass
            if self.proc.poll() is not None:
                break
            time.sleep(0.1)
        if not port:
            self.close()
            raise CDPError("Chrome 沒有啟動成功（找不到除錯埠）")
        with urllib.request.urlopen("http://127.0.0.1:%d/json/version" % port, timeout=10) as r:
            info = json.loads(r.read().decode("utf-8"))
        self.ws = WebSocket(info["webSocketDebuggerUrl"], timeout=timeout)
        self._id = 0
        self.events = []

    def send(self, method, params=None, session_id=None, timeout=30):
        self._id += 1
        mid = self._id
        msg = {"id": mid, "method": method, "params": params or {}}
        if session_id:
            msg["sessionId"] = session_id
        self.ws.send(json.dumps(msg))
        deadline = time.time() + timeout
        while True:
            if time.time() > deadline:
                raise CDPError("CDP 指令逾時：%s" % method)
            data = json.loads(self.ws.recv())
            if data.get("id") == mid:
                if "error" in data:
                    raise CDPError("%s：%s" % (method, data["error"].get("message")))
                return data.get("result", {})
            if "method" in data:
                self.events.append(data)

    def pump(self, seconds):
        """把這段時間內的事件收進 self.events。"""
        self.ws.sock.settimeout(seconds)
        try:
            while True:
                data = json.loads(self.ws.recv())
                if "method" in data:
                    self.events.append(data)
        except (socket.timeout, TimeoutError):
            pass
        finally:
            self.ws.sock.settimeout(30)

    def new_page(self, isolated=False):
        """開一個新分頁。isolated=True：放在全新的瀏覽器情境裡（跟別的分頁不共用 cookie、localStorage、
        IndexedDB——模擬器冒煙測試用它讓每個登入身分互不干擾）。"""
        params = {"url": "about:blank"}
        if isolated:
            params["browserContextId"] = self.send("Target.createBrowserContext")["browserContextId"]
        t = self.send("Target.createTarget", params)
        s = self.send("Target.attachToTarget", {"targetId": t["targetId"], "flatten": True})
        return Page(self, s["sessionId"], t["targetId"])

    def close(self):
        try:
            if getattr(self, "ws", None):
                try:
                    self.send("Browser.close", timeout=5)
                except Exception:
                    pass
                self.ws.close()
        finally:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
            shutil.rmtree(self.profile, ignore_errors=True)


class Page:
    def __init__(self, browser, session_id, target_id):
        self.b = browser
        self.sid = session_id
        self.tid = target_id

    def send(self, method, params=None, timeout=30):
        return self.b.send(method, params, session_id=self.sid, timeout=timeout)

    def my_events(self, clear=True):
        mine = [e for e in self.b.events if e.get("sessionId") == self.sid]
        if clear:
            self.b.events = [e for e in self.b.events if e.get("sessionId") != self.sid]
        return mine

    def evaluate(self, expr, timeout=30):
        r = self.send("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": True},
                      timeout=timeout)
        if r.get("exceptionDetails"):
            d = r["exceptionDetails"]
            desc = ((d.get("exception") or {}).get("description") or "")[:300]
            raise CDPError("頁面裡的程式出錯：%s %s" % (d.get("text"), desc))
        return r.get("result", {}).get("value")

    def wait_for(self, expr, timeout=15, interval=0.1):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.evaluate(expr):
                    return True
            except CDPError:
                pass
            self.b.pump(interval)
        return False

    def screenshot(self, path, full_page=True):
        params = {"format": "png", "captureBeyondViewport": bool(full_page)}
        if full_page:
            m = self.send("Page.getLayoutMetrics")
            size = m.get("cssContentSize") or m.get("contentSize")
            vp = m.get("cssVisualViewport") or m.get("visualViewport") or {}
            width = vp.get("clientWidth") or size["width"]
            params["clip"] = {"x": 0, "y": 0, "width": width, "height": min(size["height"], 12000), "scale": 1}
        data = self.send("Page.captureScreenshot", params, timeout=60)["data"]
        with open(path, "wb") as fh:
            fh.write(base64.b64decode(data))
