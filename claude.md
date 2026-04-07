# Running Batch Bill Printing Locally from ZIP

This guide helps you run the **Batch Bill Printing** webapp on your local machine after downloading the ZIP distribution.

---

## Prerequisites

Before you begin, make sure you have:

- **macOS** 10.14+ (or Windows/Linux with Python 3.8+)
- **Python 3.8 or later** installed
- ~50MB free disk space
- A printer configured for bill/invoice printing

### Check if Python is Installed

Open Terminal and run:
```bash
python3 --version
```

You should see Python 3.8 or later. If not, install Python from:
- macOS: [https://www.python.org/downloads/](https://www.python.org/downloads/)
- Or use Homebrew: `brew install python3`

---

## Installation Steps

### Step 1: Extract the ZIP File

1. Download the ZIP file (e.g., `Batch_Bill_Print_v1.0.zip`)
2. Double-click the ZIP to extract it
3. Move the extracted folder to a convenient location (e.g., Documents, Desktop)

### Step 2: Open Terminal

1. Open **Terminal** (Spotlight: Cmd+Space, type "Terminal")
2. Navigate to the extracted folder:
   ```bash
   cd /path/to/Bill_Print
   ```
   
   **Tip:** You can drag the folder from Finder into Terminal to auto-fill the path

### Step 3: Run Installation

Run the installation script:
```bash
./install.sh
```

This script will:
- ✓ Check for Python 3.8+
- ✓ Check for pip (Python package manager)
- ✓ Install required dependencies (~50MB download)
- ✓ Make scripts executable
- ✓ Create a desktop shortcut (`BatchBill.command`)
- ✓ Create necessary directories

**Installation takes 1-2 minutes** depending on your internet speed.

---

## Running the Application

You have three options to launch the app:

### Option 1: Desktop Shortcut (Easiest)

Double-click `BatchBill.command` on your Desktop

### Option 2: Launch Script

In Terminal, from the app directory:
```bash
./run.sh
```

### Option 3: Python Direct

```bash
python3 app.py
```

### What Happens When You Launch

1. The Flask web server starts (port 5003)
2. Your default browser opens automatically to `http://localhost:5003`
3. The webapp interface loads

---

## Using the Webapp

### Step 1: Upload CSV File

1. Click **"Choose CSV File"** button
2. Select your ecommerce platform CSV export file
3. The webapp will automatically detect CSV headers

### Step 2: Map CSV Columns

1. Review the detected CSV headers
2. Map each header to the corresponding bill field:
   - **Invoice Number** → Order ID / Invoice #
   - **Customer Name** → Buyer Name
   - **Customer Address** → Shipping Address
   - **Item Name** → Product Name
   - **Quantity** → Qty
   - **Price** → Unit Price
   - **Total** → Total Amount
   - **Date** → Order Date
3. Click **"Validate Mapping"**

### Step 3: Preview Bill Layout

1. View the bill template preview
2. Check data placement in the layout
3. Adjust bill template settings if needed:
   - Paper size (A4, Letter, Custom)
   - Margins
   - Font size
   - Logo placement

### Step 4: Generate & Print Bills

1. Click **"Generate Bills"**
2. Watch real-time progress as bills are generated
3. Options:
   - **Print All** - Send all bills to printer
   - **Print Selected** - Choose specific invoices
   - **Save as PDF** - Save bills to output folder
   - **Preview** - View bills before printing

### Step 5: Handle Multi-Item Invoices

The webapp automatically detects and groups multiple CSV rows by invoice number:
- Single invoice with multiple items = merged into one bill
- All line items displayed in bill table format
- Subtotals and totals calculated automatically

---

## Stopping the Application

To stop the server:

1. **In Terminal**: Press `Ctrl + C`
2. **Close browser tab** (optional)

---

## Troubleshooting

### "Permission denied" Error

Make scripts executable:
```bash
chmod +x install.sh run.sh
```

### "Python not found" Error

Install Python 3.8+ from [python.org/downloads](https://www.python.org/downloads/)

### "Port already in use" Error

Another app is using port 5003. To use a different port:

1. Open `app.py` in a text editor
2. Find the last line: `app.run(debug=True, port=5003, host='0.0.0.0')`
3. Change `5003` to another port (e.g., `5004`)
4. Save and restart the app
5. Access at `http://localhost:5004`

### Installation Fails

Try manual installation:
```bash
python3 -m pip install Flask pandas reportlab weasyprint openpyxl
```

### "Invalid CSV Format" Error

- Verify your CSV file has headers in the first row
- Check encoding is UTF-8
- Ensure no empty rows at the beginning
- Try opening CSV in Excel/Numbers to verify structure

### Printer Not Found

- Verify printer is connected and turned on
- Check printer is set as default in System Preferences
- Use "Save as PDF" option as alternative

### Multi-Item Invoices Not Grouping

- Ensure invoice/order number column is mapped correctly
- Check that invoice numbers are consistent across rows
- Verify CSV doesn't have extra spaces in invoice numbers

---

## File Structure

After extraction, your folder should look like:

```
Bill_Print/
├── app.py                    # Main Flask application
├── launcher.py               # Browser auto-launcher
├── install.sh                # Installation script
├── run.sh                    # Launch script
├── requirements.txt          # Python dependencies
├── claude.md                 # This documentation file
│
├── src/                      # Source code
│   ├── csv_parser.py         # CSV reading & mapping
│   ├── bill_generator.py     # Bill PDF generation
│   ├── printer.py            # Print management
│   └── templates/            # Bill templates
│       ├── default.html      # Default bill layout
│       └── custom.html       # Custom bill layouts
│
├── templates/                # HTML interface
│   └── index.html            # Main webapp interface
│
├── static/                   # CSS & JavaScript
│   ├── css/
│   └── js/
│
├── uploads/                  # Uploaded CSV files
├── output/                   # Generated bills (PDF)
│   └── bills/                # Individual bill PDFs
│
└── .workspace/               # Logs and temp files
    └── logs/                 # Processing logs
```

---

## Performance Expectations

- **CSV Parsing**: ~0.1 seconds per file
- **Bill Generation**: ~0.5 seconds per invoice
- **Printing**: ~2-3 seconds per bill (depends on printer)
- **100 invoices batch**:
  - Generation: ~1 minute
  - Printing: ~4-5 minutes

---

## Supported CSV Formats

The webapp supports CSV exports from:
- **Shopify**
- **WooCommerce**
- **Amazon Seller Central**
- **eBay**
- **Etsy**
- **Generic CSV** (with manual column mapping)

### Required Columns (Minimum)

At minimum, your CSV should have:
- Invoice/Order Number
- Customer Name
- Item/Product Name
- Quantity
- Price
- Date

---

## Bill Template Customization

### Adding Your Logo

1. Place your logo image in `static/img/logo.png`
2. Restart the webapp
3. Logo will appear on all bills automatically

### Changing Bill Layout

Edit `src/templates/default.html`:
- Modify HTML structure
- Adjust CSS styling
- Change field positions

### Creating Custom Templates

1. Copy `src/templates/default.html` to `src/templates/custom.html`
2. Make your changes
3. Select "Custom Template" in webapp settings

---

## Updating the Application

When a new version is released:

1. Download the new ZIP file
2. Backup your `static/img/` and custom templates
3. Extract and replace old files
4. Restore your logo and templates
5. Run `./install.sh` again to update dependencies

---

## Uninstalling

To completely remove the application:

1. Delete the `Bill_Print` folder
2. Remove desktop shortcut (`~/Desktop/BatchBill.command`)
3. (Optional) Uninstall Python packages:
   ```bash
   python3 -m pip uninstall Flask pandas reportlab weasyprint openpyxl
   ```

---

## Advanced Configuration

### Changing Default Directories

Edit paths in `app.py`:
```python
UPLOAD_FOLDER = "./uploads"
OUTPUT_FOLDER = "./output/bills"
```

### Paper Size Configuration

Available paper sizes:
- **A4** (default) - 210mm × 297mm
- **Letter** - 8.5" × 11"
- **Legal** - 8.5" × 14"
- **Custom** - Define your own dimensions

### Viewing Logs

Processing logs are saved to:
```
.workspace/logs/bill_print_YYYYMMDD_HHMMSS.log
```

Logs contain:
- CSV parsing summary
- Column mapping results
- Bill generation status
- Print job status
- Error messages

---

## Support

For issues or questions:
- Check troubleshooting section above
- Review logs in `.workspace/logs/`
- Ensure Python 3.8+ and all dependencies are installed
- Verify CSV file format is correct

---

## Quick Reference Commands

```bash
# Navigate to app folder
cd /path/to/Bill_Print

# Install dependencies
./install.sh

# Launch application
./run.sh

# Stop server
Ctrl + C

# Make scripts executable
chmod +x install.sh run.sh

# Manual dependency install
python3 -m pip install -r requirements.txt

# Check Python version
python3 --version
```

---

## Tips for Best Results

1. **Clean CSV Data**: Remove empty rows and ensure consistent formatting
2. **Test First**: Use "Save as PDF" before mass printing
3. **Preview**: Always preview the first bill to check layout
4. **Batch Size**: Print in batches of 50-100 for easier management
5. **Paper**: Use quality invoice paper for professional appearance

---

**Version**: 1.0  
**Last Updated**: 2026-02-11  
**Tested on**: macOS 14+, Python 3.8+
