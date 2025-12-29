# Quick Start Guide

Get up and running with the Dutch Tax Agent in 5 minutes.

## Step 1: Set Up Environment Variables

Create a `.env` file in the project root:

```bash
# OpenAI Configuration (REQUIRED)
OPENAI_API_KEY=sk-your-openai-key-here
OPENAI_MODEL=gpt-4o-mini

# LangSmith Configuration (OPTIONAL - for tracing/debugging)
LANGSMITH_API_KEY=ls-your-key-here
LANGSMITH_PROJECT=dutch-tax-agent
LANGSMITH_TRACING=true
# For EU region, use: https://eu.smith.langchain.com
# Leave empty for US region (default)
LANGSMITH_ENDPOINT=https://eu.smith.langchain.com

# Application Configuration (OPTIONAL - defaults shown)
LOG_LEVEL=INFO
MAX_DOCUMENT_SIZE_MB=10
PDF_MIN_CHARS=50
SUPPORTED_TAX_YEARS=2022,2023,2024,2025
```

## Step 2: Install Dependencies

```bash
# Install using uv (already done if you see this file!)
uv sync

# Or if you need to reinstall
uv sync --reinstall
```

## Step 3: Configure PII Scrubbing

Before processing documents, you must configure which names and addresses to scrub. **This data never leaves your local machine and is never shared with LLMs or external services.**

### Configure Names

```bash
# Copy the example template
cp src/dutch_tax_agent/data/pii_names.json.example src/dutch_tax_agent/data/pii_names.json

# Edit with your actual names
# See docs/README.md for format details
```

### Configure Addresses

```bash
# Copy the example template
cp src/dutch_tax_agent/data/pii_addresses.json.example src/dutch_tax_agent/data/pii_addresses.json

# Edit with your actual addresses
# See docs/README.md for format details
```

**⚠️ Security Note**: 
- Never commit `pii_names.json` or `pii_addresses.json` to git. They contain sensitive PII.
- These files are processed **only on your local machine** and are never sent to LLMs or external services.
- Addresses are only scrubbed if explicitly listed in `pii_addresses.json` (whitelist approach to prevent false positives).

## Step 4: Prepare Your Documents

Place your PDF tax documents in the `sample_docs/` directory:

```bash
# Example documents you might have:
sample_docs/
├── ing_bank_statement_jan2024.pdf
├── us_broker_statement_2024.pdf
├── rev_savings_eur.pdf          # Revolut statement PDF
├── rev_savings_eur.csv          # Revolut transaction CSV (optional, merges with PDF)
├── salary_jan_2024.pdf
└── salary_feb_2024.pdf
```

### Broker Statement Requirements

For broker statements (US brokerage or crypto exchange), you have two options:

1. **Full Year Statement** (Recommended): Add the complete annual statement for the tax year. This statement should cover the entire tax year and show both January 1 and December 31 values.

2. **Monthly Statements** (If annual not available): If only monthly statements are available, add:
   - The **December statement from the previous tax year** (e.g., Dec 2023 for tax year 2024) - provides the January 1 value
   - The **December statement of the tax year** (e.g., Dec 2024 for tax year 2024) - provides the December 31 value

**Example for tax year 2024:**
- Option 1: `broker_statement_2024.pdf` (full year)
- Option 2: `broker_statement_dec2023.pdf` + `broker_statement_dec2024.pdf` (monthly)

**⚠️ Security Note**: Never commit real financial documents to git. The `sample_docs/` directory is gitignored.

### Revolut Statement Processing

For Revolut Flexible Cash Funds statements, you can provide:
- **PDF Statement**: Contains opening/closing balances and period information
- **CSV Transaction File** (optional): Contains transaction details for actual return calculation

Files are automatically matched by name (case-insensitive). For example:
- `rev_savings_eur.pdf` + `rev_savings_eur.csv` → Merged into single asset
- The PDF provides Jan 1 and Dec 31 balances
- The CSV provides deposits, withdrawals, gains, and losses
- Actual return is calculated automatically when both files are present

See the main [README.md](../README.md) for detailed information about Revolut statement processing.

## Step 5: Run the Agent

### Option A: Using the CLI

```bash
# Process documents in sample_docs/ for tax year 2024
uv run python -m dutch_tax_agent.cli process

# Specify custom directory and year
uv run python -m dutch_tax_agent.cli process --input-dir ~/Documents/taxes_2024 --year 2024

# Disable fiscal partner optimization (single taxpayer)
uv run python -m dutch_tax_agent.cli process --input-dir ~/Documents/taxes_2024 --no-fiscal-partner

# Show version
uv run python -m dutch_tax_agent.cli version
```

### Option B: As a Python Library

```python
from pathlib import Path
from dutch_tax_agent import DutchTaxAgent

# Create agent (fiscal partner assumed by default)
agent = DutchTaxAgent(tax_year=2024)

# Or disable fiscal partner
# agent = DutchTaxAgent(tax_year=2024, has_fiscal_partner=False)

# Ingest documents (creates new thread)
pdf_files = [
    Path("sample_docs/bank_statement.pdf"),
    Path("sample_docs/salary.pdf"),
]

state = agent.ingest_documents(pdf_files, is_initial=True)

# View status
status = agent.get_status()
print(f"Box 1 Total: €{status['box1_total']:,.2f}")
print(f"Box 3 Total: €{status['box3_total']:,.2f}")

# Calculate taxes
final_state = agent.calculate_taxes()
```

## Step 6: Understanding the Output

The agent will display:

### Phase 1: Document Ingestion
- ✓ Parsed X documents
- ✓ Scrubbed PII from X documents

### Phase 2: LangGraph Processing
- Documents are classified and routed to specialized parser agents
- Data is extracted, validated, and currency-normalized
- Results are aggregated

### Phase 3: Box 3 Calculations
- **Statutory Calculation**: Savings Variant (2023-2025) or Legacy (2022)
- **Fiscal Partner Optimization**: Allocates assets to maximize tax credits
- **Actual Return Method**: Hoge Raad method (includes unrealized gains)
- **Comparison**: Shows potential tax savings between methods

### Example Output

```
📊 Tax Processing Results

Box 1: Income from Employment
Total Income: €54,000.00
Items: 12

Box 3: Wealth (Jan 1, 2024)
Total Assets: €125,000.00
Items: 3

Box 3 Tax Comparison

Method A: Statutory Calculation (Savings Variant)
  Deemed Income: €3,245.00
  Tax Owed: €1,168.20
  (Optimized for fiscal partner: €1,050.00)

Method B: Actual Return (Hoge Raad Method)
  Actual Gains: €2,650.00
  Tax Owed: €954.00

💰 Potential Savings: €214.20

Recommendation:
The actual return method results in €214.20 less tax. 
Consider using this method if you have proper documentation 
of realized gains from your bank and broker statements.
Note: Fiscal partner optimization saved an additional €118.20.
```

## Testing the Installation

Run the test suite to verify everything works:

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=dutch_tax_agent

# Run specific test file
uv run pytest tests/unit/test_bsn_recognizer.py -v
```

## Troubleshooting

### "No module named 'dutch_tax_agent'"
- Make sure you're in the project root directory
- Run `uv sync` to install the package

### "OPENAI_API_KEY not found"
- Create a `.env` file with your OpenAI API key
- Ensure it's in the project root directory

### "No PDF files found"
- Check that your PDFs are in the correct directory
- Verify files have `.pdf` extension (lowercase)

### "Extracted text too short"
- The PDF might be a scanned image (OCR not supported)
- Try re-exporting the PDF with selectable text

## Next Steps

- Read the [full documentation](README.md)
- Review the [architecture diagram](docs/architecture.md)
- Check out the [test examples](tests/)
- Customize the parser agents for your specific document formats

## Need Help?

This is a demonstration project. For production use:
1. Review all security configurations
2. Add proper error handling for your use case
3. Implement data retention policies
4. Consider adding OCR support if needed
5. Validate Box 3 calculations with a tax advisor

