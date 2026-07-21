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

def get_expense_structure(uid, start_date, end_date):
    """يجمع حسابات المصروفات الفعلية من القيود المحاسبية المرحّلة فقط."""
    domain = [
        ['date', '>=', start_date],
        ['date', '<=', end_date],
        ['move_id.state', '=', 'posted'],
        ['account_id.account_type', 'in', ['expense', 'expense_direct_cost']],
    ]
    try:
        grouped = execute(
            uid,
            'account.move.line',
            'read_group',
            [domain],
            {
                'fields': ['debit:sum', 'credit:sum'],
                'groupby': ['account_id'],
                'orderby': 'debit desc',
                'lazy': False,
            },
        ) or []
        account_ids = [row['account_id'][0] for row in grouped if row.get('account_id')]
        accounts = execute(
            uid,
            'account.account',
            'search_read',
            [[['id', 'in', account_ids]]],
            {'fields': ['code', 'name', 'account_type']},
        ) if account_ids else []
        account_map = {row['id']: row for row in accounts}
        rows = []
        for item in grouped:
            if not item.get('account_id'):
                continue
            account_id, fallback_name = item['account_id']
            account = account_map.get(account_id, {})
            amount = round((item.get('debit') or 0) - (item.get('credit') or 0), 2)
            if amount == 0:
                continue
            account_type = account.get('account_type') or 'expense'
            rows.append({
                'id': account_id,
                'code': account.get('code') or '',
                'name': account.get('name') or fallback_name or 'غير محدد',
                'account_type': account_type,
                'classification': 'direct_cost' if account_type == 'expense_direct_cost' else 'operating_expense',
                'amount': amount,
            })
        rows.sort(key=lambda item: abs(item['amount']), reverse=True)
        direct_cost = round(sum(item['amount'] for item in rows if item['classification'] == 'direct_cost'), 2)
        operating_expense = round(sum(item['amount'] for item in rows if item['classification'] == 'operating_expense'), 2)
        return {
            'status': 'ok',
            'start_date': start_date,
            'end_date': end_date,
            'total_expenses': round(direct_cost + operating_expense, 2),
            'direct_cost': direct_cost,
            'operating_expense': operating_expense,
            'accounts': rows,
        }
    except Exception:
        # لا تُعرض رسالة Odoo الخام حتى لا تتسرّب تفاصيل الجلسة إلى سجل GitHub Actions.
        return {'status': 'unavailable', 'reason': 'accounting_read_failed'}


def calculate_change(new, old):
    if old == 0:
        return 0
    return round((new - old) / old * 1000) / 10

def fmt(d):
    return d.strftime('%Y-%m-%d')

def main():
    print(f"🚀 بدء السحب: {datetime.now()}")
    print("🔐 تم تحميل بيانات الاعتماد من أسرار GitHub دون طباعتها في السجل")

    uid = authenticate()
    print("✅ تم تسجيل الدخول بنجاح")
    
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
    year_start = today.replace(month=1, day=1)
    expense_structure = get_expense_structure(uid, fmt(year_start), fmt(yesterday))

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
        'expense_structure_ytd': expense_structure,
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
    if expense_structure.get('status') == 'ok':
        print(f"   مصروفات السنة حتى أمس: {expense_structure['total_expenses']:>10,.2f} ﷼")
        print(f"   عدد حسابات المصروفات: {len(expense_structure['accounts'])}")
    else:
        print("   تفصيل المصروفات: غير متاح لصلاحيات الحسابات الحالية")
    print(f"\n✅ حُفظت البيانات في: {OUTPUT_FILE}")
    return 0

if __name__ == '__main__':
    sys.exit(main())
