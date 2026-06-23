
import os, time, requests, threading, traceback
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

# ========== إعدادات التليجرام ==========
TG_TOKEN = "8887593469:AAFKDCeleWxHuBC4p6q-vJQMTJ5V1ff0Lts"
TG_CHAT  = "5230956729"

# ========== أفضل 12 عملة (بدون عملات مستقرة) ==========
SYMBOLS = [
    "BTCUSDT","ETHUSDT","TAOUSDT","SOLUSDT","XRPUSDT",
    "ZECUSDT","BNBUSDT","TRXUSDT","WLDUSDT","DOGEUSDT",
    "ADAUSDT","LTCUSDT"
]

# ========== إعدادات الاستراتيجية (V41) ==========
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

# ========== الحالة الداخلية ==========
usdt = CAPITAL
positions = []
TOTAL_TRADES = 0
TOTAL_WINS = 0
TOTAL_LOSSES = 0
TOTAL_PNL = 0.0
price_ok = True          # حالة جلب الأسعار

# ========== خادم HTTP (لـ Railway) ==========
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"V41 LIVE")
    def log_message(self, *a): pass
threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8000))), H).serve_forever(), daemon=True).start()

# ========== إرسال رسائل تيليجرام ==========
def tg(msg):
    for _ in range(3):
        try:
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                data={"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"}, timeout=15)
            return
        except: time.sleep(3)

# ========== جلب الأسعار الحية من مصدرين ==========
COINGECKO_IDS = {
    "BTCUSDT":"bitcoin","ETHUSDT":"ethereum","TAOUSDT":"tao","SOLUSDT":"solana",
    "XRPUSDT":"ripple","ZECUSDT":"zcash","BNBUSDT":"binancecoin","TRXUSDT":"tron",
    "WLDUSDT":"worldcoin","DOGEUSDT":"dogecoin","ADAUSDT":"cardano","LTCUSDT":"litecoin"
}

def get_price(sym):
    """جلب السعر الحي من CoinGecko أولاً، ثم Binance كبديل"""
    # المصدر 1: CoinGecko
    cg_id = COINGECKO_IDS.get(sym)
    if cg_id:
        for _ in range(2):
            try:
                r = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd",
                    timeout=10, headers={"User-Agent":"Mozilla/5.0"})
                if r.status_code == 200:
                    data = r.json()
                    if cg_id in data:
                        return float(data[cg_id]["usd"])
            except: pass
            time.sleep(2)
    # المصدر 2: Binance
    try:
        r = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={sym}", timeout=10)
        if r.status_code == 200:
            return float(r.json()["price"])
    except: pass
    return 0.0

# ========== جلب الشموع للتحليل ==========
def get_klines(sym, interval, limit=200):
    for _ in range(3):
        try:
            r = requests.get(f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={interval}&limit={limit}", timeout=15)
            if r.status_code == 200:
                return [{"open":float(k[1]),"high":float(k[2]),"low":float(k[3]),"close":float(k[4]),"volume":float(k[5])} for k in r.json()]
        except: pass
        time.sleep(3)
    return []

# ========== المؤشرات ==========
def calc_atr(highs, lows, closes, period=14):
    if len(closes) < period+1: return 0.0
    trs = [max(highs[i]-lows[i], abs(highs[i]-closes[i-1]), abs(lows[i]-closes[i-1])) for i in range(1, len(closes))]
    trs = trs[-period:]
    return sum(trs)/period if trs else 0.0

def calc_adx(highs, lows, closes, period=14):
    n = len(closes)
    if n < period*2+1: return 0.0
    h, l, c = highs[-30:], lows[-30:], closes[-30:]
    trs = [max(h[i]-l[i], abs(h[i]-c[i-1]), abs(l[i]-c[i-1])) for i in range(1, len(h))]
    pdm = [max(0, h[i]-h[i-1]) if h[i]-h[i-1] > l[i-1]-l[i] else 0 for i in range(1, len(h))]
    mdm = [max(0, l[i-1]-l[i]) if l[i-1]-l[i] > h[i]-h[i-1] else 0 for i in range(1, len(h))]
    atr_s = sum(trs[-period:])/period
    p_s = sum(pdm[-period:])/period
    m_s = sum(mdm[-period:])/period
    if atr_s == 0: return 0.0
    pdi, mdi = 100*p_s/atr_s, 100*m_s/atr_s
    denom = pdi + mdi
    return 100*abs(pdi-mdi)/denom if denom != 0 else 0.0

# ========== التحليل واتخاذ القرار ==========
def analyze(sym):
    klines = get_klines(sym, "4h", 150)
    if len(klines) < 120: return None

    closes = [c['close'] for c in klines]
    highs  = [c['high'] for c in klines]
    lows   = [c['low'] for c in klines]
    volumes = [c['volume'] for c in klines]

    recent = klines[-LOOKBACK-1:-1]
    highest = max(c['high'] for c in recent)
    lowest  = min(c['low'] for c in recent)

    atr = calc_atr(highs, lows, closes, 14)
    if atr <= 0: return None

    adx = calc_adx(highs, lows, closes, 14)
    if adx < ADX_MIN: return None

    avg_vol = sum(volumes[-LOOKBACK-1:-1]) / LOOKBACK
    if volumes[-2] < avg_vol * VOL_MULT: return None

    current = klines[-1]
    direction = None
    entry_price = 0.0

    if current['high'] > highest:
        direction = 'Long'
        entry_price = highest
    elif current['low'] < lowest:
        direction = 'Short'
        entry_price = lowest

    if direction is None: return None

    risk = atr * STOP_MULT
    entry = entry_price * (1 + SLIPPAGE) if direction == 'Long' else entry_price * (1 - SLIPPAGE)
    stop = entry - risk if direction == 'Long' else entry + risk
    target = entry + atr * TGT_MULT if direction == 'Long' else entry - atr * TGT_MULT

    return {"dir": direction, "entry": entry, "stop": stop, "target": target, "atr": atr, "adx": adx}

# ========== تقرير كل 15 دقيقة ==========
def send_report(cycle):
    global price_ok
    wr = (TOTAL_WINS/TOTAL_TRADES*100) if TOTAL_TRADES > 0 else 0.0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    status = "✅ الأسعار حية" if price_ok else "❌ فشل جلب الأسعار"
    lines = [
        f"📊 <b>تقرير V41 #{cycle}</b> | {now}",
        f"{status}",
        f"━━━━━━━━━━━━━━━━━",
        f"💰 الرصيد: <b>{usdt:.2f}$</b>",
        f"📈 الأرباح: <b>{TOTAL_PNL:+.2f}$</b>",
        f"📋 الصفقات: {TOTAL_TRADES} | ✅ {TOTAL_WINS} | ❌ {TOTAL_LOSSES}",
        f"🎯 نسبة الربح: {wr:.1f}%",
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
                net_unr = unr - fee
                pct = net_unr/p["amount"]*100
                icon = "🟢" if net_unr>=0 else "🔴"
                lines.append(
                    f"{icon} {p['dir']} {p['sym']}\n"
                    f"   دخول: {p['entry']:.4f} | الآن: {cur:.4f}\n"
                    f"   P&L: {net_unr:+.2f}$ ({pct:+.1f}%)\n"
                    f"   وقف: {p['stop']:.4f} | هدف: {p['target']:.4f}"
                )
    tg("\n".join(lines))

# ========== رسالة البداية ==========
tg(f"🤖 <b>بوت V41 – النسخة النهائية</b>\n"
   f"━━━━━━━━━━━━━━━━━\n"
   f"💰 رأس المال: {CAPITAL:.2f}$\n"
   f"⚙️ كسر القمم والقيعان + ADX + حجم\n"
   f"📊 {len(SYMBOLS)} عملة | فريم 4H\n"
   f"🔄 يفحص كل 15 دقيقة\n"
   f"📱 أسعار حية من CoinGecko + Binance\n"
   f"✅ جاهز لفتح الصفقات تلقائياً")

# ========== الحلقة الرئيسية ==========
cycle = 0
while True:
    try:
        cycle += 1

        # 1. اختبار الاتصال وجلب الأسعار
        test_price = get_price("BTCUSDT")
        if test_price <= 0:
            price_ok = False
            tg("⚠️ <b>فشل جلب الأسعار الحية!</b> سأحاول مجدداً.")
        else:
            price_ok = True

        # 2. إدارة الصفقات المفتوحة
        for pos in list(positions):
            price = get_price(pos["sym"])
            if price <= 0: continue
            hit = None; reason = ""
            if pos["dir"] == "Long":
                if price <= pos["stop"]: hit = pos["stop"]; reason = "وقف الخسارة"
                elif price >= pos["target"]: hit = pos["target"]; reason = "هدف الربح"
            else:
                if price >= pos["stop"]: hit = pos["stop"]; reason = "وقف الخسارة"
                elif price <= pos["target"]: hit = pos["target"]; reason = "هدف الربح"
            if hit:
                pnl = (hit-pos["entry"])*pos["qty"] if pos["dir"]=="Long" else (pos["entry"]-hit)*pos["qty"]
                fee = (pos["entry"]+hit)*pos["qty"]*COMMISSION
                net = pnl - fee
                usdt += pos["amount"] + net
                TOTAL_PNL += net
                TOTAL_TRADES += 1
                if net > 0: TOTAL_WINS += 1
                else: TOTAL_LOSSES += 1
                positions.remove(pos)
                icon = "✅" if net>0 else "❌"
                tg(f"{icon} <b>{'ربح' if net>0 else 'خسارة'} | {pos['dir']} {pos['sym']}</b>\n"
                   f"السبب: {reason}\n"
                   f"📍 دخول: {pos['entry']:.4f} | خروج: {hit:.4f}\n"
                   f"💰 P&L: <b>{net:+.2f}$</b>\n"
                   f"💼 الرصيد: {usdt:.2f}$")

        # 3. فتح صفقات جديدة
        if len(positions) < MAX_OPEN:
            open_syms = [p["sym"] for p in positions]
            for sym in SYMBOLS:
                if len(positions) >= MAX_OPEN: break
                if sym in open_syms: continue
                sig = analyze(sym)
                if not sig: continue
                entry = sig["entry"]
                dist = abs(entry - sig["stop"])
                if dist <= 0: continue
                amount = round(usdt * RISK_PCT / 100, 2)
                qty = round(amount / dist, 6)
                if qty * entry < 5: continue
                positions.append({
                    "sym": sym, "dir": sig["dir"], "entry": entry,
                    "stop": sig["stop"], "target": sig["target"],
                    "qty": qty, "amount": amount,
                    "time": datetime.now(timezone.utc).strftime("%H:%M")
                })
                usdt -= amount
                rr = round(abs(sig["target"]-entry)/dist, 1)
                tg(f"🔔 <b>✅ فتح صفقة حقيقية – V41!</b>\n"
                   f"{'🟢 Long' if sig['dir']=='Long' else '🔴 Short'} <b>{sym}</b>\n"
                   f"━━━━━━━━━━━━━━━━━\n"
                   f"📍 سعر: <b>{entry:.4f} $</b>\n"
                   f"🛑 وقف: <b>{sig['stop']:.4f} $</b>\n"
                   f"🎯 هدف: <b>{sig['target']:.4f} $</b>\n"
                   f"⚖️ R:R = 1:{rr}\n"
                   f"📊 ADX: {sig['adx']:.1f}\n"
                   f"💵 مبلغ: {amount:.2f}$ | كمية: {qty:.6f}\n"
                   f"⏰ {datetime.now(timezone.utc).strftime('%H:%M')} UTC\n\n"
                   f"✅ <b>تم فتح الصفقة تلقائياً بنجاح</b>")
                time.sleep(2)

        # 4. إرسال التقرير الدوري
        send_report(cycle)

    except Exception as e:
        tg(f"⚠️ خطأ: {str(e)[:200]}")
    time.sleep(900)
