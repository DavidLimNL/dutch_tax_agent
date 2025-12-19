# Sample Documents

Place your PDF tax documents in this directory for processing.

## Supported Document Types

- **Dutch Bank Statements**: ING, ABN AMRO, Rabobank, etc.
- **US Brokerage Statements**: Interactive Brokers, Charles Schwab, etc.
- **Salary Statements**: Dutch payslips (salarisstroken)
- **Mortgage Statements**: Property-related documents

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

