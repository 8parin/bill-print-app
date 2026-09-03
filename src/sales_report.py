"""Sales report generation: data assembly, PDF layout, and CSV/XLSX export.

Extracted from app.py's _build_sales_data() and the /sales-report and
/sales-report-export routes. Routes now do: parse request -> assemble
invoice_lookup from session state -> call the functions here -> wrap the
returned bytes in a Flask response.
"""
import re
from io import BytesIO

import pandas as pd

# Default (Shopee) column names used when no platform preset is active, or
# when the active preset has no report_columns override (see
# src/platform_presets.py PlatformPreset.report_columns for the schema).
# This preserves pre-refactor behavior exactly: Lazada/TikTok CSVs simply
# don't contain these columns, so find_col() resolves them to None and the
# corresponding report values become 0/None, same as before this module
# existed.
_DEFAULT_REPORT_COLUMNS = {
    'seller_discount_code': 'โค้ดส่วนลดชำระโดยผู้ขาย',
    'commission': 'ค่าคอมมิชชั่น',
    'transaction_fee': 'Transaction Fee',
    'buyer_paid': 'ราคาสินค้าที่ชำระโดยผู้ซื้อ',
    'net_sale': 'ราคาขายสุทธิ',
    'platform_shipping': 'ค่าจัดส่งที่ Shopee ออกให้โดยประมาณ',
    'seller_disc_other': [
        'โค้ด coins Cashback ชำระโดยผู้ขาย',
        'ส่วนลด bundle deal ชำระโดยผู้ขาย',
        'โบนัสส่วนลดเครื่องเก่าแลกใหม่จากผู้ขาย',
    ],
    'platform_disc_other': [
        'โค้ดส่วนลดชำระโดย Shopee',
        'ส่วนลด bundle deal ชำระโดย Shopee',
        'ส่วนลดจากการใช้เหรียญ',
        'โปรโมชั่นช่องทางชำระเงินทั้งหมด',
        'ส่วนลดเครื่องเก่าแลกใหม่',
        'โบนัสส่วนลดเครื่องเก่าแลกใหม่',
    ],
}


def _format_bill_number(prefix, number):
    """Re-combine prefix + number into a bill number string.

    Mirrors app.py's format_bill_number(); kept as a tiny local copy here
    to avoid a circular import (app.py imports this module).
    """
    return f"{prefix}{number}"


def build_sales_data(df, preset, mapping, invoice_lookup, bill_prefix, starting_bill_number):
    """Build sales report rows from the trimmed dataframe.

    Returns a dict containing report_rows (list of dicts), per-order summary dicts,
    seen_orders (set), total_qty (float), and model_stats (dict).
    """
    order_col = mapping.get('order_id', 'หมายเลขคำสั่งซื้อ')
    product_col = mapping.get('product_name', 'ชื่อสินค้า')
    sale_price_col = mapping.get('sale_price', 'ราคาขาย')
    qty_col = mapping.get('quantity', 'จำนวน')
    estimated_shipping_col = mapping.get('estimated_shipping', 'ค่าจัดส่งโดยประมาณ')
    option_name_col = mapping.get('variant', 'ชื่อตัวเลือก')
    shopee_discount_col = mapping.get('shopee_discount', 'ส่วนลดจาก Shopee')
    recipient_col = mapping.get('recipient_name', 'ชื่อผู้รับ')

    def find_col(name):
        stripped_cols = {c.strip(): c for c in df.columns}
        if name in stripped_cols:
            return stripped_cols[name]
        for col_stripped, col_orig in stripped_cols.items():
            if name in col_stripped:
                return col_orig
        return None

    # Platform-specific report column names, falling back to the Shopee
    # defaults (see src/platform_presets.py PlatformPreset.report_columns).
    rc = (preset.report_columns if preset and preset.report_columns else None) or _DEFAULT_REPORT_COLUMNS

    seller_discount_code_col = find_col(rc['seller_discount_code'])
    commission_col = find_col(rc['commission'])
    transaction_fee_col = find_col(rc['transaction_fee'])
    buyer_paid_col = find_col(rc['buyer_paid'])
    net_sale_col = find_col(rc['net_sale'])
    shopee_shipping_col = find_col(rc['platform_shipping'])

    seller_disc_other_cols = [c for c in (find_col(n) for n in rc['seller_disc_other']) if c]

    shopee_disc_other_cols = [c for c in (find_col(n) for n in rc['platform_disc_other']) if c]

    def extract_model(product_name):
        if pd.isna(product_name):
            return ''
        match = re.search(r'รุ่น\s+(\S+)', str(product_name))
        return match.group(1) if match else ''

    def extract_color(option_name):
        if pd.isna(option_name) or not str(option_name).strip():
            return ''
        parts = str(option_name).split(',', 1)
        return parts[0].strip() if parts else ''

    def extract_size(option_name):
        if pd.isna(option_name) or not str(option_name).strip():
            return ''
        parts = str(option_name).split(',', 1)
        if len(parts) < 2:
            return ''
        size_part = parts[1].strip()
        match = re.match(r'#?(\d+)', size_part)
        return match.group(0) if match else size_part

    def clean_num(val):
        if pd.isna(val) or val == '' or val == '-':
            return 0.0
        if isinstance(val, str):
            val = val.strip().replace(',', '').replace(' ', '')
            if val == '' or val == '-':
                return 0.0
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0

    def safe_col_val(row, col_name):
        if col_name and col_name in row.index:
            return clean_num(row.get(col_name, 0))
        return 0.0

    # Pre-compute per-order sums for multi-row discount columns
    order_seller_disc_main_pre = {}
    order_seller_disc_other_pre = {}
    order_shopee_disc_other_pre = {}
    for oid_val, grp in df.groupby(order_col, sort=False):
        oid_str = str(oid_val)
        if seller_discount_code_col and seller_discount_code_col in df.columns:
            order_seller_disc_main_pre[oid_str] = sum(clean_num(v) for v in grp[seller_discount_code_col])
        else:
            order_seller_disc_main_pre[oid_str] = 0.0
        order_seller_disc_other_pre[oid_str] = sum(
            sum(clean_num(v) for v in grp[c]) for c in seller_disc_other_cols if c in df.columns
        )
        order_shopee_disc_other_pre[oid_str] = sum(
            sum(clean_num(v) for v in grp[c]) for c in shopee_disc_other_cols if c in df.columns
        )

    # Sort rows by the pre-locked bill order stamped at processing time.
    # __bill_order__ is an integer (0-based order_index) already written into the df
    # by save-mapping / apply-return-decisions, so no re-computation needed here.
    if '__bill_order__' in df.columns:
        df = df.sort_values(by='__bill_order__', kind='stable', na_position='last').reset_index(drop=True)

    report_rows = []
    seen_orders = set()
    order_shipping_buyer = {}
    order_service_fee = {}
    order_grand_total = {}
    order_estimated_shipping = {}
    order_seller_disc_main = {}
    order_seller_disc_other = {}
    order_shopee_disc_main = {}
    order_shopee_disc_other = {}
    order_shopee_shipping = {}
    order_buyer_paid = {}
    order_commission = {}
    order_transaction_fee = {}
    order_total_fee = {}
    order_actual_receive = {}
    total_qty = 0.0
    row_number = 0
    model_stats = {}

    for _, row in df.iterrows():
        oid = str(row[order_col]) if pd.notna(row[order_col]) else ''
        model = extract_model(row.get(product_col, ''))
        sale_price = clean_num(row.get(sale_price_col, 0))
        if preset and preset.implicit_quantity is not None:
            qty = float(preset.implicit_quantity)
        else:
            qty = clean_num(row.get(qty_col, 0)) if qty_col in df.columns else 1.0
        total_qty += qty
        row_number += 1

        option_val = row.get(option_name_col, '') if option_name_col in df.columns else ''
        color = extract_color(option_val)
        size = extract_size(option_val)

        if model:
            if model not in model_stats:
                model_stats[model] = {'total_value': 0.0, 'total_qty': 0.0, 'prices': []}
            model_stats[model]['total_value'] += sale_price * qty
            model_stats[model]['total_qty'] += qty
            model_stats[model]['prices'].append(sale_price)

        net_sale = clean_num(row.get(net_sale_col, 0)) if net_sale_col and net_sale_col in df.columns else (sale_price * qty)

        is_first_row = oid not in seen_orders
        if is_first_row:
            seen_orders.add(oid)
            inv_data = invoice_lookup.get(oid, {})
            # Read bill number from pre-stamped DF column — no re-computation
            if '__bill_number__' in df.columns:
                bill_num = str(row.get('__bill_number__', ''))
            else:
                bill_num = _format_bill_number(bill_prefix, starting_bill_number + inv_data.get('order_index', 0))
            sb = inv_data.get('shipping', 0.0)
            sf = inv_data.get('service_fee', 0.0)
            gt = inv_data.get('grand_total', 0.0)
            es = clean_num(row.get(estimated_shipping_col, 0)) if estimated_shipping_col in df.columns else 0.0
            vat_amt = inv_data.get('vat_amount', 0.0)
            before_vat = inv_data.get('total_before_vat', 0.0)
            recipient = str(row.get(recipient_col, '')) if recipient_col in df.columns else ''
            sd_main = order_seller_disc_main_pre.get(oid, 0.0)
            sd_other = order_seller_disc_other_pre.get(oid, 0.0)
            shopee_disc_main = clean_num(row.get(shopee_discount_col, 0)) if shopee_discount_col in df.columns else 0.0
            shopee_disc_other = order_shopee_disc_other_pre.get(oid, 0.0)
            shopee_ship = clean_num(row.get(shopee_shipping_col, 0)) if shopee_shipping_col and shopee_shipping_col in df.columns else 0.0
            comm_fee = safe_col_val(row, commission_col)
            trans_fee = safe_col_val(row, transaction_fee_col)
            svc_fee_val = sf
            total_fee = comm_fee + trans_fee + svc_fee_val
            buyer_paid = safe_col_val(row, buyer_paid_col)
            actual_receive = buyer_paid + shopee_disc_main - total_fee - sb

            order_shipping_buyer[oid] = sb
            order_service_fee[oid] = sf
            order_grand_total[oid] = gt
            order_estimated_shipping[oid] = es
            order_seller_disc_main[oid] = sd_main
            order_seller_disc_other[oid] = sd_other
            order_shopee_disc_main[oid] = shopee_disc_main
            order_shopee_disc_other[oid] = shopee_disc_other
            order_shopee_shipping[oid] = shopee_ship
            order_buyer_paid[oid] = buyer_paid
            order_commission[oid] = comm_fee
            order_transaction_fee[oid] = trans_fee
            order_total_fee[oid] = total_fee
            order_actual_receive[oid] = actual_receive
        else:
            bill_num = ''
            recipient = ''
            sb = sf = gt = es = vat_amt = before_vat = None
            sd_main = sd_other = shopee_disc_main = shopee_disc_other = shopee_ship = None
            comm_fee = trans_fee = svc_fee_val = total_fee = buyer_paid = actual_receive = None

        report_rows.append({
            'row_num': row_number,
            'bill_number': bill_num,
            'recipient': recipient,
            'order_id': oid if is_first_row else '',
            'model': model,
            'color': color,
            'size': size,
            'sale_price': sale_price,
            'qty': qty,
            'net_sale': net_sale,
            'seller_disc_main': sd_main,
            'seller_disc_other': sd_other,
            'shopee_disc_main': shopee_disc_main,
            'shopee_disc_other': shopee_disc_other,
            'shipping_buyer': sb,
            'shopee_shipping': shopee_ship,
            'buyer_paid': buyer_paid,
            'estimated_shipping': es,
            'grand_total': gt,
            'vat_amount': vat_amt,
            'total_before_vat': before_vat,
            'commission': comm_fee,
            'transaction_fee': trans_fee,
            'service_fee': sf,
            'total_fee': total_fee,
            'actual_receive': actual_receive,
        })

    return {
        'report_rows': report_rows,
        'seen_orders': seen_orders,
        'total_qty': total_qty,
        'model_stats': model_stats,
        'order_shipping_buyer': order_shipping_buyer,
        'order_service_fee': order_service_fee,
        'order_grand_total': order_grand_total,
        'order_estimated_shipping': order_estimated_shipping,
        'order_seller_disc_main': order_seller_disc_main,
        'order_seller_disc_other': order_seller_disc_other,
        'order_shopee_disc_main': order_shopee_disc_main,
        'order_shopee_disc_other': order_shopee_disc_other,
        'order_shopee_shipping': order_shopee_shipping,
        'order_buyer_paid': order_buyer_paid,
        'order_commission': order_commission,
        'order_transaction_fee': order_transaction_fee,
        'order_total_fee': order_total_fee,
        'order_actual_receive': order_actual_receive,
    }


def build_sales_report_pdf(sales_data, invoices):
    """Render the sales report PDF (26-column detail table + summary + top-10
    models) and return it as bytes.

    `sales_data` is the dict returned by build_sales_data(). `invoices` is the
    list of Invoice objects for the current session, used for the VAT / pre-VAT
    summary totals (pre-computed on the Invoice, not re-derived here).
    """
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
    from reportlab.lib.styles import ParagraphStyle

    from .fonts import register_thai_fonts

    thai_font, thai_font_bold = register_thai_fonts()

    report_rows = sales_data['report_rows']
    seen_orders = sales_data['seen_orders']
    total_qty = sales_data['total_qty']
    model_stats = sales_data['model_stats']
    order_shipping_buyer = sales_data['order_shipping_buyer']
    order_service_fee = sales_data['order_service_fee']
    order_grand_total = sales_data['order_grand_total']
    order_estimated_shipping = sales_data['order_estimated_shipping']
    order_seller_disc_main = sales_data['order_seller_disc_main']
    order_seller_disc_other = sales_data['order_seller_disc_other']
    order_shopee_disc_main = sales_data['order_shopee_disc_main']
    order_shopee_disc_other = sales_data['order_shopee_disc_other']
    order_shopee_shipping = sales_data['order_shopee_shipping']
    order_buyer_paid = sales_data['order_buyer_paid']
    order_commission = sales_data['order_commission']
    order_transaction_fee = sales_data['order_transaction_fee']
    order_total_fee = sales_data['order_total_fee']
    order_actual_receive = sales_data['order_actual_receive']

    # Build PDF — landscape A4 to accommodate more columns
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=14, rightMargin=14, topMargin=40, bottomMargin=30)

    title_style = ParagraphStyle('Title', fontName=thai_font_bold, fontSize=14, leading=18, alignment=0)
    header_style = ParagraphStyle('Header', fontName=thai_font_bold, fontSize=6, leading=8, alignment=1)
    cell_style = ParagraphStyle('Cell', fontName=thai_font, fontSize=6, leading=8)
    cell_center = ParagraphStyle('CellCenter', fontName=thai_font, fontSize=6, leading=8, alignment=1)
    cell_right = ParagraphStyle('CellRight', fontName=thai_font, fontSize=6, leading=8, alignment=2)

    elements = []
    elements.append(Paragraph('Sales Report (รายงานยอดขาย)', title_style))
    elements.append(Spacer(1, 12))

    # Table header — 26 columns (landscape layout)
    headers = [
        Paragraph('ลำดับ', header_style),
        Paragraph('เลขที่บิล', header_style),
        Paragraph('ชื่อผู้รับ', header_style),
        Paragraph('หมายเลข\nคำสั่งซื้อ', header_style),
        Paragraph('รหัส\nสินค้า', header_style),
        Paragraph('ตัวเลือก\n(สี)', header_style),
        Paragraph('ตัวเลือก\n(ขนาด)', header_style),
        Paragraph('ราคาขาย', header_style),
        Paragraph('จำนวน', header_style),
        Paragraph('รวมเป็นเงิน', header_style),
        Paragraph('ส่วนลด\nผู้ขาย', header_style),
        Paragraph('ส่วนลดอื่นๆ\nผู้ขาย', header_style),
        Paragraph('ส่วนลด\nShopee', header_style),
        Paragraph('ส่วนลดอื่นๆ\nShopee', header_style),
        Paragraph('ค่าจัดส่ง\n(ผู้ซื้อ)', header_style),
        Paragraph('ค่าจัดส่ง\nShopee', header_style),
        Paragraph('ราคาสินค้า\nชำระโดยผู้ซื้อ', header_style),
        Paragraph('ค่าจัดส่ง\nประมาณ', header_style),
        Paragraph('จำนวนเงิน\nทั้งหมด', header_style),
        Paragraph('VAT 7%', header_style),
        Paragraph('ยอดก่อน\nVAT', header_style),
        Paragraph('ค่าคอม', header_style),
        Paragraph('Transaction\nFee', header_style),
        Paragraph('ค่าบริการ', header_style),
        Paragraph('ค่าธรรม\nเนียม', header_style),
        Paragraph('จำนวนเงิน\nได้รับจริง', header_style),
    ]

    def fmt(val):
        if val is None:
            return ''
        return f'{val:,.2f}'

    table_data = [headers]
    for r in report_rows:
        qty_val = r['qty']
        qty_str = str(int(qty_val)) if qty_val == int(qty_val) else fmt(qty_val)
        table_data.append([
            Paragraph(str(r['row_num']), cell_center),
            Paragraph(r['bill_number'], cell_center),
            Paragraph(r['recipient'], cell_style),
            Paragraph(r['order_id'], cell_style),
            Paragraph(r['model'], cell_style),
            Paragraph(r['color'], cell_style),
            Paragraph(r['size'], cell_center),
            Paragraph(fmt(r['sale_price']), cell_right),
            Paragraph(qty_str, cell_right),
            Paragraph(fmt(r['net_sale']), cell_right),
            Paragraph(fmt(r['seller_disc_main']), cell_right),
            Paragraph(fmt(r['seller_disc_other']), cell_right),
            Paragraph(fmt(r['shopee_disc_main']), cell_right),
            Paragraph(fmt(r['shopee_disc_other']), cell_right),
            Paragraph(fmt(r['shipping_buyer']), cell_right),
            Paragraph(fmt(r['shopee_shipping']), cell_right),
            Paragraph(fmt(r['buyer_paid']), cell_right),
            Paragraph(fmt(r['estimated_shipping']), cell_right),
            Paragraph(fmt(r['grand_total']), cell_right),
            Paragraph(fmt(r['vat_amount']), cell_right),
            Paragraph(fmt(r['total_before_vat']), cell_right),
            Paragraph(fmt(r['commission']), cell_right),
            Paragraph(fmt(r['transaction_fee']), cell_right),
            Paragraph(fmt(r['service_fee']), cell_right),
            Paragraph(fmt(r['total_fee']), cell_right),
            Paragraph(fmt(r['actual_receive']), cell_right),
        ])

    # Landscape A4 usable width: ~814pt (842 - 2*14 margins)
    # 26 cols total = 784pt
    col_widths = [14, 34, 38, 54, 30, 40, 18, 28, 18, 32,
                  30, 30, 28, 30, 30, 30, 36, 28, 34, 26,
                  30, 28, 28, 24, 30, 36]
    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), thai_font),
        ('FONTSIZE', (0, 0), (-1, -1), 6),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4a90d9')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (7, 1), (-1, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0f4f8')]),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]))
    elements.append(t)

    # Page break before summary
    elements.append(PageBreak())

    # Summary table
    sum_title_style = ParagraphStyle('SumTitle', fontName=thai_font_bold, fontSize=11, leading=14)
    elements.append(Paragraph('Summary (สรุป)', sum_title_style))
    elements.append(Spacer(1, 8))

    sum_shipping_buyer = sum(order_shipping_buyer.values())
    sum_service_fee = sum(order_service_fee.values())
    sum_grand_total = sum(order_grand_total.values())
    sum_estimated_shipping = sum(order_estimated_shipping.values())
    sum_seller_disc_main = sum(order_seller_disc_main.values())
    sum_seller_disc_other = sum(order_seller_disc_other.values())
    sum_shopee_disc_main = sum(order_shopee_disc_main.values())
    sum_shopee_disc_other = sum(order_shopee_disc_other.values())
    sum_shopee_shipping = sum(order_shopee_shipping.values())
    sum_buyer_paid = sum(order_buyer_paid.values())
    sum_commission = sum(order_commission.values())
    sum_transaction_fee = sum(order_transaction_fee.values())
    sum_total_fee = sum(order_total_fee.values())
    sum_actual_receive = sum(order_actual_receive.values())

    # Sum VAT from pre-computed invoice values
    sum_vat = sum(inv.vat_amount for inv in invoices)
    sum_before_vat = sum(inv.total_before_vat for inv in invoices)

    summary_data = [
        [Paragraph('รายการ', header_style), Paragraph('ยอดรวม', header_style)],
        [Paragraph('จำนวนคำสั่งซื้อ', cell_style), Paragraph(f'{len(seen_orders):,}', cell_right)],
        [Paragraph('จำนวนสินค้า (ชิ้น)', cell_style), Paragraph(f'{int(total_qty):,}', cell_right)],
        [Paragraph('ส่วนลดโดยผู้ขาย', cell_style), Paragraph(fmt(sum_seller_disc_main), cell_right)],
        [Paragraph('ส่วนลดอื่นๆ โดยผู้ขาย', cell_style), Paragraph(fmt(sum_seller_disc_other), cell_right)],
        [Paragraph('ส่วนลดโดย Shopee', cell_style), Paragraph(fmt(sum_shopee_disc_main), cell_right)],
        [Paragraph('ส่วนลดอื่นๆ โดย Shopee', cell_style), Paragraph(fmt(sum_shopee_disc_other), cell_right)],
        [Paragraph('ค่าจัดส่ง (ผู้ซื้อ)', cell_style), Paragraph(fmt(sum_shipping_buyer), cell_right)],
        [Paragraph('ค่าจัดส่งโดย Shopee', cell_style), Paragraph(fmt(sum_shopee_shipping), cell_right)],
        [Paragraph('ราคาสินค้าชำระโดยผู้ซื้อ', cell_style), Paragraph(fmt(sum_buyer_paid), cell_right)],
        [Paragraph('ค่าจัดส่งโดยประมาณ', cell_style), Paragraph(fmt(sum_estimated_shipping), cell_right)],
        [Paragraph('จำนวนเงินทั้งหมด', cell_style), Paragraph(fmt(sum_grand_total), cell_right)],
        [Paragraph('ยอดก่อน VAT', cell_style), Paragraph(fmt(sum_before_vat), cell_right)],
        [Paragraph('VAT 7%', cell_style), Paragraph(fmt(sum_vat), cell_right)],
        [Paragraph('ค่าคอมมิชชั่น', cell_style), Paragraph(fmt(sum_commission), cell_right)],
        [Paragraph('Transaction Fee', cell_style), Paragraph(fmt(sum_transaction_fee), cell_right)],
        [Paragraph('ค่าบริการ', cell_style), Paragraph(fmt(sum_service_fee), cell_right)],
        [Paragraph('ค่าธรรมเนียมรวม', cell_style), Paragraph(fmt(sum_total_fee), cell_right)],
        [Paragraph('จำนวนเงินที่ได้รับจริง', cell_style), Paragraph(fmt(sum_actual_receive), cell_right)],
    ]

    st = Table(summary_data, colWidths=[200, 120])
    st.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), thai_font),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4a90d9')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0f4f8')]),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(st)

    # Top 10 Models by Sales Value
    elements.append(Spacer(1, 24))
    elements.append(Paragraph('Top 10 Models by Sales Value (สินค้าขายดี 10 อันดับ)', sum_title_style))
    elements.append(Spacer(1, 8))

    # Calculate total sales value across all models
    total_sales_value = sum(m['total_value'] for m in model_stats.values())

    # Sort models by total_value descending, take top 10
    top_models = sorted(model_stats.items(), key=lambda x: x[1]['total_value'], reverse=True)[:10]

    top_header_style = ParagraphStyle('TopHeader', fontName=thai_font_bold, fontSize=8, leading=10, alignment=1)
    top_cell = ParagraphStyle('TopCell', fontName=thai_font, fontSize=8, leading=10)
    top_cell_right = ParagraphStyle('TopCellRight', fontName=thai_font, fontSize=8, leading=10, alignment=2)
    top_cell_center = ParagraphStyle('TopCellCenter', fontName=thai_font, fontSize=8, leading=10, alignment=1)

    top_data = [[
        Paragraph('#', top_header_style),
        Paragraph('Model', top_header_style),
        Paragraph('ราคาเฉลี่ย', top_header_style),
        Paragraph('จำนวนขาย', top_header_style),
        Paragraph('ยอดขาย', top_header_style),
        Paragraph('% ของยอดรวม', top_header_style),
    ]]

    for rank, (model_name, stats) in enumerate(top_models, 1):
        avg_price = sum(stats['prices']) / len(stats['prices']) if stats['prices'] else 0
        pct = (stats['total_value'] / total_sales_value * 100) if total_sales_value > 0 else 0
        top_data.append([
            Paragraph(str(rank), top_cell_center),
            Paragraph(model_name, top_cell),
            Paragraph(fmt(avg_price), top_cell_right),
            Paragraph(f'{int(stats["total_qty"]):,}', top_cell_right),
            Paragraph(fmt(stats['total_value']), top_cell_right),
            Paragraph(f'{pct:.1f}%', top_cell_right),
        ])

    top_table = Table(top_data, colWidths=[25, 80, 80, 65, 90, 80])
    top_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), thai_font),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4a90d9')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f0f4f8')]),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    elements.append(top_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer.read()


# Thai column headers matching the 26-column PDF layout, in export order.
SALES_EXPORT_COLUMN_MAP = {
    'row_num':          'ลำดับ',
    'bill_number':      'เลขที่บิล',
    'recipient':        'ชื่อผู้รับ',
    'order_id':         'หมายเลขคำสั่งซื้อ',
    'model':            'รหัสสินค้า',
    'color':            'ตัวเลือก (สี)',
    'size':             'ตัวเลือก (ขนาด)',
    'sale_price':       'ราคาขาย',
    'qty':              'จำนวนสินค้า',
    'net_sale':         'รวมเป็นเงิน',
    'seller_disc_main': 'ส่วนลดโดยผู้ขาย',
    'seller_disc_other':'ส่วนลดอื่นๆ โดยผู้ขาย',
    'shopee_disc_main': 'ส่วนลดโดย Shopee',
    'shopee_disc_other':'ส่วนลดอื่นๆ โดย Shopee',
    'shipping_buyer':   'ค่าจัดส่ง (ผู้ซื้อ)',
    'shopee_shipping':  'ค่าจัดส่งโดย Shopee',
    'buyer_paid':       'ราคาสินค้าที่ชำระโดยผู้ซื้อ',
    'estimated_shipping':'ค่าจัดส่งประมาณ',
    'grand_total':      'จำนวนเงินทั้งหมด',
    'vat_amount':       'VAT 7%',
    'total_before_vat': 'ยอดก่อน VAT',
    'commission':       'ค่าคอมมิชชั่น',
    'transaction_fee':  'Transaction Fee',
    'service_fee':      'ค่าบริการ',
    'total_fee':        'ค่าธรรมเนียม',
    'actual_receive':   'จำนวนเงินที่ได้รับจริง',
}


def build_sales_export_df(report_rows):
    """Build the renamed DataFrame used for the CSV/XLSX sales report export."""
    export_df = pd.DataFrame(report_rows)[list(SALES_EXPORT_COLUMN_MAP.keys())]
    export_df.rename(columns=SALES_EXPORT_COLUMN_MAP, inplace=True)
    return export_df
