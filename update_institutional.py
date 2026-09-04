from __future__ import annotations
import json, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
STOCKS_FILE = ROOT / "data" / "stocks.json"
OUT_FILE = ROOT / "data" / "institutional.json"
JS_FILE = ROOT / "data" / "institutional.js"
HISTORY_FILE = ROOT / "data" / "institutional_history.json"

TZ8 = timezone(timedelta(hours=8))
HEADERS = {"User-Agent": "Mozilla/5.0 stock-industry-dashboard/1.0"}

def n(v):
    if v is None: return 0
    if isinstance(v, (int,float)): return int(v)
    s = str(v).replace(",", "").replace(" ", "").strip()
    if s in ("","--","---"): return 0
    try: return int(float(s))
    except: return 0

def fetch_twse(date_yyyymmdd: str):
    url = "https://www.twse.com.tw/rwd/zh/fund/T86"
    params = {"date": date_yyyymmdd, "selectType": "ALLBUT0999", "response": "json"}
    r = requests.get(url, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    j = r.json()
    rows = j.get("data") or []
    fields = j.get("fields") or []
    if not rows: return {}
    def idx(keyword):
        for i, f in enumerate(fields):
            if keyword in str(f): return i
        return None
    i_code = idx("證券代號"); i_name = idx("證券名稱")
    i_buy = idx("投信買進股數"); i_sell = idx("投信賣出股數"); i_net = idx("投信買賣超股數")
    out={}
    for row in rows:
        code=str(row[i_code]).strip()
        buy=n(row[i_buy]) if i_buy is not None else 0
        sell=n(row[i_sell]) if i_sell is not None else 0
        net=n(row[i_net]) if i_net is not None else buy-sell
        out[code]={"name":str(row[i_name]).strip(),"buy":buy,"sell":sell,"net":net,"market":"TWSE"}
    return out

def fetch_tpex_latest():
    # TPEx official OpenAPI: latest trading day's institutional detail.
    url = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    rows = r.json()
    if not isinstance(rows, list): return {}
    out={}
    for row in rows:
        # Field labels can change slightly, so locate by content rather than one hard-coded schema.
        def pick(*needles):
            for k,v in row.items():
                ks=str(k).replace("\n","").replace(" ","")
                if all(x in ks for x in needles): return v
            return None
        code = pick("代號") or pick("證券代號") or row.get("SecuritiesCompanyCode")
        name = pick("名稱") or pick("證券名稱") or row.get("CompanyName")
        if not code: continue
        buy = pick("投信","買進") or pick("投信","買股") or pick("投信","買")
        sell = pick("投信","賣出") or pick("投信","賣股") or pick("投信","賣")
        net = pick("投信","買賣超") or pick("投信","淨買")
        buy_i, sell_i = n(buy), n(sell)
        net_i = n(net) if net is not None else buy_i-sell_i
        out[str(code).strip()]={"name":str(name or "").strip(),"buy":buy_i,"sell":sell_i,"net":net_i,"market":"TPEx"}
    return out

def load_json(path, default):
    try: return json.loads(path.read_text(encoding="utf-8"))
    except: return default

def main():
    tracked = {x["code"]: x for x in json.loads(STOCKS_FILE.read_text(encoding="utf-8"))}
    now = datetime.now(TZ8)
    today = now.strftime("%Y%m%d")

    # TWSE endpoint accepts a requested date; if today is holiday / data not ready,
    # walk back up to 10 calendar days to find the latest trading day.
    twse, twse_date = {}, None
    for back in range(10):
        d = (now - timedelta(days=back)).strftime("%Y%m%d")
        try:
            got = fetch_twse(d)
            if got:
                twse, twse_date = got, d
                break
        except Exception as e:
            print("TWSE", d, e)
        time.sleep(0.25)

    tpex={}
    try:
        tpex=fetch_tpex_latest()
    except Exception as e:
        print("TPEx error:", e)

    combined = dict(twse)
    combined.update(tpex)
    if not combined:
        raise SystemExit("No institutional data fetched; keep previous JSON unchanged.")

    # Use TWSE date when available. TPEx OpenAPI is latest-day data; under normal post-close runs they match.
    as_of = f"{twse_date[:4]}-{twse_date[4:6]}-{twse_date[6:]}" if twse_date else now.strftime("%Y-%m-%d")

    hist = load_json(HISTORY_FILE, {"days":{}})
    days = hist.setdefault("days", {})
    day_map={}
    for code in tracked:
        if code in combined:
            row=combined[code]
            day_map[code]={"net_shares":row["net"],"buy_shares":row["buy"],"sell_shares":row["sell"],"market":row["market"]}
    days[as_of]=day_map

    # Keep newest 80 calendar entries.
    for old in sorted(days)[:-80]:
        del days[old]
    HISTORY_FILE.write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")

    trading_days=sorted(days.keys(), reverse=True)
    result={}
    for code, meta in tracked.items():
        series=[]
        for d in trading_days:
            if code in days[d]:
                series.append((d, days[d][code]["net_shares"]))
        if not series:
            continue
        latest_day, d1 = series[0]
        d5=sum(v for _,v in series[:5])
        d20=sum(v for _,v in series[:20])
        # shares -> lots (張), conventional 1 lot = 1000 shares for common stock.
        def lots(x): return round(x/1000, 1)
        consec_buy=0; consec_sell=0
        for _,v in series:
            if v>0 and consec_sell==0: consec_buy+=1
            elif v<0 and consec_buy==0: consec_sell+=1
            else: break
        result[code]={
            "name":meta["name"], "industry":meta["industry"], "date":latest_day,
            "d1":lots(d1), "d5":lots(d5), "d20":lots(d20),
            "d1_shares":d1, "d5_shares":sum(v for _,v in series[:5]), "d20_shares":sum(v for _,v in series[:20]),
            "days_available":len(series),
            "consecutive_buy_days":consec_buy, "consecutive_sell_days":consec_sell
        }

    out={
        "as_of": as_of,
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S +08:00"),
        "note":"5日/20日數據由本站每日累積；剛部署時會先從 1 日資料開始累積。",
        "stocks": result
    }
    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    JS_FILE.write_text("window.INSTITUTIONAL_DATA = " + json.dumps(out, ensure_ascii=False, indent=2) + ";\n", encoding="utf-8")
    print("Updated", OUT_FILE, "and", JS_FILE, "stocks:", len(result), "as_of:", as_of)

if __name__ == "__main__":
    main()
