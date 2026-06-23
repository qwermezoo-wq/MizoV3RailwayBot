
import os, time, requests, threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

TG_TOKEN = "8887593469:AAFKDCeleWxHuBC4p6q-vJQMTJ5V1ff0Lts"
TG_CHAT  = "5230956729"
SYMBOLS = ["BTCUSDT","ETHUSDT","SOLUSDT","ADAUSDT","BNBUSDT","XRPUSDT","LTCUSDT","DOGEUSDT","DOTUSDT","AVAXUSDT","LINKUSDT","UNIUSDT","ATOMUSDT","TRXUSDT","NEARUSDT"]

CAPITAL    = 10000.0
RISK_PCT   = 1.0
STOP_MULT  = 1.5
TGT_MULT   = 3.0
MAX_OPEN   = 4
VOL_MULT   = 1.2
ADX_MIN    = 22
MIN_ATR_PCT= 0.15
SLIPPAGE   = 0.0003
COMMISSION = 0.0004

usdt=CAPITAL; positions=[]; TOTAL_TRADES=0; TOTAL_WINS=0; TOTAL_LOSSES=0; TOTAL_PNL=0.0

# ========== فلترة العملات الخاسرة ==========
BLACKLIST = {}          # {sym: عدد الخسائر المتتالية}
MAX_CONSECUTIVE_LOSSES = 3
BLACKLIST_DURATION = 48  # ساعة ثم نعيدها للتجربة

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    def log_message(self,*a): pass
threading.Thread(target=lambda:HTTPServer(("0.0.0.0",int(os.environ.get("PORT",8000))),H).serve_forever(),daemon=True).start()

def tg(msg):
    for _ in range(3):
        try:
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                data={"chat_id":TG_CHAT,"text":msg,"parse_mode":"HTML"},timeout=15)
            return
        except: time.sleep(3)

COINGECKO_IDS = {
    "BTCUSDT":"bitcoin","ETHUSDT":"ethereum","SOLUSDT":"solana",
    "ADAUSDT":"cardano","BNBUSDT":"binancecoin","XRPUSDT":"ripple",
    "LTCUSDT":"litecoin","DOGEUSDT":"dogecoin","DOTUSDT":"polkadot",
    "AVAXUSDT":"avalanche-2","LINKUSDT":"chainlink","UNIUSDT":"uniswap",
    "ATOMUSDT":"cosmos","TRXUSDT":"tron","NEARUSDT":"near"
}

def get_price(sym):
    cg_id = COINGECKO_IDS.get(sym)
    if not cg_id: return 0.0
    for _ in range(3):
        try:
            r = requests.get(
                f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}&vs_currencies=usd",
                timeout=15, headers={"User-Agent":"Mozilla/5.0"})
            if r.status_code == 200:
                data = r.json()
                if cg_id in data: return float(data[cg_id]["usd"])
        except: pass
        time.sleep(5)
    return 0.0

def get_klines(sym, interval, limit=200):
    urls = [
        f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={interval}&limit={limit}",
        f"https://api1.binance.com/api/v3/klines?symbol={sym}&interval={interval}&limit={limit}",
        f"https://api2.binance.com/api/v3/klines?symbol={sym}&interval={interval}&limit={limit}",
    ]
    for url in urls:
        for _ in range(2):
            try:
                r = requests.get(url, timeout=15, headers={"User-Agent":"Mozilla/5.0"})
                if r.status_code == 200:
                    return [{"open":float(k[1]),"high":float(k[2]),"low":float(k[3]),"close":float(k[4]),"volume":float(k[5])} for k in r.json()]
            except: pass
            time.sleep(3)
    return []

def ema(s,p):
    if len(s)<p: return 0.0
    k=2.0/(p+1); v=sum(s[:p])/p
    for x in s[p:]: v=(x-v)*k+v
    return v

def atr_calc(hi,lo,cl,p=14):
    if len(hi)<p+1: return 0.0
    trs=[max(hi[i]-lo[i],abs(hi[i]-cl[i-1]),abs(lo[i]-cl[i-1])) for i in range(1,len(hi))]
    v=sum(trs[:p])/p
    for t in trs[p:]: v=(v*(p-1)+t)/p
    return v

def rsi_calc(cl,p=14):
    if len(cl)<p+1: return 50.0
    g=l=0.0
    for i in range(1,p+1):
        d=cl[i]-cl[i-1]
        if d>0: g+=d
        else: l-=d
    ag,al=g/p,l/p
    for i in range(p+1,len(cl)):
        d=cl[i]-cl[i-1]
        ag=(ag*(p-1)+(d if d>0 else 0))/p
        al=(al*(p-1)+(-d if d<0 else 0))/p
    return 100.0 if al==0 else 100.0-100.0/(1+ag/al)

def adx_calc(hi,lo,cl,p=14):
    n=len(hi)
    if n<p*2: return 0.0
    trs,pdms,mdms=[],[],[]
    for i in range(1,n):
        trs.append(max(hi[i]-lo[i],abs(hi[i]-cl[i-1]),abs(lo[i]-cl[i-1])))
        up,dn=hi[i]-hi[i-1],lo[i-1]-lo[i]
        pdms.append(up if up>dn and up>0 else 0.0)
        mdms.append(dn if dn>up and dn>0 else 0.0)
    av=sum(trs[:p])/p; pv=sum(pdms[:p])/p; mv=sum(mdms[:p])/p
    for i in range(p,len(trs)):
        av=(av*(p-1)+trs[i])/p; pv=(pv*(p-1)+pdms[i])/p; mv=(mv*(p-1)+mdms[i])/p
    if av==0: return 0.0
    pdi,mdi=100*pv/av,100*mv/av; d=pdi+mdi
    return 100*abs(pdi-mdi)/d if d>0 else 0.0

def analyze(sym):
    # العملات المحظورة
    if sym in BLACKLIST:
        if BLACKLIST[sym].get("time"):
            if (datetime.now(timezone.utc) - BLACKLIST[sym]["time"]).seconds < BLACKLIST_DURATION * 3600:
                return None
            else:
                del BLACKLIST[sym]   # انتهت مدة الحظر
        else:
            return None

    h4=get_klines(sym,"4h",200)
    d1=get_klines(sym,"1d",101)
    if len(h4)<100 or len(d1)<52: return None

    d1_closed = d1[:-1]
    d1_cl=[c["close"] for c in d1_closed[-60:]]
    d1_e50=ema(d1_cl,50)
    if d1_e50<=0: return None
    trend="Bull" if d1_closed[-1]["close"]>d1_e50 else "Bear"

    win=h4[-100:]
    cl=[c["close"] for c in win]
    hi=[c["high"] for c in win]
    lo=[c["low"] for c in win]
    vl=[c["volume"] for c in win]

    e20=ema(cl,20); e50=ema(cl,50)
    a=atr_calc(hi,lo,cl)
    rs=rsi_calc(cl)
    adxv=adx_calc(hi,lo,cl)
    avg_vol=sum(vl[-20:])/20

    if e20<=0 or e50<=0 or a<=0: return None
    if (a/cl[-1]*100)<MIN_ATR_PCT: return None

    signal = win[-2]
    if signal["volume"] < avg_vol * VOL_MULT: return None
    if rs<=30 or rs>=70: return None
    if adxv<ADX_MIN: return None

    curr=win[-1]
    direction=None

    if trend=="Bull":
        if (signal["close"]>e50 and signal["close"]>e20
            and signal["low"]<=e20
            and signal["close"]>signal["open"]):
            direction="Long"
    elif trend=="Bear":
        if (signal["close"]<e50 and signal["close"]<e20
            and signal["high"]>=e20
            and signal["close"]<signal["open"]):
            direction="Short"

    if not direction: return None

    entry=curr["open"]
    if direction=="Long": entry=round(entry*(1+SLIPPAGE),6)
    else: entry=round(entry*(1-SLIPPAGE),6)

    stop  =round(entry-a*STOP_MULT,6) if direction=="Long" else round(entry+a*STOP_MULT,6)
    target=round(entry+a*TGT_MULT,6) if direction=="Long" else round(entry-a*TGT_MULT,6)

    return {"dir":direction,"stop":stop,"target":target,"entry":entry,
            "atr":a,"rsi":rs,"adx":adxv,"trend":trend,"e20":e20,"e50":e50}

def send_report(cycle):
    now=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    wr=(TOTAL_WINS/TOTAL_TRADES*100) if TOTAL_TRADES>0 else 0.0
    lines=[
        f"📊 <b>تقرير #{cycle}</b> | {now}",
        "━━━━━━━━━━━━━━━━━",
        f"💰 الرصيد: <b>{usdt:.2f}$</b>",
        f"📈 الأرباح: <b>{TOTAL_PNL:+.2f}$ ({TOTAL_PNL/CAPITAL*100:+.1f}%)</b>",
        f"📋 الصفقات: {TOTAL_TRADES} | ✅ {TOTAL_WINS} | ❌ {TOTAL_LOSSES}",
        f"🎯 نسبة الربح: {wr:.1f}%",
        f"📂 مفتوحة: {len(positions)}/{MAX_OPEN}"
    ]
    if BLACKLIST:
        lines.append("🚫 محظورة: " + ", ".join(BLACKLIST.keys()))
    if positions:
        lines+=["━━━━━━━━━━━━━━━━━","📌 <b>الصفقات المفتوحة:</b>"]
        for p in positions:
            cur=get_price(p["sym"])
            if cur>0:
                unr=(cur-p["entry"])*p["qty"] if p["dir"]=="Long" else (p["entry"]-cur)*p["qty"]
                fee=p["entry"]*p["qty"]*COMMISSION
                net_unr=unr-fee; pct=net_unr/p["amount"]*100
                icon="🟢" if net_unr>=0 else "🔴"
                lines.append(
                    f"{icon} {p['dir']} {p['sym']}\n"
                    f"   دخول: {p['entry']:.4f} | الآن: {cur:.4f}\n"
                    f"   P&L: {net_unr:+.2f}$ ({pct:+.1f}%)\n"
                    f"   وقف: {p['stop']:.4f} | هدف: {p['target']:.4f}"
                )
    tg("\n".join(lines))

tg(
    f"🤖 <b>بوت V18+ADX - فلترة ذكية</b>\n"
    f"━━━━━━━━━━━━━━━━━\n"
    f"💰 رأس المال: {CAPITAL:.2f}$\n"
    f"⚙️ RSI 30-70 | VOL 1.2x | ADX≥22\n"
    f"🛡️ حظر بعد {MAX_CONSECUTIVE_LOSSES} خسائر متتالية\n"
    f"📊 {len(SYMBOLS)} عملة | فريم 4H + يومي\n"
    f"🔄 يفحص كل 15 دقيقة"
)

cycle=0
while True:
    try:
        cycle+=1
        for pos in list(positions):
            price=get_price(pos["sym"])
            if price<=0: continue
            hit=None; reason=""
            if pos["dir"]=="Long":
                if price<=pos["stop"]: hit=pos["stop"]; reason="وقف الخسارة"
                elif price>=pos["target"]: hit=pos["target"]; reason="هدف الربح"
            else:
                if price>=pos["stop"]: hit=pos["stop"]; reason="وقف الخسارة"
                elif price<=pos["target"]: hit=pos["target"]; reason="هدف الربح"
            if hit:
                pnl=(hit-pos["entry"])*pos["qty"] if pos["dir"]=="Long" else (pos["entry"]-hit)*pos["qty"]
                fee=(pos["entry"]+hit)*pos["qty"]*COMMISSION
                net=pnl-fee
                usdt+=pos["amount"]+net; TOTAL_PNL+=net; TOTAL_TRADES+=1
                if net>0:
                    TOTAL_WINS+=1
                    # إعادة تعيين عداد الخسائر المتتالية للعملة
                    if pos["sym"] in BLACKLIST:
                        del BLACKLIST[pos["sym"]]
                else:
                    TOTAL_LOSSES+=1
                    # زيادة عداد الخسائر المتتالية
                    BLACKLIST[pos["sym"]] = BLACKLIST.get(pos["sym"], {"count": 0, "time": datetime.now(timezone.utc)})
                    BLACKLIST[pos["sym"]]["count"] = BLACKLIST[pos["sym"]].get("count", 0) + 1
                    if BLACKLIST[pos["sym"]]["count"] >= MAX_CONSECUTIVE_LOSSES:
                        BLACKLIST[pos["sym"]]["time"] = datetime.now(timezone.utc)
                        tg(f"🚫 <b>حظر {pos['sym']}</b> - {MAX_CONSECUTIVE_LOSSES} خسائر متتالية")
                positions.remove(pos)
                icon="✅" if net>0 else "❌"
                tg(
                    f"{icon} <b>{'ربح' if net>0 else 'خسارة'} | {pos['dir']} {pos['sym']}</b>\n"
                    f"السبب: {reason}\n"
                    f"📍 دخول: {pos['entry']:.4f} | خروج: {hit:.4f}\n"
                    f"💰 P&L: <b>{net:+.2f}$</b>\n"
                    f"💼 الرصيد: {usdt:.2f}$"
                )
        if len(positions)<MAX_OPEN:
            open_syms=[p["sym"] for p in positions]
            for sym in SYMBOLS:
                if len(positions)>=MAX_OPEN: break
                if sym in open_syms: continue
                sig=analyze(sym)
                if not sig: continue
                entry=sig["entry"]
                dist=abs(entry-sig["stop"])
                if dist<=0: continue
                amount=round(usdt*RISK_PCT/100,2)
                qty=round(amount/dist,6)
                if qty*entry<10: continue
                positions.append({
                    "sym":sym,"dir":sig["dir"],"entry":entry,
                    "stop":sig["stop"],"target":sig["target"],
                    "qty":qty,"amount":amount,
                    "time":datetime.now(timezone.utc).strftime("%H:%M")
                })
                usdt-=amount
                rr=round(abs(sig["target"]-entry)/dist,1)
                tg(
                    f"🔔 <b>إشارة V18+ADX!</b>\n"
                    f"{'🟢 Long' if sig['dir']=='Long' else '🔴 Short'} <b>{sym}</b>\n"
                    f"━━━━━━━━━━━━━━━━━\n"
                    f"📍 سعر: <b>{entry:.4f} $</b>\n"
                    f"🛑 وقف: <b>{sig['stop']:.4f} $</b> ({abs(entry-sig['stop'])/entry*100:.2f}%)\n"
                    f"🎯 هدف: <b>{sig['target']:.4f} $</b> ({abs(sig['target']-entry)/entry*100:.2f}%)\n"
                    f"⚖️ R:R = 1:{rr}\n"
                    f"📊 RSI: {sig['rsi']:.1f} | ADX: {sig['adx']:.1f}\n"
                    f"📈 اتجاه: {sig['trend']}\n"
                    f"💵 مبلغ: {amount:.2f}$ | كمية: {qty:.6f}\n"
                    f"⏰ {datetime.now(timezone.utc).strftime('%H:%M')} UTC"
                )
                time.sleep(2)
        send_report(cycle)
    except Exception as e:
        tg(f"⚠️ خطأ: {str(e)[:200]}")
    time.sleep(900)
