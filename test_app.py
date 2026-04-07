"""
Quick test script to verify CSV parsing and PDF generation
"""
import sys
sys.path.insert(0, '/Users/parin/Library/Mobile Documents/com~apple~CloudDocs/VS_Code/Bill_Print')

from src.csv_parser import CSVParser
from src.pdf_generator import PDFGenerator
from src.bill_data import CompanyInfo
import json
import os

# Load config
with open('/Users/parin/Library/Mobile Documents/com~apple~CloudDocs/VS_Code/Bill_Print/config.json', 'r', encoding='utf-8') as f:
    config = json.load(f)

# Company info
company = CompanyInfo(
    name=config['company']['name'],
    tax_id=config['company']['tax_id'],
    address=config['company']['address'],
    phone=config['company']['phone'],
    branch_code=config['company'].get('branch_code', ''),
    branch_address=config['company'].get('branch_address', '')
)

# Test CSV parsing
print("Testing CSV Parser...")
csv_path = '/Users/parin/Library/Mobile Documents/com~apple~CloudDocs/VS_Code/Bill_Print/test2.csv'
parser = CSVParser(vat_rate=0.07)

try:
    invoices = parser.parse_csv_to_invoices(csv_path)
    print(f"✅ Successfully parsed {len(invoices)} invoices")
    
    # Show first invoice details
    if invoices:
        inv = invoices[0]
        print(f"\nFirst Invoice:")
        print(f"  Number: {inv.invoice_number}")
        print(f"  Customer: {inv.customer.name}")
        print(f"  Items: {len(inv.items)}")
        print(f"  Total: {inv.grand_total:.2f}")
        
        # Test PDF generation for first invoice only
        print("\nTesting PDF Generation (first invoice only)...")
        template_dir = '/Users/parin/Library/Mobile Documents/com~apple~CloudDocs/VS_Code/Bill_Print/templates'
        static_dir = '/Users/parin/Library/Mobile Documents/com~apple~CloudDocs/VS_Code/Bill_Print/static'
        output_dir = '/Users/parin/Library/Mobile Documents/com~apple~CloudDocs/VS_Code/Bill_Print/output/bills'
        
        generator = PDFGenerator(template_dir, static_dir, output_dir)
        
        # Generate one bill as test
        output_path = generator.generate_single_bill(invoices[0], company)
        print(f"✅ PDF generated: {output_path}")
        print(f"✅ File exists: {os.path.exists(output_path)}")
        print(f"✅ File size: {os.path.getsize(output_path)} bytes")
        
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
