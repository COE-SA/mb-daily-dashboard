#!/usr/bin/env python3
"""
بوصلة التميز التجارية - السكريبت اليومي للسحب من Odoo
يستخدم /jsonrpc endpoint (متوافق مع Odoo Online + API Keys)
"""
import os
import json
import sys
from datetime import datetime, timedelta, timezone
import requests

# ─── الإعدادات (من GitHub Secrets) ─────────────────────────────────────
ODOO_URL = os.environ['ODOO_URL']
ODOO_DB = os.environ['ODOO_DB']
ODOO_USER = os.environ['ODOO_USER']
ODOO_API_KEY = os.environ['ODOO_API_KEY']
OUTPUT_FILE = os.environ.get('OUTPUT_FILE', 'data.json')

BRANCH_MAP = {
    4: 'الحمدانية', 5: 'مروى', 6: 'الأجاويد',
    7: 'المدينة',   8: 'الوزيرية', 9: 'الصفا'
}

# ─── JSON-RPC client (يستخدم /jsonrpc - يدعم API Keys في Odoo Online) ──
JSONRPC_URL = f'{ODOO_URL.rstrip("/")}/jsonrpc'

def jsonrpc(service, method, args):
    """استدعاء JSON-RPC"""
    r = requests.post(
        JSONRPC_URL,
        json={
            'jsonrpc': '2.0',
            'method': 'call',
            'params': {'service': service, 'method': method, 'args': args}
        },
        timeout=30
    )
    data = r.json()
    if 'error' in data:
        raise Exception(f"Odoo error: {data['error']}")
    return data.get('result')

def authenticate():
    """تسجيل دخول للحصول على UID"""
    uid = jsonrpc('common', 'authenticate', [ODOO_DB, ODOO_USER, ODOO_API_KEY, {}])
    if not uid:
        raise Exception("فشل تسجيل الدخول - تحقق من البيانات")
    return uid

def execute(uid, model, method, args, kwargs=None):
    """استدعاء model method"""
    kwargs = kwargs or {}
    return jsonrpc('object', 'execute_kw', [
        ODOO_DB, uid, ODOO_API_KEY, model, method, args, kwargs
    ])

def get_sales(uid, start_date, end_date, config_id=None):
    """جلب إجمالي المبيعات لفترة"""
    domain = [
        ['date_order', '>=', f'{start_date} 00:00:00'],
        ['date_order', '<=', f'{end_date} 23:59:59'],
        ['state', 'in', ['done', 'invoiced', 'paid']]
    ]
    if config_id:
        domain.append(['config_id', '=', config_id])
    result = execute(uid, 'pos.order', 'read_group',
        [domain],
        {'fields': ['amount_total:sum', 'id:count'], 'groupby': [], 'limit': 1})
    if result and len(result) > 0:
        row = result[0]
        return {
            'revenue': round(row.get('amount_total') or 0),
            'orders': row.get('id') or row.get('__count') or 0
        }
    return {'revenue': 0, 'orders': 0}

def get_top_products(uid, start_date, end_date, limit=5):
    """أفضل المنتجات لفترة"""
    result = execute(uid, 'pos.order.line', 'read_group',
        [[['order_id.date_order', '>=', f'{start_date} 00:00:00'],
          ['order_id.date_order', '<=', f'{end_date} 23:59:59'],
          ['order_id.state', 'in', ['done', 'invoiced', 'paid']],
          ['price_subtotal_incl', '>', 0]]],
        {'fields': ['product_id', 'qty:sum', 'price_subtotal_incl:sum'],
         'groupby': ['product_id'],
         'orderby': 'price_subtotal_incl desc',
         'limit': limit})
    return [{
        'product': (p.get('product_id', [None, ''])[1] or '').split(']')[-1].strip()[:40],
        'qty': round(p.get('qty') or 0),
        'revenue': round(p.get('price_subtotal_incl') or 0)
    } for p in (result or [])]

def calculate_change(new, old):
    if old == 0:
        return 0
    return round((new - old) / old * 1000) / 10

def fmt(d):
    return d.strftime('%Y-%m-%d')

def main():
    print(f"🚀 بدء السحب: {datetime.now()}")
    print(f"🔗 الموقع: {ODOO_URL}")
    print(f"💾 قاعدة البيانات: {ODOO_DB}")
    print(f"👤 المستخدم: {ODOO_USER}")
    
    uid = authenticate()
    print(f"✅ تم تسجيل الدخول (UID: {uid})")
    
    # المرجع الزمني (Saudi time = UTC+3)
    saudi_tz = timezone(timedelta(hours=3))
    today = datetime.now(saudi_tz)
    yesterday = today - timedelta(days=1)
    day_before = today - timedelta(days=2)
    week_start = today - timedelta(days=7)
    week_end = today - timedelta(days=1)
    prev_month_start = week_start - timedelta(days=28)
    prev_month_end = week_end - timedelta(days=28)
    
    print(f"📅 أمس: {fmt(yesterday)}")
    print(f"📊 الأسبوع: {fmt(week_start)} → {fmt(week_end)}")
    
    yesterday_total = get_sales(uid, fmt(yesterday), fmt(yesterday))
    day_before_total = get_sales(uid, fmt(day_before), fmt(day_before))
    week_total = get_sales(uid, fmt(week_start), fmt(week_end))
    prev_month_total = get_sales(uid, fmt(prev_month_start), fmt(prev_month_end))
    
    branches = {}
    for bid, bname in BRANCH_MAP.items():
        y = get_sales(uid, fmt(yesterday), fmt(yesterday), bid)
        db = get_sales(uid, fmt(day_before), fmt(day_before), bid)
        w = get_sales(uid, fmt(week_start), fmt(week_end), bid)
        pm = get_sales(uid, fmt(prev_month_start), fmt(prev_month_end), bid)
        branches[bname] = {
            'yesterday': y, 'day_before': db,
            'week': w, 'prev_month_week': pm,
            'change_dod': calculate_change(y['revenue'], db['revenue']),
            'change_wow': calculate_change(w['revenue'], pm['revenue']),
        }
    
    top_products = get_top_products(uid, fmt(yesterday), fmt(yesterday))
    
    day_names_ar = ['الإثنين', 'الثلاثاء', 'الأربعاء', 'الخميس', 'الجمعة', 'السبت', 'الأحد']
    last_7_days = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i + 1)
        sales = get_sales(uid, fmt(d), fmt(d))
        last_7_days.append({
            'date': fmt(d), 'revenue': sales['revenue'],
            'orders': sales['orders'], 'day_name': day_names_ar[d.weekday()]
        })
    
    prev_month_7_days = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i + 1 + 28)
        sales = get_sales(uid, fmt(d), fmt(d))
        prev_month_7_days.append({
            'date': fmt(d), 'revenue': sales['revenue'],
            'orders': sales['orders'], 'day_name': day_names_ar[d.weekday()]
        })
    
    dashboard = {
        'last_updated': today.strftime('%Y-%m-%d %H:%M:%S'),
        'periods': {
            'yesterday_date': fmt(yesterday),
            'day_before_date': fmt(day_before),
            'week_range': f'{fmt(week_start)} → {fmt(week_end)}',
            'prev_month_range': f'{fmt(prev_month_start)} → {fmt(prev_month_end)}'
        },
        'totals': {
            'yesterday': yesterday_total,
            'day_before': day_before_total,
            'change_dod_pct': calculate_change(yesterday_total['revenue'], day_before_total['revenue']),
            'week': week_total,
            'prev_month_week': prev_month_total,
            'change_wow_pct': calculate_change(week_total['revenue'], prev_month_total['revenue']),
        },
        'branches': branches,
        'top_products_yesterday': top_products,
        'last_7_days': last_7_days,
        'prev_month_7_days': prev_month_7_days,
    }
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(dashboard, f, ensure_ascii=False, indent=2)
    
    print(f"\n📊 ملخص:")
    print(f"   أمس:           {yesterday_total['revenue']:>10,} ﷼  ({yesterday_total['orders']} طلب)")
    print(f"   أول أمس:       {day_before_total['revenue']:>10,} ﷼")
    print(f"   التغير اليومي: {dashboard['totals']['change_dod_pct']:+.1f}%")
    print(f"   الأسبوع:       {week_total['revenue']:>10,} ﷼")
    print(f"   التغير الأسبوعي: {dashboard['totals']['change_wow_pct']:+.1f}%")
    print(f"\n✅ حُفظت البيانات في: {OUTPUT_FILE}")
    return 0

if __name__ == '__main__':
    sys.exit(main())
