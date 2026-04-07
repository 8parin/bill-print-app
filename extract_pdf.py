#!/usr/bin/env python3
"""
Quick script to extract text from the sample bill PDF
"""
import sys

try:
    import PyPDF2
    
    pdf_path = "sample_bill.pdf"
    
    with open(pdf_path, 'rb') as f:
        reader = PyPDF2.PdfReader(f)
        print(f"Total pages: {len(reader.pages)}\n")
        print("=" * 80)
        
        for i, page in enumerate(reader.pages, 1):
            print(f"\n--- PAGE {i} ---\n")
            text = page.extract_text()
            print(text)
            print("\n" + "=" * 80)
            
except ImportError:
    print("PyPDF2 is not installed.")
    print("Installing PyPDF2...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "PyPDF2"])
    print("\nPlease run this script again.")
