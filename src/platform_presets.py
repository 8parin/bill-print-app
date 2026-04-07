"""
Platform presets for multi-platform CSV support.

Each platform (Shopee, Lazada, TikTok Shop) has its own column names,
status values, and data quirks. This file centralizes all platform-specific
configuration so the parser stays platform-agnostic.

To update when a platform changes column names:
  1. Find the preset below (e.g. LAZADA_PRESET)
  2. Change the column name in column_map
  3. Update fingerprint_columns if the renamed column was a fingerprint
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PlatformPreset:
    name: str                   # Internal key: "shopee", "lazada", "tiktok"
    display_name: str           # UI label: "Shopee", "Lazada", "TikTok Shop"

    # Maps internal field keys -> platform CSV column names
    column_map: dict

    # 3-4 column names unique to this platform (for auto-detection)
    fingerprint_columns: set

    # Status values that mean "cancelled order"
    cancelled_statuses: list

    # Field key for return status column, or None if platform has no separate return column
    return_status_field: Optional[str]

    # Status values that mean "confirmed return"
    confirmed_return_statuses: list

    # True only for Shopee: blank rows below = same invoice, need forward-fill
    needs_forward_fill: bool

    # Row indices to skip after reading (e.g. [1] for TikTok metadata row)
    skip_rows: list = field(default_factory=list)

    # If platform has no explicit quantity column, set this (e.g. 1 for Lazada)
    implicit_quantity: Optional[int] = None

    # Date offset in days (e.g. +1 for Lazada to shift createTime forward)
    date_offset_days: int = 0

    # CSV column names to concatenate for full address
    # Single-element list = use that column directly
    # Multi-element list = join with ", "
    address_fields: list = field(default_factory=lambda: ['address'])

    # Field keys that are per-invoice (used for forward-fill when needs_forward_fill=True)
    invoice_level_fields: list = field(default_factory=list)

    # CSV column names to sum across all items for discount (overrides shopee_discount single-column)
    # Empty list = use shopee_discount column from column_map (default behavior)
    discount_sum_columns: list = field(default_factory=list)

    # Fallback CSV column names for order_date when primary column is NaN (e.g. unshipped TikTok orders)
    date_fallback_columns: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Shopee
# ---------------------------------------------------------------------------
SHOPEE_PRESET = PlatformPreset(
    name='shopee',
    display_name='Shopee',
    column_map={
        'order_id': 'หมายเลขคำสั่งซื้อ',
        'buyer_username': 'ชื่อผู้ใช้ (ผู้ซื้อ)',
        'order_date': 'เวลาส่งสินค้า',
        'payment_time': 'เวลาการชำระสินค้า',
        'product_name': 'ชื่อสินค้า',
        'sale_price': 'ราคาขาย',
        'quantity': 'จำนวน',
        'total': 'ราคาขายสุทธิ',
        'shipping_buyer': 'ค่าจัดส่งที่ชำระโดยผู้ซื้อ',
        'service_fee': 'ค่าบริการ',
        'grand_total': 'จำนวนเงินทั้งหมด',
        'estimated_shipping': 'ค่าจัดส่งโดยประมาณ',
        'recipient_name': 'ชื่อผู้รับ',
        'phone': 'หมายเลขโทรศัพท์',
        'address': 'ที่อยู่ในการจัดส่ง',
        'tracking_number': '*หมายเลขติดตามพัสดุ',
        'payment_method': 'ช่องทางการชำระเงิน',
        'shipping_time': 'เวลาส่งสินค้า',
        'shopee_discount': 'โค้ดส่วนลดชำระโดยผู้ขาย',
        'variant': 'ชื่อตัวเลือก',
        'tax_invoice': 'หมายเลขคำสั่งซื้อ',
        'order_status': 'สถานะการสั่งซื้อ',
        'return_status': 'สถานะการคืนเงินหรือคืนสินค้า',
    },
    fingerprint_columns={'หมายเลขคำสั่งซื้อ', 'ชื่อสินค้า', 'ชื่อผู้รับ'},
    cancelled_statuses=['ยกเลิกแล้ว'],
    return_status_field='return_status',
    confirmed_return_statuses=['คำขอได้รับการยอมรับแล้ว'],
    needs_forward_fill=True,
    address_fields=['address'],  # single column: ที่อยู่ในการจัดส่ง
    invoice_level_fields=[
        'order_id', 'tax_invoice', 'order_date', 'recipient_name',
        'phone', 'address', 'tracking_number', 'shopee_discount',
        'shipping_buyer', 'service_fee', 'grand_total', 'estimated_shipping',
    ],
)

# ---------------------------------------------------------------------------
# Lazada
# ---------------------------------------------------------------------------
LAZADA_PRESET = PlatformPreset(
    name='lazada',
    display_name='Lazada',
    column_map={
        'order_id': 'orderNumber',
        'product_name': 'itemName',
        'variant': 'variation',
        'sale_price': 'unitPrice',
        'total': 'paidPrice',
        'recipient_name': 'billingName',
        'phone': 'billingPhone',
        'address': 'billingAddr',  # primary address field
        'tracking_number': 'trackingCode',
        'order_date': 'createTime',
        'order_status': 'status',
        'shipping_buyer': 'shippingFee',
        'grand_total': 'paidPrice',
        'shopee_discount': 'sellerDiscountTotal',  # reuse key for discount
        'tax_invoice': 'orderNumber',  # group by order number
        'service_fee': 'shippingFee',  # placeholder — Lazada bundles fees differently
    },
    fingerprint_columns={'orderItemId', 'lazadaId', 'lazadaSku'},
    cancelled_statuses=['canceled', 'cancelled'],
    return_status_field=None,  # Lazada has no separate return column
    confirmed_return_statuses=[],
    needs_forward_fill=False,  # every row has orderNumber
    implicit_quantity=1,  # each row = 1 item
    date_offset_days=1,  # Lazada createTime is 1 day behind actual order date
    address_fields=[
        'billingAddr', 'billingAddr2', 'billingAddr3', 'billingAddr4', 'billingAddr5',
    ],
    invoice_level_fields=[],
    discount_sum_columns=['sellerDiscountTotal'],  # sum per-item discount across invoice
)

# ---------------------------------------------------------------------------
# TikTok Shop
# ---------------------------------------------------------------------------
TIKTOK_PRESET = PlatformPreset(
    name='tiktok',
    display_name='TikTok Shop',
    column_map={
        'order_id': 'Order ID',
        'product_name': 'Product Name',
        'variant': 'Variation',
        'quantity': 'Quantity',
        'sale_price': 'SKU Subtotal Before Discount',
        'total': 'SKU Subtotal After Discount',
        'recipient_name': 'Recipient',
        'phone': 'Phone #',
        'address': 'Detail Address',  # primary address field
        'tracking_number': 'Tracking ID',
        'order_date': 'Shipped Time',           # use Shipped Time for bill date
        'order_status': 'Order Status',
        'return_status': 'Cancelation/Return Type',
        'shipping_buyer': 'Shipping Fee',  # customer-paid shipping fee (ค่าขนส่งที่ลูกค้าชำระ)
        'grand_total': 'Order Amount',
        'shopee_discount': 'SKU Seller Discount',  # reuse key for discount
        'tax_invoice': 'Order ID',  # group by order ID
        'service_fee': 'Small Order Fee',
    },
    fingerprint_columns={'SKU ID', 'Seller SKU', 'SKU Subtotal After Discount'},
    cancelled_statuses=['ยกเลิกแล้ว'],
    return_status_field='return_status',
    confirmed_return_statuses=['Return'],
    needs_forward_fill=False,  # every row has Order ID
    skip_rows=[0],  # DataFrame index 0 is a metadata/description row (file row 2, after header)
    address_fields=['Detail Address', 'District', 'Province', 'Zipcode'],
    invoice_level_fields=[],
    discount_sum_columns=['SKU Seller Discount'],  # seller discount only (not platform discount)
    date_fallback_columns=['RTS Time', 'Paid Time', 'Created Time'],  # fallback when Shipped Time is NaN
)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
PLATFORM_PRESETS = {
    'shopee': SHOPEE_PRESET,
    'lazada': LAZADA_PRESET,
    'tiktok': TIKTOK_PRESET,
}


def detect_platform(csv_columns: list) -> Optional[str]:
    """Auto-detect platform from CSV header column names.

    Checks each preset's fingerprint_columns against the actual headers.
    Returns the platform key ('shopee', 'lazada', 'tiktok') or None.
    """
    col_set = set(csv_columns)
    for key, preset in PLATFORM_PRESETS.items():
        if preset.fingerprint_columns.issubset(col_set):
            return key
    return None
