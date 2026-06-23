
import os, time, requests, threading
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler

TG_TOKEN = "8887593469:AAFKDCeleWxHuBC4p6q-vJQMTJ5V1ff0Lts"
TG_CHAT  = "5230956729"
SYMBOLS = ["BTCUSDT","ETHUSDT","SOLUSDT","ADAUSDT","BNBUSDT","XRPUSDT","LTCUSDT","DOGEUSDT","DOTUSDT","AVAXUSDT","LINKUSDT","UNIUSDT","ATOMUSDT","TRXUSDT","NEARUSDT"]
CAPITAL=10000.0; RISK_PCT=1.0; STOP_MULT=1.5; TGT_MULT=3.0; MIN_ATR_PCT=0.15; MAX_OPEN=4; VOL_MULT=1.5; ADX_MIN=22
usdt=CAPITAL; positions=[]; TOTAL_TRADES=0; TOTAL_WINS=0; TOTAL_LOSSES=0; TOTAL_PNL=0.0

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    def log_message(self,*a): pass
threading.Thread(target=lambda:HTTPServer(("0.0.0.0",int(os.environ.get("PORT",8000))),H).serve_forever(),daemon=True).start()

def tg(msg):
    for _ in range(3):
        try:
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",data={"chat_id":TG_CHAT,"text":msg,"parse_mode":"HTML"},timeout=15); return
        except: time.sleep(3)

def get_klines(sym,interval,limit=200):
    for _ in range(3):
        try:
            r=requests.get(f"https://api.binance.com/api/v3/klines?symbol={sym}&interval={interval}&limit={limit}",timeout=15)
            if r.status_code==200: return [{"open":float(k[1]),"high":float(k[2]),"low":float(k[3]),"close":float(k[4]),"volume":float(k[5])} for k in r.json()]
        except: pass
        time.sleep(2)
    return []

def get_price(sym):
    for _ in range(3):
        try:
            r=requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={sym}",timeout=10)
            if r.status_code==200:
                p=float(r.json()["price"])
                if p>0: return p
        except: pass
        time.sleep(2)
    return 0.0

def ema(series,period):
    if len(series)<period: return 0.0
    k=2.0/(period+1); val=sum(series[:period])/period
    for p in series[period:]: val=(p-val)*k+val
    return val

def atr(highs,lows,closes,period=14):
    if len(highs)<period: return 0.0
    trs=[max(highs[i]-lows[i],abs(highs[i]-closes[i-1]),abs(lows[i]-closes[i-1])) for i in range(1,len(highs))]
    val=sum(trs[:period])/period
    for tr in trs[period:]: val=(val*(period-1)+tr)/period
    return val

def rsi(closes,period=14):
    if len(closes)<period+1: return 50.0
    gains=losses=0.0
    for i in range(1,period+1):
        d=closes[i]-closes[i-1]
        if d>0: gains+=d
        else: losses-=d
    ag,al=gains/period,losses/period
    for i in range(period+1,len(closes)):
        d=closes[i]-closes[i-1]
        ag=(ag*(period-1)+(d if d>0 else 0.0))/period
        al=(al*(period-1)+(-d if d<0 else 0.0))/period
    return 100.0 if al==0 else 100.0-100.0/(1+ag/al)

def adx(highs,lows,closes,period=14):
    n=len(highs)
    if n<period*2: return 0.0
    trs,pdms,mdms=[],[],[]
    for i in range(1,n):
        trs.append(max(highs[i]-lows[i],abs(highs[i]-closes[i-1]),abs(lows[i]-closes[i-1])))
        up,dn=highs[i]-highs[i-1],lows[i-1]-lows[i]
        pdms.append(up if up>dn and up>0 else 0.0)
        mdms.append(dn if dn>up and dn>0 else 0.0)
    av=sum(trs[:period])/period; pv=sum(pdms[:period])/period; mv=sum(mdms[:period])/period
    for i in range(period,len(trs)):
        av=(av*(period-1)+trs[i])/period; pv=(pv*(period-1)+pdms[i])/period; mv=(mv*(period-1)+mdms[i])/period
    if av==0: return 0.0
    pdi,mdi=100*pv/av,100*mv/av; d=pdi+mdi
    return 100*abs(pdi-mdi)/d if d>0 else 0.0

def analyze(sym):
    h4=get_klines(sym,"4h",200); d1=get_klines(sym,"1d",100)
    if len(h4)<100 or len(d1)<60: return None
    win=h4[-100:]; cl=[c["close"] for c in win]; hi=[c["high"] for c in win]; lo=[c["low"] for c in win]; vl=[c["volume"] for c in win]
    e20,e50=ema(cl,20),ema(cl,50); a=atr(hi,lo,cl); rs=rsi(cl); adxv=adx(hi,lo,cl); avg_vol=sum(vl[-20:])/20
    if e20<=0 or e50<=0 or a<=0: return None
    if (a/cl[-1]*100)<MIN_ATR_PCT: return None
    if win[-1]["volume"]<avg_vol*VOL_MULT: return None
    if rs<=30 or rs>=70: return None
    if adxv<ADX_MIN: return None
    d1_cl=[c["close"] for c in d1[-60:]]; d1_e50=ema(d1_cl,50)
    if d1_e50<=0: return None
    trend="Bull" if d1[-1]["close"]>d1_e50 else "Bear"
    c,prev=win[-1],win[-2]; direction=None
    if trend=="Bull" and c["close"]>e50 and c["close"]>e20 and prev["low"]<=e20 and c["close"]>c["open"]: direction="Long"
    elif trend=="Bear" and c["close"]<e50 and c["close"]<e20 and prev["high"]>=e20 and c["close"]<c["open"]: direction="Short"
    if not direction: return None
    risk=a*STOP_MULT
    stop=c["close"]-risk if direction=="Long" else c["close"]+risk
    target=c["close"]+a*TGT_MULT if direction=="Long" else c["close"]-a*TGT_MULT
    return {"dir":direction,"stop":stop,"target":target,"entry":c["close"],"atr":a,"rsi":rs,"adx":adxv,"trend":trend,"e20":e20,"e50":e50}

def open_demo_trades():
    global usdt
    tg("🚀 <b>فتح 3 صفقات تجريبية بأسعار السوق الحقيقية...</b>")
    demos=[("BTCUSDT","Long"),("ETHUSDT","Long"),("SOLUSDT","Short")]
    for sym,dir_ in demos:
        price=get_price(sym)
        if price<=0: continue
        a_val=price*0.015
        stop=round(price-a_val*STOP_MULT,4) if dir_=="Long" else round(price+a_val*STOP_MULT,4)
        target=round(price+a_val*TGT_MULT,4) if dir_=="Long" else round(price-a_val*TGT_MULT,4)
        dist=abs(price-stop)
        amount=usdt*RISK_PCT/100
        qty=round(amount/dist,6)
        positions.append({"sym":sym,"dir":dir_,"entry":price,"stop":stop,"target":target,"qty":qty,"amount":amount,"time":datetime.now(timezone.utc).strftime("%H:%M")})
        usdt-=amount
        rr=abs(target-price)/dist
        tg(f"✅ <b>صفقة تجريبية | {'🟢 Long' if dir_=='Long' else '🔴 Short'} {sym}</b>\n"
           f"━━━━━━━━━━━━━━━━━\n"
           f"📍 دخول: {price:.4f}\n"
           f"🛑 وقف الخسارة: {stop:.4f} ({abs(price-stop)/price*100:.1f}%)\n"
           f"🎯 هدف الربح: {target:.4f} ({abs(target-price)/price*100:.1f}%)\n"
           f"⚖️ نسبة R:R = 1:{rr:.1f}\n"
           f"💵 مبلغ الصفقة: {amount:.2f}$\n"
           f"📊 الكمية: {qty:.6f}")
        time.sleep(2)

def send_report(cycle):
    now=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    wr=(TOTAL_WINS/TOTAL_TRADES*100) if TOTAL_TRADES>0 else 0.0
    lines=[f"📊 <b>تقرير #{cycle}</b> | {now}","━━━━━━━━━━━━━━━━━",
           f"💰 الرصيد: <b>{usdt:.2f}$</b>",
           f"📈 الأرباح: <b>{TOTAL_PNL:+.2f}$ ({TOTAL_PNL/CAPITAL*100:+.1f}%)</b>",
           f"📋 الصفقات: {TOTAL_TRADES} | ✅ {TOTAL_WINS} | ❌ {TOTAL_LOSSES}",
           f"🎯 نسبة الربح: {wr:.1f}%",f"📂 مفتوحة: {len(positions)}/{MAX_OPEN}"]
    if positions:
        lines+=["━━━━━━━━━━━━━━━━━","📌 <b>الصفقات المفتوحة:</b>"]
        for p in positions:
            cur=get_price(p["sym"])
            if cur>0:
                unr=(cur-p["entry"])*p["qty"] if p["dir"]=="Long" else (p["entry"]-cur)*p["qty"]
                fee=p["entry"]*p["qty"]*0.001; net_unr=unr-fee; pct=net_unr/p["amount"]*100
                icon="🟢" if net_unr>=0 else "🔴"
                lines.append(f"{icon} {p['dir']} {p['sym']}\n   دخول: {p['entry']:.4f} → الآن: {cur:.4f}\n   P&L: {net_unr:+.2f}$ ({pct:+.1f}%)\n   وقف: {p['stop']:.4f} | هدف: {p['target']:.4f}")
    tg("\n".join(lines))

tg(f"🤖 <b>بوت محاكاة MizoV3 يعمل الآن</b>\n━━━━━━━━━━━━━━━━━\n💰 رأس المال: {CAPITAL:.2f}$\n⚙️ الاستراتيجية: EMA20/50 + RSI + ADX + ATR\n📊 العملات: {len(SYMBOLS)} عملة\n🔄 يفحص كل 15 دقيقة\n📱 أسعار حقيقية من Binance")
open_demo_trades()
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
                fee=(pos["entry"]+hit)*pos["qty"]*0.001; net=pnl-fee
                usdt+=pos["amount"]+net; TOTAL_PNL+=net; TOTAL_TRADES+=1
                if net>0: TOTAL_WINS+=1
                else: TOTAL_LOSSES+=1
                positions.remove(pos)
                icon="✅" if net>0 else "❌"
                tg(f"{icon} <b>{'ربح' if net>0 else 'خسارة'} | {pos['dir']} {pos['sym']}</b>\nالسبب: {reason}\nدخول: {pos['entry']:.4f} | خروج: {hit:.4f}\nP&L: <b>{net:+.2f}$</b>\nالرصيد: {usdt:.2f}$")
        if len(positions)<MAX_OPEN:
            open_syms=[p["sym"] for p in positions]
            for sym in SYMBOLS:
                if len(positions)>=MAX_OPEN: break
                if sym in open_syms: continue
                sig=analyze(sym)
                if not sig: continue
                entry=get_price(sym)
                if entry<=0: continue
                stop_dist=abs(entry-sig["stop"])
                if stop_dist<=0: continue
                amount=usdt*RISK_PCT/100; qty=amount/stop_dist
                if qty*entry<10: continue
                positions.append({"sym":sym,"dir":sig["dir"],"entry":entry,"stop":sig["stop"],"target":sig["target"],"qty":qty,"amount":amount,"time":datetime.now(timezone.utc).strftime("%H:%M")})
                usdt-=amount
                rr=abs(sig["target"]-entry)/abs(entry-sig["stop"])
                tg(f"🔔 <b>إشارة جديدة!</b>\n{'🟢 Long' if sig['dir']=='Long' else '🔴 Short'} <b>{sym}</b>\n━━━━━━━━━━━━━━━━━\n📍 دخول: {entry:.4f}\n🛑 وقف: {sig['stop']:.4f} ({abs(entry-sig['stop'])/entry*100:.1f}%)\n🎯 هدف: {sig['target']:.4f} ({abs(sig['target']-entry)/entry*100:.1f}%)\n⚖️ نسبة R:R = 1:{rr:.1f}\n📊 RSI: {sig['rsi']:.1f} | ADX: {sig['adx']:.1f}\n📈 اتجاه يومي: {sig['trend']}\n💵 مبلغ الصفقة: {amount:.2f}$")
                time.sleep(2)
        send_report(cycle)
    except Exception as e:
        tg(f"⚠️ خطأ: {str(e)[:200]}")
    time.sleep(900)
