"""Tests for src/bill_data.py: Thai VAT rounding and Invoice.compute_vat."""
import pytest

from src.bill_data import thai_vat_round, Invoice, Customer


class TestThaiVatRound:
    def test_round_up_at_half_third_decimal(self):
        # Thai rule: 3rd decimal >= 5 rounds the 2nd decimal up (ROUND_HALF_UP,
        # not banker's rounding).
        assert thai_vat_round(1.005) == 1.01
        assert thai_vat_round(2.675) == 2.68

    def test_truncate_when_below_half(self):
        assert thai_vat_round(2.674) == 2.67
        assert thai_vat_round(1.004) == 1.00

    def test_already_two_decimals_unchanged(self):
        assert thai_vat_round(10.50) == 10.50
        assert thai_vat_round(0.0) == 0.0

    def test_negative_amounts_round_half_up_away_from_zero(self):
        # Decimal's ROUND_HALF_UP rounds away from zero, so -1.005 -> -1.01
        assert thai_vat_round(-1.005) == -1.01
        assert thai_vat_round(-2.674) == -2.67


def _make_invoice(grand_total, vat_rate=0.07):
    inv = Invoice(
        invoice_number='INV1',
        order_id='O1',
        bill_number='',
        order_date='01/01/2026',
        tracking_number='',
        customer=Customer(name='Test', address='Addr', phone='0800000000'),
        items=[],
        subtotal=grand_total,
        discount=0.0,
        shipping=0.0,
        service_fee=0.0,
        vat_rate=vat_rate,
        grand_total=grand_total,
    )
    inv.compute_vat()
    return inv


class TestComputeVat:
    @pytest.mark.parametrize('grand_total', [107.0, 100.0, 1.0, 999.99, 0.01, 53.55, 12345.67])
    def test_before_vat_plus_vat_equals_grand_total(self, grand_total):
        inv = _make_invoice(grand_total)
        assert round(inv.total_before_vat + inv.vat_amount, 2) == round(grand_total, 2)

    def test_known_value_107_baht_at_7_percent(self):
        # 107 * 7/107 = 7 exactly
        inv = _make_invoice(107.0)
        assert inv.vat_amount == 7.0
        assert inv.total_before_vat == 100.0

    def test_vat_amount_uses_thai_rounding(self):
        inv = _make_invoice(53.55)
        raw_vat = 53.55 * 0.07 / 1.07
        assert inv.vat_amount == thai_vat_round(raw_vat)

    def test_zero_grand_total(self):
        inv = _make_invoice(0.0)
        assert inv.vat_amount == 0.0
        assert inv.total_before_vat == 0.0
