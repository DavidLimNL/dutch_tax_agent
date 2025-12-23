# Sample Documents

Place your PDF tax documents in this directory for processing.

## Supported Document Types

- **Dutch Bank Statements**: ING, ABN AMRO, Rabobank, etc.
- **US Brokerage Statements**: Interactive Brokers, Charles Schwab, etc.
- **Crypto Exchange Statements**: Coinbase, Binance, Kraken, etc.
- **Salary Statements**: Dutch payslips (salarisstroken)
- **Mortgage Statements**: Property-related documents

### Broker Statement Requirements

For broker statements (US brokerage or crypto exchange), you have two options:

1. **Full Year Statement** (Recommended): Add the complete annual statement for the tax year. This statement should cover the entire tax year and show both January 1 and December 31 values.

2. **Monthly Statements** (If annual not available): If only monthly statements are available, add:
   - The **December statement from the previous tax year** (e.g., Dec 2023 for tax year 2024) - provides the January 1 value
   - The **December statement of the tax year** (e.g., Dec 2024 for tax year 2024) - provides the December 31 value

**Example for tax year 2024:**
- Option 1: `broker_statement_2024.pdf` (full year)
- Option 2: `broker_statement_dec2023.pdf` + `broker_statement_dec2024.pdf` (monthly)

## Security

⚠️ **IMPORTANT**: Files in this directory are gitignored for security reasons.

- Never commit real financial documents
- PII will be scrubbed during processing, but source files remain untouched
- For testing, use synthetic/dummy documents

## Example Usage

```bash
# Place your PDFs here
cp ~/Downloads/bank_statement_2024.pdf sample_docs/
cp ~/Downloads/salary_jan_2024.pdf sample_docs/

# Run the agent
uv run python -m dutch_tax_agent.main --input-dir sample_docs
```

