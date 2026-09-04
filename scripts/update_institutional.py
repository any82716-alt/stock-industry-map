from __future__ import annotations
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
STOCKS_FILE = ROOT / 'data' / 'stocks.json'
OUT_FILE = ROOT / 'data' / 'institutional.json'
JS_FILE = ROOT / 'data' / 'institutional.js'
HISTORY_FILE = ROOT / 'data' / 'institutional_history.json'

TZ8 = timezone(timedelta(hours=8))
HEADERS = {
    'User-Agent': 'Mozilla/5.0 stock-industry-dashboard/2.0',
    'Accept': 'application/json,text/plain,*/*',
}
LOOKBACK_CALENDAR_DAYS = 45
TARGET_TRADING_DAYS = 20


def n(v):
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).replace(',', '').replace(' ', '').strip()
    if s in ('', '--', '---', 'N/A', 'null'):
        return 0
    try:
        return int(float(s))
    except Exception:
        return 0


def fetch_twse(date_yyyymmdd: str) -> dict:
    url = 'https://www.twse.com.tw/rwd/zh/fund/T86'
    params = {'date': date_yyyymmdd, 'selectType': 'ALLBUT0999', 'response': 'json'}
    r = requests.get(url, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    j = r.json()
    rows = j.get('data') or []
    fields = j.get('fields') or []
    if not rows:
        return {}

    def idx(keyword):
        for i, f in enumerate(fields):
            if keyword in str(f):
                return i
        return None

    i_code = idx('證券代號')
    i_name = idx('證券名稱')
    i_buy = idx('投信買進股數')
    i_sell = idx('投信賣出股數')
    i_net = idx('投信買賣超股數')
    if i_code is None or i_name is None or i_net is None:
        raise RuntimeError(f'TWSE 欄位格式改變：{fields}')

    out = {}
    for row in rows:
        code = str(row[i_code]).strip()
        buy = n(row[i_buy]) if i_buy is not None else 0
        sell = n(row[i_sell]) if i_sell is not None else 0
        net = n(row[i_net])
        out[code] = {'name': str(row[i_name]).strip(), 'buy': buy, 'sell': sell, 'net': net, 'market': 'TWSE'}
    return out


def roc_date(dt):
    return f'{dt.year - 1911:03d}/{dt.month:02d}/{dt.day:02d}'


def parse_tpex_payload(payload) -> dict:
    rows = []
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        for key in ('aaData', 'data'):
            v = payload.get(key)
            if isinstance(v, list):
                rows.extend(v)
        tables = payload.get('tables')
        if isinstance(tables, list):
            for table in tables:
                if isinstance(table, dict):
                    v = table.get('data') or table.get('aaData')
                    if isinstance(v, list):
                        rows.extend(v)

    out = {}
    for row in rows:
        if not isinstance(row, dict):
            continue

        def pick(*needles):
            for k, v in row.items():
                ks = str(k).replace('\n', '').replace(' ', '')
                if all(x in ks for x in needles):
                    return v
            return None

        code = pick('證券代號') or pick('代號') or row.get('SecuritiesCompanyCode') or row.get('Code')
        if not code:
            continue
        name = pick('證券名稱') or pick('名稱') or row.get('CompanyName') or row.get('Name')
        buy = pick('投信', '買') or row.get('InvestmentTrustBuy')
        sell = pick('投信', '賣') or row.get('InvestmentTrustSell')
        net = pick('投信', '買賣超') or pick('投信', '淨買') or row.get('InvestmentTrustNet')
        buy_i, sell_i = n(buy), n(sell)
        net_i = n(net) if net is not None else buy_i - sell_i
        out[str(code).strip()] = {'name': str(name or '').strip(), 'buy': buy_i, 'sell': sell_i, 'net': net_i, 'market': 'TPEx'}
    return out


def fetch_tpex_by_date(dt) -> dict:
    candidates = [
        ('https://www.tpex.org.tw/www/zh-tw/insti/daily', {'date': dt.strftime('%Y/%m/%d'), 'id': '', 'response': 'json'}),
        ('https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php', {'l': 'zh-tw', 'd': roc_date(dt), 'se': 'EW', 't': 'D'}),
    ]
    for url, params in candidates:
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=30)
            if not r.ok:
                continue
            if 'json' in (r.headers.get('content-type') or '').lower() or r.text.lstrip().startswith(('{', '[')):
                parsed = parse_tpex_payload(r.json())
                if parsed:
                    return parsed
        except Exception:
            pass
    return {}


def fetch_tpex_latest() -> dict:
    url = 'https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading'
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return parse_tpex_payload(r.json())


def lots(shares):
    return round(shares / 1000, 1)


def main():
    tracked_list = json.loads(STOCKS_FILE.read_text(encoding='utf-8'))
    tracked = {x['code']: x for x in tracked_list}
    now = datetime.now(TZ8)

    days = {}
    found_twse_days = 0
    found_tpex_days = 0
    latest_valid_date = None

    print('Backfilling the latest 20 trading days...')

    for back in range(LOOKBACK_CALENDAR_DAYS):
        dt = now - timedelta(days=back)
        if dt.weekday() >= 5:
            continue

        date_key = dt.strftime('%Y-%m-%d')
        ymd = dt.strftime('%Y%m%d')
        twse, tpex = {}, {}

        if found_twse_days < TARGET_TRADING_DAYS:
            try:
                twse = fetch_twse(ymd)
                if twse:
                    found_twse_days += 1
            except Exception as e:
                print('TWSE', date_key, 'error:', e)

        if found_tpex_days < TARGET_TRADING_DAYS:
            try:
                tpex = fetch_tpex_by_date(dt)
                if tpex:
                    found_tpex_days += 1
            except Exception as e:
                print('TPEx', date_key, 'error:', e)

        combined = dict(twse)
        combined.update(tpex)
        day_map = {}
        for code in tracked:
            if code in combined:
                row = combined[code]
                day_map[code] = {
                    'net_shares': row['net'],
                    'buy_shares': row['buy'],
                    'sell_shares': row['sell'],
                    'market': row['market'],
                }

        if day_map:
            days[date_key] = day_map
            if latest_valid_date is None:
                latest_valid_date = date_key

        print(date_key, f'TWSE={"OK" if twse else "-"}', f'TPEx={"OK" if tpex else "-"}', f'tracked={len(day_map)}')

        if found_twse_days >= TARGET_TRADING_DAYS and found_tpex_days >= TARGET_TRADING_DAYS:
            break
        time.sleep(0.15)

    # TPEx fallback for current day only, if historical endpoint is unavailable.
    if found_tpex_days == 0:
        try:
            latest_tpex = fetch_tpex_latest()
            if latest_tpex:
                key = latest_valid_date or now.strftime('%Y-%m-%d')
                days.setdefault(key, {})
                for code in tracked:
                    if code in latest_tpex:
                        row = latest_tpex[code]
                        days[key][code] = {
                            'net_shares': row['net'], 'buy_shares': row['buy'], 'sell_shares': row['sell'], 'market': 'TPEx'
                        }
                print('TPEx historical endpoint unavailable; latest OpenAPI fallback used.')
        except Exception as e:
            print('TPEx latest fallback error:', e)

    if not days:
        raise SystemExit('No institutional data fetched; previous files are left unchanged.')

    HISTORY_FILE.write_text(json.dumps({'days': days}, ensure_ascii=False, indent=2), encoding='utf-8')
    trading_days = sorted(days.keys(), reverse=True)
    as_of = trading_days[0]
    result = {}

    for code, meta in tracked.items():
        series = [(d, days[d][code]['net_shares']) for d in trading_days if code in days[d]]
        if not series:
            continue

        latest_day, d1_shares = series[0]
        last5 = series[:5]
        last20 = series[:20]
        d5_shares = sum(v for _, v in last5)
        d20_shares = sum(v for _, v in last20)

        consecutive_buy = 0
        consecutive_sell = 0
        for _, v in series:
            if v > 0 and consecutive_sell == 0:
                consecutive_buy += 1
            elif v < 0 and consecutive_buy == 0:
                consecutive_sell += 1
            else:
                break

        result[code] = {
            'name': meta['name'],
            'industry': meta['industry'],
            'date': latest_day,
            'd1': lots(d1_shares),
            'd5': lots(d5_shares) if len(last5) == 5 else None,
            'd20': lots(d20_shares) if len(last20) == 20 else None,
            'd1_shares': d1_shares,
            'd5_shares': d5_shares if len(last5) == 5 else None,
            'd20_shares': d20_shares if len(last20) == 20 else None,
            'd5_days': len(last5),
            'd20_days': len(last20),
            'days_available': len(series),
            'consecutive_buy_days': consecutive_buy,
            'consecutive_sell_days': consecutive_sell,
        }

    out = {
        'as_of': as_of,
        'generated_at': now.strftime('%Y-%m-%d %H:%M:%S +08:00'),
        'note': '今日=最新交易日；近5日/20日=由最新交易日往前加總最近5/20個實際交易日，休市日自動略過。',
        'stocks': result,
    }

    OUT_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    JS_FILE.write_text('window.INSTITUTIONAL_DATA = ' + json.dumps(out, ensure_ascii=False, indent=2) + ';\n', encoding='utf-8')

    print('Updated:', as_of, 'stocks:', len(result), 'TWSE trading days:', found_twse_days, 'TPEx trading days:', found_tpex_days)


if __name__ == '__main__':
    main()
