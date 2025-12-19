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

## Step 3: Prepare Your Documents

Place your PDF tax documents in the `sample_docs/` directory:

```bash
# Example documents you might have:
sample_docs/
├── ing_bank_statement_jan2024.pdf
├── us_broker_statement_2024.pdf
├── salary_jan_2024.pdf
└── salary_feb_2024.pdf
```

**⚠️ Security Note**: Never commit real financial documents to git. The `sample_docs/` directory is gitignored.

## Step 4: Run the Agent

### Option A: Using the CLI

```bash
# Process documents in sample_docs/ for tax year 2024
uv run python -m dutch_tax_agent.cli process

# Specify custom directory and year
uv run python -m dutch_tax_agent.cli process --input-dir ~/Documents/taxes_2024 --year 2024

# Show version
uv run python -m dutch_tax_agent.cli version
```

### Option B: Using the Main Script

```bash
uv run python -m dutch_tax_agent.main
```

### Option C: As a Python Library

```python
from pathlib import Path
from dutch_tax_agent.main import DutchTaxAgent

# Create agent
agent = DutchTaxAgent(tax_year=2024)

# Process documents
pdf_files = [
    Path("sample_docs/bank_statement.pdf"),
    Path("sample_docs/salary.pdf"),
]

result = agent.process_documents(pdf_files)

# Access results
print(f"Box 1 Total: €{result.box1_total_income:,.2f}")
print(f"Box 3 Total: €{result.box3_total_assets_jan1:,.2f}")
```

## Step 5: Understanding the Output

The agent will display:

### Phase 1: Document Ingestion
- ✓ Parsed X documents
- ✓ Scrubbed PII from X documents

### Phase 2: LangGraph Processing
- Documents are classified and routed to specialized parser agents
- Data is extracted, validated, and currency-normalized
- Results are aggregated

### Phase 3: Box 3 Calculations
- **Fictional Yield Method**: Based on statutory rates
- **Actual Return Method**: Based on realized gains
- **Comparison**: Shows potential tax savings

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

Method A: Fictional Yield (Old Law)
  Deemed Income: €3,245.00
  Tax Owed: €1,168.20

Method B: Actual Return (New Law)
  Actual Gains: €2,650.00
  Tax Owed: €954.00

💰 Potential Savings: €214.20

Recommendation:
The actual return method results in €214.20 less tax. 
Consider using this method if you have proper documentation 
of realized gains from your bank and broker statements.
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

