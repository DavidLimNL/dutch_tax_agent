# Test Fixtures

This directory contains synthetic test data for integration testing.

## Synthetic PDFs

To create synthetic test PDFs, you can use tools like:

- **reportlab** (Python): Generate PDFs programmatically
- **wkhtmltopdf**: Convert HTML to PDF
- **LibreOffice**: Export documents to PDF

### Example: Create a synthetic Dutch bank statement

```python
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

def create_test_bank_statement(filename):
    c = canvas.Canvas(filename, pagesize=A4)
    
    c.setFont("Helvetica-Bold", 16)
    c.drawString(100, 750, "ING Bank Statement")
    
    c.setFont("Helvetica", 12)
    c.drawString(100, 700, "Datum: 01-01-2024")
    c.drawString(100, 680, "Rekeningnummer: NL91ABNA0417164300")
    c.drawString(100, 650, "Saldo per 1 januari 2024: EUR 45,000.00")
    
    c.save()

create_test_bank_statement("synthetic_dutch_bank.pdf")
```

## Security Note

**NEVER** commit real tax documents or PDFs containing actual PII to this repository.


