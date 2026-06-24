
import os, time, requests, threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

TG_TOKEN = "8887593469:AAFKDCeleWxHuBC4p6q-vJQMTJ5V1ff0Lts"
TG_CHAT  = "5230956729"

def tg(msg):
    try:
        requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                      data={"chat_id": TG_CHAT, "text": msg}, timeout=15)
    except: pass

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *a): pass

threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8000))), H).serve_forever(), daemon=True).start()

tg("🟢 تم تشغيل البوت بنجاح على Railway!")

count = 0
while True:
    time.sleep(30)
    count += 1
    now = datetime.now(timezone.utc).strftime("%H:%M:%S")
    tg(f"💓 نبضة #{count} | {now} UTC")
