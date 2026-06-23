
import os, time, requests, threading, traceback
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

# ========== الإعدادات ==========
TG_TOKEN = "8887593469:AAFKDCeleWxHuBC4p6q-vJQMTJ5V1ff0Lts"
TG_CHAT  = "5230956729"

SYMBOLS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT",
    "ADAUSDT","DOGEUSDT","DOTUSDT","LTCUSDT","LINKUSDT",
    "AVAXUSDT","UNIUSDT"
]

CAPITAL    = 100.0
RISK_PCT   = 1.0
STOP_MULT  = 2.0
TGT_MULT   = 4.0
MAX_OPEN   = 3
VOL_MULT   = 1.5
ADX_MIN    = 20
LOOKBACK   = 20
SLIPPAGE   = 0.0003
COMMISSION = 0.0004

usdt = CAPITAL
positions = []
TOTAL_TRADES = 0
TOTAL_WINS = 0
TOTAL_LOSSES = 0
TOTAL_PNL = 0.0

# ========== خادم HTTP ==========
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"V42 LIVE")
    def log_message(self, *a): pass
threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8000))), H).serve_forever(), daemon=True).start()

def tg(msg):
    for _ in range(3):
        try:
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                data={"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"}, timeout=15)
            return
        except: time.sleep(3)

# ========== جلب السعر الحي ==========
def get_price(sym):
    try:
        r = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={sym}", timeout=10)
        if r.status_code == 200: return float(r.json()["price"])
    except: pass
    return 0.0

# ========== مؤشرات ==========
def calc_atr(highs, lows, closes, period=14):
    if len(closes) < period+1: return 0.0
    trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])) for i in range(1, len(closes))]
    return sum(trs[-period:])/period if trs else 0.0

def calc_adx(highs, lows, closes, period=14):
    n = len(closes)
    if n < period*2+1: return 0.0
    h, l, c = highs[-30:], lows[-30:], closes[-30:]
    trs = [max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])) for i in range(1, len(h))]
    pdm = [max(0, h[i]-h[i-1]) if h[i]-h[i-1] > l[i-1]-l[i] else 0 for i in range(1, len(h))]
    mdm = [max(0, l[i-1]-l[i]) if l[i-1]-l[i] > h[i]-h[i-1] else 0 for i in range(1, len(h))]
    atr_s = sum(trs[-period:])/period; p_s = sum(pdm[-period:])/period; m_s = sum(mdm[-period:])/period
    if atr_s == 0: return 0.0
    pdi, mdi = 100*p_s/atr_s, 100*m_s/atr_s
    denom = pdi + mdi
    return 100*abs(pdi-mdi)/denom if denom != 0 else 0.0

def get_klines(sym, interval, limit=200):
    try:
        r = requests.get(f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={interval}&limit={limit}", timeout=15)
        if r.status_code == 200:
            return [{"open":float(k[1]),"high":float(k[2]),"low":float(k[3]),"close":float(k[4]),"volume":float(k[5])} for k in r.json()]
    except: pass
    return []

def analyze(sym):
    klines = get_klines(sym, "4h", 150)
    if len(klines) < 120: return None
    closes = [c['close'] for c in klines]; highs = [c['high'] for c in klines]
    lows = [c['low'] for c in klines]; volumes = [c['volume'] for c in klines]
    recent = klines[-LOOKBACK-1:-1]; highest = max(c['high'] for c in recent); lowest = min(c['low'] for c in recent)
    atr = calc_atr(highs, lows, closes, 14)
    if atr <= 0: return None
    adx = calc_adx(highs, lows, closes, 14)
    if adx < ADX_MIN: return None
    avg_vol = sum(volumes[-LOOKBACK-1:-1]) / LOOKBACK
    if volumes[-2] < avg_vol * VOL_MULT: return None
    current = klines[-1]; direction = None; entry_price = 0.0
    if current['high'] > highest: direction = 'Long'; entry_price = highest
    elif current['low'] < lowest: direction = 'Short'; entry_price = lowest
    if direction is None: return None
    risk = atr * STOP_MULT
    entry = entry_price * (1 + SLIPPAGE) if direction == 'Long' else entry_price * (1 - SLIPPAGE)
    stop = entry - risk if direction == 'Long' else entry + risk
    target = entry + atr * TGT_MULT if direction == 'Long' else entry - atr * TGT_MULT
    return {"dir": direction, "entry": entry, "stop": stop, "target": target, "atr": atr, "adx": adx}

def send_report(cycle, forced=False):
    wr = (TOTAL_WINS/TOTAL_TRADES*100) if TOTAL_TRADES > 0 else 0.0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"📊 <b>{'تقرير تجريبي' if forced else 'تقرير'} V42 #{cycle}</b> | {now}",
        f"━━━━━━━━━━━━━━━━━",
        f"💰 الرصيد: <b>{usdt:.2f}$</b>",
        f"📈 الأرباح: <b>{TOTAL_PNL:+.2f}$</b>",
        f"📋 الصفقات: {TOTAL_TRADES} | ✅ {TOTAL_WINS} | ❌ {TOTAL_LOSSES}",
        f"📂 مفتوحة: {len(positions)}/{MAX_OPEN}"
    ]
    if positions:
        lines.append("━━━━━━━━━━━━━━━━━")
        lines.append("📌 <b>الصفقات المفتوحة:</b>")
        for p in positions:
            cur = get_price(p["sym"])
            if cur > 0:
                unr = (cur-p["entry"])*p["qty"] if p["dir"]=="Long" else (p["entry"]-cur)*p["qty"]
                fee = p["entry"]*p["qty"]*COMMISSION
                net_unr = unr - fee; pct = net_unr/p["amount"]*100
                icon = "🟢" if net_unr>=0 else "🔴"
                lines.append(f"{icon} {p['dir']} {p['sym']} | دخول:{p['entry']:.4f} → الآن:{cur:.4f} | {net_unr:+.2f}$")
    tg("\n".join(lines))

# ========== 3 صفقات تجريبية سريعة (Scalping) ==========
def open_demo_trades():
    global usdt
    tg("🚀 <b>جاري فتح 3 صفقات تجريبية (Scalping) بأسعار السوق الحقيقية...</b>")
    demos = [("BTCUSDT", "Long"), ("ETHUSDT", "Short"), ("SOLUSDT", "Long")]
    for i, (sym, dir_) in enumerate(demos):
        if i > 0: time.sleep(900)  # 15 دقيقة بين كل صفقة
        price = get_price(sym)
        if price <= 0:
            tg(f"❌ فشل جلب سعر {sym}")
            continue
        atr_val = price * 0.005  # 0.5% تقريباً
        stop = round(price - atr_val * STOP_MULT, 4) if dir_ == "Long" else round(price + atr_val * STOP_MULT, 4)
        target = round(price + atr_val * TGT_MULT, 4) if dir_ == "Long" else round(price - atr_val * TGT_MULT, 4)
        amount = round(usdt * RISK_PCT / 100, 2)
        dist = abs(price - stop)
        qty = round(amount / dist, 6) if dist > 0 else 0
        if qty * price < 5: continue
        positions.append({
            "sym": sym, "dir": dir_, "entry": price,
            "stop": stop, "target": target,
            "qty": qty, "amount": amount, "demo": True,
            "time": datetime.now(timezone.utc).strftime("%H:%M")
        })
        usdt -= amount
        tg(f"🧪 <b>صفقة تجريبية #{i+1}</b>\n"
           f"{'🟢 Long' if dir_=='Long' else '🔴 Short'} <b>{sym}</b>\n"
           f"━━━━━━━━━━━━━━━━━\n"
           f"📍 سعر: <b>{price:.4f} $</b>\n"
           f"🛑 وقف: <b>{stop:.4f} $</b>\n"
           f"🎯 هدف: <b>{target:.4f} $</b>\n"
           f"💵 مبلغ: {amount:.2f}$ | كمية: {qty:.6f}\n"
           f"⏰ {datetime.now(timezone.utc).strftime('%H:%M')} UTC")
        send_report(i+1, forced=True)

tg(f"🤖 <b>بوت V42 – محاكاة حية كاملة</b>\n"
   f"━━━━━━━━━━━━━━━━━\n"
   f"💰 رأس المال: {CAPITAL:.2f}$\n"
   f"📊 {len(SYMBOLS)} عملة | فريم 4H\n"
   f"🧪 سيفتح 3 صفقات تجريبية الآن\n"
   f"📡 ثم يستمر في البحث عن الفرص الحقيقية\n"
   f"🔄 تقارير كل 15 دقيقة")

open_demo_trades()
cycle = 3

while True:
    try:
        cycle += 1

        # إدارة الصفقات المفتوحة (تجريبية وحقيقية)
        for pos in list(positions):
            price = get_price(pos["sym"])
            if price <= 0: continue
            hit = None; reason = ""
            if pos["dir"] == "Long":
                if price <= pos["stop"]: hit = pos["stop"]; reason = "وقف"
                elif price >= pos["target"]: hit = pos["target"]; reason = "هدف"
            else:
                if price >= pos["stop"]: hit = pos["stop"]; reason = "وقف"
                elif price <= pos["target"]: hit = pos["target"]; reason = "هدف"
            if hit:
                pnl = (hit-pos["entry"])*pos["qty"] if pos["dir"]=="Long" else (pos["entry"]-hit)*pos["qty"]
                fee = (pos["entry"]+hit)*pos["qty"]*COMMISSION
                net = pnl - fee
                usdt += pos["amount"] + net
                TOTAL_PNL += net; TOTAL_TRADES += 1
                if net > 0: TOTAL_WINS += 1
                else: TOTAL_LOSSES += 1
                positions.remove(pos)
                tag = "🧪 تجريبي" if pos.get("demo") else "✅ حقيقي"
                tg(f"{'✅ ربح' if net>0 else '❌ خسارة'} | {tag} | {pos['dir']} {pos['sym']} | {net:+.2f}$ | 💼 {usdt:.2f}$")

        # البحث عن فرص حقيقية (استراتيجية V41)
        if len(positions) < MAX_OPEN:
            open_syms = [p["sym"] for p in positions]
            for sym in SYMBOLS:
                if len(positions) >= MAX_OPEN: break
                if sym in open_syms: continue
                sig = analyze(sym)
                if not sig: continue
                entry = sig["entry"]; dist = abs(entry - sig["stop"])
                if dist <= 0: continue
                amount = round(usdt * RISK_PCT / 100, 2)
                qty = round(amount / dist, 6)
                if qty * entry < 5: continue
                positions.append({
                    "sym": sym, "dir": sig["dir"], "entry": entry,
                    "stop": sig["stop"], "target": sig["target"],
                    "qty": qty, "amount": amount, "demo": False,
                    "time": datetime.now(timezone.utc).strftime("%H:%M")
                })
                usdt -= amount
                tg(f"🔔 <b>✅ فتح صفقة حقيقية – V41!</b>\n"
                   f"{'🟢 Long' if sig['dir']=='Long' else '🔴 Short'} <b>{sym}</b>\n"
                   f"📍 سعر: <b>{entry:.4f} $</b>\n"
                   f"🛑 وقف: <b>{sig['stop']:.4f} $</b>\n"
                   f"🎯 هدف: <b>{sig['target']:.4f} $</b>\n"
                   f"💵 مبلغ: {amount:.2f}$ | كمية: {qty:.6f}")

        if cycle % 15 == 0:
            send_report(cycle)

    except Exception as e:
        tg(f"⚠️ خطأ: {str(e)[:200]}")
    time.sleep(60)
