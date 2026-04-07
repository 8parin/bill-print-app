"""
Alternative PDF generator using ReportLab for better Thai font support
"""
import os
import time
from typing import List
from reportlab.lib.pagesizes import A4, A5, LETTER, landscape, portrait
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from .bill_data import Invoice, CompanyInfo


class PDFGeneratorReportLab:
    """Generate PDF bills using ReportLab for better Thai support"""
    
    def __init__(self, output_dir: str):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)
        
        # Register Tahoma font which properly supports Thai Unicode
        try:
            pdfmetrics.registerFont(TTFont('ThaiFont', '/System/Library/Fonts/Supplemental/Tahoma.ttf'))
            pdfmetrics.registerFont(TTFont('ThaiFont-Bold', '/System/Library/Fonts/Supplemental/Tahoma Bold.ttf'))
            self.thai_font = 'ThaiFont'
            self.thai_font_bold = 'ThaiFont-Bold'
            print("✅ Thai fonts (Tahoma) loaded successfully")
        except Exception as e:
            print(f"❌ Font loading error: {e}")
            # Fallback to Helvetica (won't display Thai properly but won't crash)
            self.thai_font = 'Helvetica'
            self.thai_font_bold = 'Helvetica-Bold'
    
    
    def _get_page_size(self, paper_size: str, orientation: str):
        """Get page size tuple based on paper size and orientation"""
        size_map = {
            'A4': A4,
            'A5': A5,
            'Letter': LETTER
        }
        
        page_size = size_map.get(paper_size, A5)  # Default to A5
        
        if orientation == 'landscape':
            return landscape(page_size)
        else:
            return portrait(page_size)
    
    def generate_single_bill(self, invoice: Invoice, company: CompanyInfo,
                            paper_size: str = 'A5', orientation: str = 'portrait') -> str:
        """Generate a single bill PDF using ReportLab"""
        # Create output filename
        safe_invoice_num = invoice.invoice_number.replace('/', '_').replace('\\', '_')
        output_filename = f"bill_{safe_invoice_num}.pdf"
        output_path = os.path.join(self.output_dir, output_filename)

        # Get page size
        page_size = self._get_page_size(paper_size, orientation)
        is_landscape = orientation == 'landscape'

        # Adjust margins based on orientation
        if is_landscape:
            margin = 4*mm
            top_margin = 3*mm
            bottom_margin = 2*mm
        else:
            margin = 6*mm
            top_margin = 4*mm
            bottom_margin = 2*mm

        # Calculate usable width from actual page size
        page_width = page_size[0]
        W = page_width - 2 * margin  # usable content width

        # Create PDF
        doc = SimpleDocTemplate(output_path, pagesize=page_size,
                               topMargin=top_margin, bottomMargin=bottom_margin,
                               leftMargin=margin, rightMargin=margin)

        story = []

        # Font sizes - smaller for landscape to save vertical space
        font_sz = 7 if is_landscape else 7.5
        font_leading = 9 if is_landscape else 10
        item_font_sz = 6.5 if is_landscape else 6.5
        item_leading = 8.5 if is_landscape else 9
        spacer_sm = 1*mm if is_landscape else 1.5*mm
        spacer_md = 1.5*mm if is_landscape else 2*mm
        cell_pad = 1*mm if is_landscape else 1.5*mm
        cell_pad_sm = 0.8*mm if is_landscape else 1*mm

        # Styles
        styles = getSampleStyleSheet()
        normal_style = ParagraphStyle('ThaiNormal',
                                     parent=styles['Normal'],
                                     fontName=self.thai_font,
                                     fontSize=font_sz,
                                     leading=font_leading,
                                     alignment=TA_LEFT)
        normal_center = ParagraphStyle('ThaiCenter',
                                       parent=normal_style,
                                       alignment=TA_CENTER)
        company_left_style = ParagraphStyle('CompanyLeft',
                                            parent=styles['Normal'],
                                            fontName=self.thai_font_bold,
                                            fontSize=font_sz,
                                            leading=font_leading,
                                            alignment=TA_LEFT)
        company_right_style = ParagraphStyle('CompanyRight',
                                             parent=styles['Normal'],
                                             fontName=self.thai_font_bold,
                                             fontSize=font_sz,
                                             leading=font_leading,
                                             alignment=TA_RIGHT)

        # === HEADER: Company LEFT, Title RIGHT ===
        company_address_formatted = company.address.replace(' เขต', '<br/>เขต')

        header_data = [[
            Paragraph(f"<b>{company.name}</b><br/>{company_address_formatted}<br/>โทรศัพท์ {company.phone}", company_left_style),
            Paragraph("ใบกํากับภาษี(อย่างย่อ)<br/>ใบส่งสินค้า /ใบเสร็จรับเงิน<br/>เลขประจําตัวผู้เสียภาษี {tax_id}<br/>(เอกสารออกเป็นชุด)".format(tax_id=company.tax_id), company_right_style)
        ]]

        half_w = W / 2
        header_table = Table(header_data, colWidths=[half_w, half_w])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ]))
        story.append(header_table)
        story.append(Spacer(1, spacer_sm))

        # === CUSTOMER & ORDER INFO ===
        info_left_w = W * 0.58
        info_right_w = W * 0.42

        info_data = [
            [Paragraph(f"ลูกค้า: {invoice.customer.name}", normal_style),
             f"วันที่: {invoice.order_date}"],
            [Paragraph(f"ที่อยู่: {invoice.customer.address}", normal_style),
             f"เลขที่ใบสั่งซื้อ: {invoice.order_id}"],
            [f"โทรศัพท์: {invoice.customer.phone}",
             f"เลขที่บิล: {invoice.bill_number}"]
        ]

        info_table = Table(info_data, colWidths=[info_left_w, info_right_w])
        info_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('FONTNAME', (0, 0), (-1, -1), self.thai_font),
            ('FONTSIZE', (0, 0), (-1, -1), font_sz),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 2*mm),
            ('RIGHTPADDING', (0, 0), (-1, -1), 2*mm),
            ('TOPPADDING', (0, 0), (-1, -1), cell_pad_sm),
            ('BOTTOMPADDING', (0, 0), (-1, -1), cell_pad_sm),
        ]))
        story.append(info_table)
        story.append(Spacer(1, spacer_sm))

        # === ITEMS TABLE ===
        col_num_w = W * 0.07
        col_desc_w = W * 0.47
        col_qty_w = W * 0.12
        col_price_w = W * 0.17
        col_total_w = W * 0.17

        item_desc_style = ParagraphStyle('ItemDesc',
                                         parent=normal_style,
                                         fontSize=item_font_sz,
                                         leading=item_leading)

        items_data = [['ลําดับ', 'รายละเอียดสินค้า', 'จํานวน', 'ราคา/หน่วย', 'จํานวนเงิน']]

        for i, item in enumerate(invoice.items, 1):
            items_data.append([
                str(i),
                Paragraph(item.description, item_desc_style),
                f"{item.quantity:.2f}",
                f"{item.unit_price:.2f}",
                f"{item.total:.2f}"
            ])

        # Add empty rows for aesthetics: 6 for landscape, 8 for portrait
        max_item_rows = 6 if is_landscape else 8
        for _ in range(max(0, max_item_rows - len(invoice.items))):
            items_data.append(['', '', '', '', ''])

        items_table = Table(items_data,
                           colWidths=[col_num_w, col_desc_w, col_qty_w, col_price_w, col_total_w],
                           rowHeights=None)
        items_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('FONTNAME', (0, 0), (-1, -1), self.thai_font),
            ('FONTSIZE', (0, 0), (-1, -1), font_sz),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('ALIGN', (0, 1), (0, -1), 'CENTER'),
            ('ALIGN', (2, 1), (2, -1), 'CENTER'),
            ('ALIGN', (3, 1), (4, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), cell_pad),
            ('BOTTOMPADDING', (0, 0), (-1, -1), cell_pad),
        ]))
        story.append(items_table)
        story.append(Spacer(1, spacer_sm))

        # === TOTALS & SIGNATURES ===
        if is_landscape:
            # Landscape: place totals and signatures SIDE BY SIDE
            totals_label_w = W * 0.22
            totals_val_w = W * 0.12

            totals_data = [
                ['ส่วนลด', f"{invoice.discount:.2f}"],
                ['ค่าจัดส่ง', f"{invoice.shipping:.2f}"],
                ['รวมจํานวนเงิน', f"{invoice.calculate_grand_total():.2f}"],
                ['ราคาก่อนภาษีมูลค่าเพิ่ม', f"{invoice.calculate_total_before_vat():.2f}"],
                [f'ภาษีมูลค่าเพิ่ม {invoice.vat_rate*100:.0f}%', f"{invoice.calculate_vat():.2f}"],
            ]

            totals_table = Table(totals_data, colWidths=[totals_label_w, totals_val_w])
            totals_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), self.thai_font),
                ('FONTSIZE', (0, 0), (-1, -1), 6.5),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('LINEABOVE', (0, -1), (-1, -1), 1, colors.black),
                ('FONTNAME', (0, -1), (-1, -1), self.thai_font_bold),
                ('TOPPADDING', (0, 0), (-1, -1), 0.5*mm),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0.5*mm),
            ]))

            # Compact signatures for landscape
            sig_compact_style = ParagraphStyle('SigCompact',
                                               parent=normal_center,
                                               fontSize=6.5,
                                               leading=8)
            sig_w = W * 0.20
            signature_data = [[
                Paragraph("<b>ผู้จัดทํา</b><br/><br/><br/><br/><br/><br/>________________<br/>วันที่ ________", sig_compact_style),
                Paragraph(f"<b>ผู้รับสินค้า</b><br/>Tracking:<br/>{invoice.tracking_number}<br/><br/><br/><br/>________________<br/>วันที่ ________", sig_compact_style),
                Paragraph("<b>ผู้รับเงิน</b><br/><br/><br/><br/><br/><br/>________________<br/>วันที่ ________", sig_compact_style),
            ]]
            signature_table = Table(signature_data, colWidths=[sig_w, sig_w, sig_w])
            signature_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))

            # Combine totals (right) and signatures (left) in one row
            bottom_table = Table([[signature_table, totals_table]],
                                colWidths=[W * 0.60, W * 0.40])
            bottom_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ]))
            story.append(bottom_table)
        else:
            # Portrait: side-by-side layout (signatures left, totals right)
            totals_label_w = W * 0.25
            totals_val_w = W * 0.15

            totals_data = [
                ['ส่วนลด', f"{invoice.discount:.2f}"],
                ['ค่าจัดส่ง', f"{invoice.shipping:.2f}"],
                ['รวมจํานวนเงิน', f"{invoice.calculate_grand_total():.2f}"],
                ['ราคาก่อนภาษีมูลค่าเพิ่ม', f"{invoice.calculate_total_before_vat():.2f}"],
                [f'ภาษีมูลค่าเพิ่ม {invoice.vat_rate*100:.0f}%', f"{invoice.calculate_vat():.2f}"],
            ]

            totals_table = Table(totals_data, colWidths=[totals_label_w, totals_val_w])
            totals_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), self.thai_font),
                ('FONTSIZE', (0, 0), (-1, -1), 7),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('LINEABOVE', (0, -1), (-1, -1), 1, colors.black),
                ('FONTNAME', (0, -1), (-1, -1), self.thai_font_bold),
                ('TOPPADDING', (0, 0), (-1, -1), 1*mm),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 1*mm),
            ]))

            # Signatures - aligned: middle has 1 fewer blank to compensate for Tracking line
            sig_w = W * 0.19
            sig_style = ParagraphStyle('SigPortrait',
                                        parent=normal_center,
                                        fontSize=7,
                                        leading=9.5)
            signature_data = [[
                Paragraph("<b>ผู้จัดทํา</b><br/><br/><br/><br/>__________________<br/>วันที่ __________", sig_style),
                Paragraph(f"<b>ผู้รับสินค้า</b><br/>Tracking:<br/>{invoice.tracking_number}<br/><br/>__________________<br/>วันที่ __________", sig_style),
                Paragraph("<b>ผู้รับเงิน</b><br/><br/><br/><br/>__________________<br/>วันที่ __________", sig_style),
            ]]
            signature_table = Table(signature_data, colWidths=[sig_w, sig_w, sig_w])
            signature_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))

            # Combine signatures (left) and totals (right) in one row
            bottom_table = Table([[signature_table, totals_table]],
                                colWidths=[W * 0.58, W * 0.42])
            bottom_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ]))
            story.append(bottom_table)

        # Build PDF
        doc.build(story)

        return output_path
    
    def _generate_bill_content(self, invoice: Invoice, company: CompanyInfo,
                              page_size, orientation: str = 'portrait'):
        """Generate bill content as story elements (for multi-page PDFs)"""
        is_landscape = orientation == 'landscape'
        margin = 4*mm if is_landscape else 6*mm
        page_width = page_size[0]
        W = page_width - 2 * margin

        story = []

        # Font sizes - smaller for landscape to save vertical space
        font_sz = 7 if is_landscape else 7.5
        font_leading = 9 if is_landscape else 10
        item_font_sz = 6.5 if is_landscape else 6.5
        item_leading = 8.5 if is_landscape else 9
        spacer_sm = 1*mm if is_landscape else 1.5*mm
        spacer_md = 1.5*mm if is_landscape else 2*mm
        cell_pad = 1*mm if is_landscape else 1.5*mm
        cell_pad_sm = 0.8*mm if is_landscape else 1*mm

        # Styles
        styles = getSampleStyleSheet()
        normal_style = ParagraphStyle('ThaiNormal',
                                     parent=styles['Normal'],
                                     fontName=self.thai_font,
                                     fontSize=font_sz,
                                     leading=font_leading,
                                     alignment=TA_LEFT)
        normal_center = ParagraphStyle('ThaiCenter',
                                       parent=normal_style,
                                       alignment=TA_CENTER)
        company_left_style = ParagraphStyle('CompanyLeft',
                                            parent=styles['Normal'],
                                            fontName=self.thai_font_bold,
                                            fontSize=font_sz,
                                            leading=font_leading,
                                            alignment=TA_LEFT)
        company_right_style = ParagraphStyle('CompanyRight',
                                             parent=styles['Normal'],
                                             fontName=self.thai_font_bold,
                                             fontSize=font_sz,
                                             leading=font_leading,
                                             alignment=TA_RIGHT)

        # === HEADER ===
        company_address_formatted = company.address.replace(' เขต', '<br/>เขต')
        header_data = [[
            Paragraph(f"<b>{company.name}</b><br/>{company_address_formatted}<br/>โทรศัพท์ {company.phone}", company_left_style),
            Paragraph("ใบกํากับภาษี(อย่างย่อ)<br/>ใบส่งสินค้า /ใบเสร็จรับเงิน<br/>เลขประจําตัวผู้เสียภาษี {tax_id}<br/>(เอกสารออกเป็นชุด)".format(tax_id=company.tax_id), company_right_style)
        ]]
        half_w = W / 2
        header_table = Table(header_data, colWidths=[half_w, half_w])
        header_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),]))
        story.append(header_table)
        story.append(Spacer(1, spacer_sm))

        # === CUSTOMER & ORDER INFO ===
        info_left_w = W * 0.58
        info_right_w = W * 0.42
        info_data = [
            [Paragraph(f"ลูกค้า: {invoice.customer.name}", normal_style), f"วันที่: {invoice.order_date}"],
            [Paragraph(f"ที่อยู่: {invoice.customer.address}", normal_style), f"เลขที่ใบสั่งซื้อ: {invoice.order_id}"],
            [f"โทรศัพท์: {invoice.customer.phone}", f"เลขที่บิล: {invoice.bill_number}"]
        ]
        info_table = Table(info_data, colWidths=[info_left_w, info_right_w])
        info_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('FONTNAME', (0, 0), (-1, -1), self.thai_font),
            ('FONTSIZE', (0, 0), (-1, -1), font_sz),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 2*mm),
            ('RIGHTPADDING', (0, 0), (-1, -1), 2*mm),
            ('TOPPADDING', (0, 0), (-1, -1), cell_pad_sm),
            ('BOTTOMPADDING', (0, 0), (-1, -1), cell_pad_sm),
        ]))
        story.append(info_table)
        story.append(Spacer(1, spacer_sm))

        # === ITEMS TABLE ===
        col_num_w = W * 0.07
        col_desc_w = W * 0.47
        col_qty_w = W * 0.12
        col_price_w = W * 0.17
        col_total_w = W * 0.17
        item_desc_style = ParagraphStyle('ItemDesc', parent=normal_style, fontSize=item_font_sz, leading=item_leading)

        items_data = [['ลําดับ', 'รายละเอียดสินค้า', 'จํานวน', 'ราคา/หน่วย', 'จํานวนเงิน']]
        for i, item in enumerate(invoice.items, 1):
            items_data.append([
                str(i),
                Paragraph(item.description, item_desc_style),
                f"{item.quantity:.2f}",
                f"{item.unit_price:.2f}",
                f"{item.total:.2f}"
            ])

        # Add empty rows for aesthetics: 6 for landscape, 8 for portrait
        max_item_rows = 6 if is_landscape else 8
        for _ in range(max(0, max_item_rows - len(invoice.items))):
            items_data.append(['', '', '', '', ''])

        items_table = Table(items_data, colWidths=[col_num_w, col_desc_w, col_qty_w, col_price_w, col_total_w], rowHeights=None)
        items_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
            ('FONTNAME', (0, 0), (-1, -1), self.thai_font),
            ('FONTSIZE', (0, 0), (-1, -1), font_sz),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('ALIGN', (0, 1), (0, -1), 'CENTER'),
            ('ALIGN', (2, 1), (2, -1), 'CENTER'),
            ('ALIGN', (3, 1), (4, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), cell_pad),
            ('BOTTOMPADDING', (0, 0), (-1, -1), cell_pad),
        ]))
        story.append(items_table)
        story.append(Spacer(1, spacer_sm))

        # === TOTALS & SIGNATURES ===
        if is_landscape:
            # Landscape: place totals and signatures SIDE BY SIDE
            totals_label_w = W * 0.22
            totals_val_w = W * 0.12

            totals_data = [
                ['ส่วนลด', f"{invoice.discount:.2f}"],
                ['ค่าจัดส่ง', f"{invoice.shipping:.2f}"],
                ['รวมจํานวนเงิน', f"{invoice.calculate_grand_total():.2f}"],
                ['ราคาก่อนภาษีมูลค่าเพิ่ม', f"{invoice.calculate_total_before_vat():.2f}"],
                [f'ภาษีมูลค่าเพิ่ม {invoice.vat_rate*100:.0f}%', f"{invoice.calculate_vat():.2f}"],
            ]

            totals_table = Table(totals_data, colWidths=[totals_label_w, totals_val_w])
            totals_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), self.thai_font),
                ('FONTSIZE', (0, 0), (-1, -1), 6.5),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('LINEABOVE', (0, -1), (-1, -1), 1, colors.black),
                ('FONTNAME', (0, -1), (-1, -1), self.thai_font_bold),
                ('TOPPADDING', (0, 0), (-1, -1), 0.5*mm),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0.5*mm),
            ]))

            # Compact signatures for landscape
            sig_compact_style = ParagraphStyle('SigCompact',
                                               parent=normal_center,
                                               fontSize=6.5,
                                               leading=8)
            sig_w = W * 0.20
            signature_data = [[
                Paragraph("<b>ผู้จัดทํา</b><br/><br/><br/><br/><br/><br/>________________<br/>วันที่ ________", sig_compact_style),
                Paragraph(f"<b>ผู้รับสินค้า</b><br/>Tracking:<br/>{invoice.tracking_number}<br/><br/><br/><br/>________________<br/>วันที่ ________", sig_compact_style),
                Paragraph("<b>ผู้รับเงิน</b><br/><br/><br/><br/><br/><br/>________________<br/>วันที่ ________", sig_compact_style),
            ]]
            signature_table = Table(signature_data, colWidths=[sig_w, sig_w, sig_w])
            signature_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ]))

            # Combine signatures (left) and totals (right) in one row
            bottom_table = Table([[signature_table, totals_table]],
                                colWidths=[W * 0.60, W * 0.40])
            bottom_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ]))
            story.append(bottom_table)
        else:
            # Portrait: side-by-side layout (signatures left, totals right)
            totals_label_w = W * 0.25
            totals_val_w = W * 0.15
            totals_data = [
                ['ส่วนลด', f"{invoice.discount:.2f}"],
                ['ค่าจัดส่ง', f"{invoice.shipping:.2f}"],
                ['รวมจํานวนเงิน', f"{invoice.calculate_grand_total():.2f}"],
                ['ราคาก่อนภาษีมูลค่าเพิ่ม', f"{invoice.calculate_total_before_vat():.2f}"],
                [f'ภาษีมูลค่าเพิ่ม {invoice.vat_rate*100:.0f}%', f"{invoice.calculate_vat():.2f}"],
            ]
            totals_table = Table(totals_data, colWidths=[totals_label_w, totals_val_w])
            totals_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), self.thai_font),
                ('FONTSIZE', (0, 0), (-1, -1), 7),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('LINEABOVE', (0, -1), (-1, -1), 1, colors.black),
                ('FONTNAME', (0, -1), (-1, -1), self.thai_font_bold),
                ('TOPPADDING', (0, 0), (-1, -1), 1*mm),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 1*mm),
            ]))

            # Signatures - aligned: middle has 1 fewer blank to compensate for Tracking line
            sig_w = W * 0.19
            sig_style = ParagraphStyle('SigPortrait', parent=normal_center, fontSize=7, leading=9.5)
            signature_data = [[
                Paragraph("<b>ผู้จัดทํา</b><br/><br/><br/><br/>__________________<br/>วันที่ __________", sig_style),
                Paragraph(f"<b>ผู้รับสินค้า</b><br/>Tracking:<br/>{invoice.tracking_number}<br/><br/>__________________<br/>วันที่ __________", sig_style),
                Paragraph("<b>ผู้รับเงิน</b><br/><br/><br/><br/>__________________<br/>วันที่ __________", sig_style),
            ]]
            signature_table = Table(signature_data, colWidths=[sig_w, sig_w, sig_w])
            signature_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),]))

            # Combine signatures (left) and totals (right) in one row
            bottom_table = Table([[signature_table, totals_table]],
                                colWidths=[W * 0.58, W * 0.42])
            bottom_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ]))
            story.append(bottom_table)

        return story
    
    
    def generate_batch_bills(self, invoices: List[Invoice], company: CompanyInfo,
                            paper_size: str = 'A5', orientation: str = 'portrait',
                            starting_bill_number: int = 2600001,
                            progress_callback=None) -> List[str]:
        """Generate single PDF with multiple pages for all bills
        
        Args:
            invoices: List of invoices to generate
            company: Company information
            paper_size: 'A4', 'A5', or 'Letter' (default: 'A5')
            orientation: 'portrait' or 'landscape' (default: 'portrait')
            starting_bill_number: Starting bill number (default: 2600001)
            progress_callback: Optional callback function for progress updates
            
        Returns:
            List with single PDF path containing all bills
        """
        # Create single output file with timestamp to avoid caching
        timestamp = int(time.time())
        output_filename = f"all_bills_{starting_bill_number}_{timestamp}.pdf"
        output_path = os.path.join(self.output_dir, output_filename)
        
        # Get page size
        page_size = self._get_page_size(paper_size, orientation)
        
        # Adjust margins based on orientation (match generate_single_bill)
        if orientation == 'landscape':
            margin = 4*mm
            top_margin = 3*mm
            bottom_margin = 2*mm
        else:
            margin = 8*mm
            top_margin = margin
            bottom_margin = 3*mm
        
        # Create PDF document
        doc = SimpleDocTemplate(output_path, pagesize=page_size,
                               topMargin=top_margin, bottomMargin=bottom_margin,
                               leftMargin=margin, rightMargin=margin)
        
        # All stories (pages) will be combined
        all_stories = []
        total = len(invoices)
        current_bill_number = starting_bill_number
        
        for i, invoice in enumerate(invoices, 1):
            try:
                # Assign bill number to this invoice
                invoice.bill_number = str(current_bill_number)
                current_bill_number += 1
                
                # Generate page content for this invoice
                story = self._generate_bill_content(invoice, company, page_size, orientation)
                all_stories.extend(story)
                
                # Add page break after each bill except the last
                if i < total:
                    from reportlab.platypus import PageBreak
                    all_stories.append(PageBreak())
                
                if progress_callback:
                    progress_callback(i, total, invoice.invoice_number)
                    
            except Exception as e:
                print(f"Warning: Failed to generate bill for invoice {invoice.invoice_number}: {e}")
                import traceback
                traceback.print_exc()
                continue

        if not all_stories:
            raise ValueError("No bills could be generated - all invoices failed to process")

        # Build single PDF with all pages
        doc.build(all_stories)
        
        return [output_path]
