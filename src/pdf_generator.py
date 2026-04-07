"""
PDF Generator for bills using xhtml2pdf
"""
import os
from xhtml2pdf import pisa
from jinja2 import Environment, FileSystemLoader
from typing import List
from .bill_data import Invoice, CompanyInfo


class PDFGenerator:
    """Generate PDF bills from invoices"""
    
    def __init__(self, template_dir: str, static_dir: str, output_dir: str):
        self.template_dir = template_dir
        self.static_dir = static_dir
        self.output_dir = output_dir
        
        # Setup Jinja2 environment
        self.env = Environment(loader=FileSystemLoader(template_dir))
        
        # Ensure output directory exists
        os.makedirs(output_dir, exist_ok=True)
    
    def generate_bill_html(self, invoice: Invoice, company: CompanyInfo) -> str:
        """Generate HTML from template"""
        template = self.env.get_template('bill_template.html')
        
        # Render template with data - no need for url_for in PDF context
        html_content = template.render(
            invoice=invoice,
            company=company,
            url_for=lambda *args, **kwargs: ''  # Dummy url_for for template
        )
        
        # Embed CSS directly
        css_path = os.path.join(self.static_dir, 'css', 'bill.css')
        if os.path.exists(css_path):
            with open(css_path, 'r', encoding='utf-8') as f:
                css_content = f.read()
            # Insert CSS into HTML
            html_content = html_content.replace('</head>', f'<style>{css_content}</style></head>')
        
        return html_content
    
    def html_to_pdf(self, html_content: str, output_path: str) -> bool:
        """Convert HTML to PDF using xhtml2pdf"""
        try:
            with open(output_path, 'wb') as pdf_file:
                # Convert HTML to PDF
                pisa_status = pisa.CreatePDF(
                    html_content.encode('utf-8'),
                    dest=pdf_file,
                    encoding='utf-8'
                )
                
                return not pisa_status.err
        except Exception as e:
            print(f"Error generating PDF: {e}")
            return False
    
    def generate_single_bill(self, invoice: Invoice, company: CompanyInfo) -> str:
        """Generate a single bill PDF"""
        # Generate HTML
        html_content = self.generate_bill_html(invoice, company)
        
        # Create output filename
        safe_invoice_num = invoice.invoice_number.replace('/', '_').replace('\\', '_')
        output_filename = f"bill_{safe_invoice_num}.pdf"
        output_path = os.path.join(self.output_dir, output_filename)
        
        # Convert to PDF
        success = self.html_to_pdf(html_content, output_path)
        
        if success:
            return output_path
        else:
            raise Exception(f"Failed to generate PDF for invoice {invoice.invoice_number}")
    
    def generate_batch_bills(self, invoices: List[Invoice], company: CompanyInfo, 
                            progress_callback=None) -> List[str]:
        """Generate multiple bill PDFs"""
        output_files = []
        total = len(invoices)
        
        for i, invoice in enumerate(invoices, 1):
            try:
                output_path = self.generate_single_bill(invoice, company)
                output_files.append(output_path)
                
                if progress_callback:
                    progress_callback(i, total, invoice.invoice_number)
                    
            except Exception as e:
                print(f"Warning: Failed to generate bill for invoice {invoice.invoice_number}: {e}")
                continue
        
        return output_files
