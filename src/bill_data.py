"""
Data models for bill generation
"""
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import List


def thai_vat_round(amount: float) -> float:
    """Round to 2 decimal places using Thai tax rounding rules.

    Thai Revenue Department rule: look at 3rd decimal place,
    if < 5 truncate, if >= 5 round up. This is standard ROUND_HALF_UP.
    """
    d = Decimal(str(amount))
    return float(d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


@dataclass
class CompanyInfo:
    """Company information for bill header"""
    name: str
    tax_id: str
    address: str
    phone: str
    branch_code: str = ""
    branch_address: str = ""


@dataclass
class Customer:
    """Customer information"""
    name: str
    address: str
    phone: str


@dataclass
class LineItem:
    """Single product line item"""
    description: str  # Product name + variant
    quantity: float
    unit_price: float
    total: float


@dataclass
class Invoice:
    """Complete invoice data"""
    invoice_number: str  # Tax invoice number (เลขที่ใบกำกับ)
    order_id: str  # Order number (หมายเลขคำสั่งซื้อ)
    bill_number: str  # Internal bill number (เลขที่บิล) - format: 26XXXXX
    order_date: str
    tracking_number: str
    customer: Customer
    items: List[LineItem]
    subtotal: float
    discount: float
    shipping: float
    service_fee: float
    vat_rate: float
    grand_total: float
    # Pre-computed VAT fields (Thai rounding applied)
    vat_amount: float = 0.0
    total_before_vat: float = 0.0
    # Sortable ISO datetime string (YYYY-MM-DD HH:MM:SS) for ordering; time trimmed only at display
    order_sort_key: str = ""
    # 0-based position in the final sorted invoice list, locked in at processing time.
    # bill_number = bill_prefix + (starting_bill_number + order_index)
    order_index: int = 0
    # New fields for detailed product amount breakdown (Thai tax invoice requirements)
    subtotal_before_discount: float = 0.0  # ราคารวมสินค้าก่อนหักส่วนลด
    subtotal_after_discount: float = 0.0   # ราคารวมสินค้าหลังหักส่วนลด (before shipping)

    def compute_vat(self):
        """Compute VAT using Thai tax standard.

        For VAT-inclusive pricing (Shopee prices include VAT):
        1. vat = grand_total * 7 / 107, rounded with Thai rules
        2. before_vat = grand_total - vat (exact, no rounding mismatch)
        """
        gt = self.grand_total
        raw_vat = gt * self.vat_rate / (1 + self.vat_rate)
        self.vat_amount = thai_vat_round(raw_vat)
        self.total_before_vat = thai_vat_round(gt - self.vat_amount)

    def calculate_grand_total(self) -> float:
        """Calculate grand total: all item prices + shipping - discount"""
        return self.subtotal + self.shipping - self.discount

    def calculate_total_before_vat(self) -> float:
        """Return pre-computed total before VAT"""
        return self.total_before_vat

    def calculate_vat(self) -> float:
        """Return pre-computed VAT amount"""
        return self.vat_amount