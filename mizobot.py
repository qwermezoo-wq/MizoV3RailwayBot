
import os, time, requests, threading, traceback
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

# ========== إعدادات التليجرام ==========
TG_TOKEN = "8887593469:AAFKDCeleWxHuBC4p6q-vJQMTJ5V1ff0Lts"
TG_CHAT  = "5230956729"

# ========== أفضل 12 عملة ==========
SYMBOLS = [
    "BTCUSDT","ETHUSDT","SOLUSDT","ADAUSDT","BNBUSDT",
    "XRPUSDT","DOGEUSDT","DOTUSDT","LTCUSDT","AVAXUSDT",
    "TRXUSDT","UNIUSDT"
]

# ========== إعدادات الحساب الممول ==========
CAPITAL          = 50000.0
RISK_PCT         = 1.0
STOP_MULT        = 2.0
TGT_MULT         = 4.0
MAX_OPEN         = 4
VOL_MULT         = 1.5
ADX_MIN          = 20
LOOKBACK         = 20
SLIPPAGE         = 0.0003
COMMISSION       = 0.0004
MAX_DAILY_LOSS   = 2500.0
MAX_TOTAL_LOSS   = 5000.0
MIN_EQUITY       = CAPITAL - MAX_TOTAL_LOSS

# فلتر الاتجاه EMA50
EMA_TREND_PERIOD = 50
USE_TREND_FILTER = True

usdt = CAPITAL
positions = []
TOTAL_TRADES = 0
TOTAL_WINS = 0
TOTAL_LOSSES = 0
TOTAL_PNL = 0.0
daily_start_eq = CAPITAL
last_date = None
stopped_out = False
stop_reason = ""

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"V41+TREND LIVE")
    def log_message(self, *a): pass
threading.Thread(target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8000))), H).serve_forever(), daemon=True).start()

def tg(msg):
    for _ in range(3):
        try:
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                data={"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"}, timeout=15)
            return
        except: time.sleep(3)

def check_risk_limits():
    global daily_start_eq, last_date, stopped_out, stop_reason
    today = datetime.now(timezone.utc).date()
    if last_date != today:
        daily_start_eq = usdt
        last_date = today
    daily_pnl = usdt - daily_start_eq
    total_pnl = usdt - CAPITAL
    if daily_pnl <= -MAX_DAILY_LOSS:
        stopped_out = True
        stop_reason = f"⛔ تجاوز حد الخسارة اليومي (5%): {daily_pnl:+.2f}$"
        tg(stop_reason)
        return False
    if usdt <= MIN_EQUITY:
        stopped_out = True
        stop_reason = f"⛔ تجاوز حد الخسارة التراكمي (10%): {total_pnl:+.2f}$"
        tg(stop_reason)
        return False
    return True

COINGECKO_IDS = {
    "BTCUSDT":"bitcoin","ETHUSDT":"ethereum","SOLUSDT":"solana",
    "ADAUSDT":"cardano","BNBUSDT":"binancecoin","XRPUSDT":"ripple",
    "DOGEUSDT":"dogecoin","DOTUSDT":"polkadot","LTCUSDT":"litecoin",
    "AVAXUSDT":"avalanche-2","TRXUSDT":"tron","UNIUSDT":"uniswap"
}

def get_price(sym):
    try:
        r = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={sym}", timeout=5)
        if r.status_code == 200: return float(r.json()["price"])
    except: pass
    cg = COINGECKO_IDS.get(sym)
    if cg:
        try:
            r = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={cg}&vs_currencies=usd",
                             timeout=10, headers={"User-Agent":"Mozilla/5.0"})
            if r.status_code == 200 and cg in r.json(): return float(r.json()[cg]["usd"])
        except: pass
    try:
        r = requests.get(f"https://api.bybit.com/v5/market/tickers?category=spot&symbol={sym}", timeout=5)
        if r.status_code == 200 and r.json().get("retCode")==0:
            return float(r.json()["result"]["list"][0]["lastPrice"])
    except: pass
    return 0.0

def calc_ema(series, period):
    if len(series) < period: return 0.0
    k = 2.0 / (period + 1)
    val = sum(series[:period]) / period
    for v in series[period:]: val = (v - val) * k + val
    return val

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

def analyze(sym, klines):
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

    # ✅ فلتر اتجاه EMA50
    if USE_TREND_FILTER:
        ema50 = calc_ema(closes, EMA_TREND_PERIOD)
        if ema50 <= 0: return None
        trend = 'Bullish' if closes[-1] > ema50 else 'Bearish'
        if direction == 'Long' and trend != 'Bullish': return None
        if direction == 'Short' and trend != 'Bearish': return None

    risk = atr * STOP_MULT
    entry = entry_price * (1 + SLIPPAGE) if direction == 'Long' else entry_price * (1 - SLIPPAGE)
    stop = entry - risk if direction == 'Long' else entry + risk
    target = entry + atr * TGT_MULT if direction == 'Long' else entry - atr * TGT_MULT
    return {"dir": direction, "entry": entry, "stop": stop, "target": target, "atr": atr, "adx": adx}

def send_report(cycle):
    if stopped_out:
        tg(f"⛔ <b>الحساب متوقف</b>\nالسبب: {stop_reason}\nالرصيد: {usdt:.2f}$")
        return
    wr = (TOTAL_WINS/TOTAL_TRADES*100) if TOTAL_TRADES > 0 else 0.0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    daily_pnl = usdt - daily_start_eq
    total_pnl = usdt - CAPITAL
    lines = [
        f"📊 <b>تقرير V41+Trend #{cycle}</b> | {now}",
        f"━━━━━━━━━━━━━━━━━",
        f"💰 الرصيد: <b>{usdt:.2f}$</b> (رأس المال: {CAPITAL:,.0f}$)",
        f"📈 أرباح اليوم: <b>{daily_pnl:+.2f}$</b> (الحد: {MAX_DAILY_LOSS:,.0f}$)",
        f"📊 الأرباح الكلية: <b>{total_pnl:+.2f}$</b> (الحد: {MAX_TOTAL_LOSS:,.0f}$)",
        f"📋 الصفقات: {TOTAL_TRADES} | ✅ {TOTAL_WINS} | ❌ {TOTAL_LOSSES}",
        f"🎯 نسبة الربح: {wr:.1f}%",
        f"📂 مفتوحة: {len(positions)}/{MAX_OPEN}",
        f"🛡️ فلتر: EMA50 (Long↑/Short↓)"
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

tg(f"🤖 <b>بوت V41+Trend – حساب ممول 50,000$</b>\n"
   f"━━━━━━━━━━━━━━━━━\n"
   f"💰 رأس المال: {CAPITAL:,.0f}$\n"
   f"🛡️ حد خسارة يومي: {MAX_DAILY_LOSS:,.0f}$ (5%)\n"
   f"🛡️ حد خسارة تراكمي: {MAX_TOTAL_LOSS:,.0f}$ (10%)\n"
   f"📊 {len(SYMBOLS)} عملة | فريم 4H\n"
   f"⚙️ V41 + فلتر EMA50\n"
   f"🛡️ Long فقط فوق EMA50 | Short فقط تحت EMA50\n"
   f"🔄 يفحص كل دقيقة إغلاقات 4h\n"
   f"📡 تقارير كل 15 دقيقة\n"
   f"⏳ في انتظار إشارات حقيقية...")

last_close_time = {}
cycle = 0

while True:
    try:
        if stopped_out:
            time.sleep(900)
            continue
        cycle += 1
        if not check_risk_limits(): continue

        for sym in SYMBOLS:
            if stopped_out: break
            try:
                r = requests.get(f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=4h&limit=2", timeout=10)
                if r.status_code != 200: continue
                data = r.json()
                if len(data) < 2: continue
                close_time = data[-2][6]
                if sym not in last_close_time or close_time != last_close_time[sym]:
                    last_close_time[sym] = close_time
                    klines = get_klines(sym, "4h", 120)
                    sig = analyze(sym, klines)
                    if sig and len(positions) < MAX_OPEN and sym not in [p['sym'] for p in positions]:
                        entry = sig['entry']; dist = abs(entry - sig['stop'])
                        if dist > 0:
                            amount = round(usdt * RISK_PCT / 100, 2)
                            qty = round(amount / dist, 6)
                            if qty * entry >= 10:
                                positions.append({
                                    "sym": sym, "dir": sig['dir'], "entry": entry,
                                    "stop": sig['stop'], "target": sig['target'],
                                    "qty": qty, "amount": amount,
                                    "time": datetime.now(timezone.utc).strftime("%H:%M")
                                })
                                usdt -= amount
                                exp_profit = round(abs(sig['target'] - entry) * qty, 2)
                                exp_loss = round(abs(entry - sig['stop']) * qty, 2)
                                tg(f"🔔 <b>✅ فتح صفقة – V41+Trend!</b>\n"
                                   f"{'🟢 Long' if sig['dir']=='Long' else '🔴 Short'} <b>{sym}</b>\n"
                                   f"━━━━━━━━━━━━━━━━━\n"
                                   f"📍 سعر: <b>{entry:.4f} $</b>\n"
                                   f"🛑 وقف: <b>{sig['stop']:.4f} $</b>\n"
                                   f"🎯 هدف: <b>{sig['target']:.4f} $</b>\n"
                                   f"📈 ربح متوقع: <b>+{exp_profit:.2f}$</b>\n"
                                   f"📉 خسارة متوقعة: <b>-{exp_loss:.2f}$</b>\n"
                                   f"💵 مبلغ: {amount:.2f}$ | كمية: {qty:.6f}\n"
                                   f"⏰ {datetime.now(timezone.utc).strftime('%H:%M')} UTC")
            except: pass

        for pos in list(positions):
            if stopped_out: break
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
                tg(f"{'✅ ربح' if net>0 else '❌ خسارة'} | {pos['dir']} {pos['sym']} | {net:+.2f}$ | 💼 {usdt:.2f}$")
                check_risk_limits()

        if cycle % 15 == 0:
            send_report(cycle)

    except Exception as e:
        tg(f"⚠️ خطأ: {str(e)[:200]}")
    time.sleep(60)
