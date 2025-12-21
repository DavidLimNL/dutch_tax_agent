# Dutch Tax Agent 🇳🇱

> **Zero-Trust AI Tax Assistant for Dutch Personal Income Tax (Box 1 & Box 3)**

A production-grade LangGraph application that automates Dutch tax filing while adhering to strict PII governance and legal compliance requirements.

## 🎯 Key Features

- **Zero-Trust Data Policy**: PII is scrubbed before any LLM processing
- **Parallel Document Processing**: Uses LangGraph's `Send` API for concurrent parsing
- **Legal Compliance**: Handles Box 3 ambiguity by calculating both methods
- **Deterministic Math**: All calculations done with Python tools, not LLM tokens
- **Audit Trail**: Every extracted value links back to source documents

## 🏗️ Architecture

```mermaid
graph TD
    subgraph "Phase 1: The Safe Zone (Local Execution)"
        User[User Upload] -->|PDFs| Ingest[Ingestion Controller]
        Ingest -->|Binary Stream| Parser[PDFPlumber]
        Parser -->|Raw Text| PII[Presidio Scrubber]
        PII -->|Scrubbed Text| SafeData[Clean Document List]
    end

    subgraph "Phase 2: The Graph (LangGraph Map-Reduce)"
        SafeData --> Dispatcher{Dispatcher Node}
        
        Dispatcher -->|Send Doc A| DutchAgent[Dutch Parser Agent]
        Dispatcher -->|Send Doc B| USAgent[US Broker Agent]
        Dispatcher -->|Send Doc C| SalaryAgent[Income Agent]
        
        DutchAgent --> ValidatorA[Validator & Currency Tool]
        USAgent --> ValidatorB[Validator & Currency Tool]
        SalaryAgent --> ValidatorC[Validator & Currency Tool]
        
        ValidatorA --> Aggregate[Aggregator Node]
        ValidatorB --> Aggregate
        ValidatorC --> Aggregate
        
        Aggregate --> Reducer[Reducer Node]
    end

    subgraph "Phase 3: Box 3 Calculation & Optimization"
        Reducer -->|Command: routes based on validation| Check{Reducer Routing}
        
        Check -->|Quarantine or No Assets| End1[END - Skip Box 3]
        
        Check -->|Valid & Has Assets| StartBox3[Start Box 3]
        
        StartBox3 --> Statutory[Statutory Calculation<br/>Savings Variant / Legacy]
        StartBox3 --> Actual[Actual Return<br/>Hoge Raad Method]
        
        Statutory --> Optimize[Fiscal Partner<br/>Optimization]
        Actual --> Compare[Comparison Node]
        Optimize --> Compare
        Compare --> End2[END - Final State]
    end
```

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- `uv` package manager

### Installation

```bash
# Install dependencies
uv sync

# Set up environment variables
cp .env.example .env
# Edit .env with your API keys
```

### Run the Agent

```bash
# Process tax documents (fiscal partner assumed by default)
uv run python -m dutch_tax_agent.main --input-dir ./sample_docs

# Disable fiscal partner optimization
uv run python -m dutch_tax_agent.main --input-dir ./sample_docs --no-fiscal-partner

# Interactive mode
uv run python -m dutch_tax_agent.cli process --input-dir ./sample_docs

# With fiscal partner disabled
uv run python -m dutch_tax_agent.cli process --input-dir ./sample_docs --no-fiscal-partner
```

## 📁 Project Structure

```
dutch_tax_agent/
├── src/
│   └── dutch_tax_agent/
│       ├── __init__.py
│       ├── main.py                    # Entry point
│       ├── config.py                  # Configuration
│       ├── schemas/                   # Pydantic models
│       │   ├── state.py               # Graph state definitions
│       │   ├── documents.py           # Document schemas
│       │   └── tax_entities.py        # Tax-specific models
│       ├── ingestion/                 # Phase 1: Safe Zone
│       │   ├── pdf_parser.py          # PDFPlumber logic
│       │   ├── pii_scrubber.py        # Presidio + custom recognizers
│       │   └── recognizers/           # Custom PII recognizers
│       │       ├── bsn_recognizer.py  # 11-proef implementation
│       │       ├── iban_recognizer.py
│       │       └── dob_recognizer.py
│       ├── graph/                     # LangGraph orchestration
│       │   ├── main_graph.py          # Graph construction only
│       │   ├── nodes/                 # Graph nodes (self-contained)
│       │   │   ├── dispatcher.py      # Document router
│       │   │   ├── aggregator.py      # Aggregation & Box 3 trigger
│       │   │   ├── reducer.py         # Totals & validation
│       │   │   ├── validators.py      # Data validation
│       │   │   └── box3/             # Box 3 calculation nodes
│       │   │       ├── statutory_calculation.py  # Savings Variant / Legacy method
│       │   │       ├── actual_return.py          # Hoge Raad actual return method
│       │   │       ├── optimization.py         # Fiscal partner optimization
│       │   │       ├── comparison.py             # Method comparison
│       │   │       └── start_box3.py             # Box 3 entry point
│       │   └── agents/                # LLM-based parser agents
│       │       ├── dutch_parser.py
│       │       ├── us_broker_parser.py
│       │       └── salary_parser.py
│       ├── tools/                     # Deterministic tools
│       │   ├── currency.py            # ECB rate fetching
│       │   ├── tax_credits.py         # General Tax Credit (AHK) calculation
│       │   └── validators.py          # Type checking
│       └── data/
│           ├── box3_rates_2022_2025.json  # Box 3 rates (Savings Variant + Legacy)
│           └── pii_names.json.example     # Template for PII names (see Security section)
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│       └── synthetic_pdfs/            # Test documents
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```

## 🔒 Security & Privacy

- **No PII in LLM**: BSN (including "citizen service number"), names, IBANs, addresses, phone numbers, and emails are scrubbed using Presidio before any LLM call
- **Zero-Trust Enforcement**: Documents that fail PII scrubbing are excluded from processing (not passed through with unredacted PII)
- **Custom 11-proef**: Validates Dutch BSN using official checksum algorithm
- **Custom Name Recognition**: Configurable name scrubbing from `pii_names.json` that handles:
  - Full names (with/without spaces, concatenated)
  - First + Last name combinations
  - Individual name parts
  - **Reversed/inverted names** (e.g., "JOHNDOE" → "EODNHOJ")
  - Case-insensitive matching
- **Audit Trail**: Every extraction is linked to `source_doc_id` and page number
- **Deterministic Math**: Currency conversion and tax calculations use Python tools only

### Setting Up PII Name Recognition

The system uses a configuration file to recognize and scrub personal names. **This file is gitignored for security reasons.**

1. Copy the example template:
   ```bash
   cp src/dutch_tax_agent/data/pii_names.json.example src/dutch_tax_agent/data/pii_names.json
   ```

2. Edit `pii_names.json` with your actual name(s):
   ```json
   {
     "names": [
       {
         "first": "JOHN",
         "last": "DOE",
         "middle": null,
         "full_name": "JOHN DOE"
       }
     ]
   }
   ```

3. The recognizer will automatically detect all variations including:
   - "JOHN DOE" (with space)
   - "JOHNDOE" (concatenated)
   - "EODNHOJ" (reversed)
   - "JOHN" or "DOE" (individual parts)
   - All case variations

**⚠️ Important**: Never commit `pii_names.json` to git. It contains sensitive PII.

## 📊 Box 3 Wealth Tax Logic

The system handles the legal complexity of Dutch Box 3 (2022-2025) by implementing multiple calculation methods:

### Calculation Methods

1. **Statutory Calculation (Savings Variant)**: 
   - Standard method for 2023-2025
   - Categorizes assets into Savings, Other Assets (stocks/ETFs/crypto), and Debts
   - Applies fictitious yield rates per category
   - For 2022: Also calculates Legacy (bracket-based) method and selects the lower tax

2. **Actual Return (Hoge Raad Method)**:
   - Rebuttal scheme based on Supreme Court rulings (June 2024)
   - Includes unrealized capital gains ("paper gains")
   - Formula: Direct Returns + (Value_End - Value_Start - Deposits + Withdrawals)
   - Tax-free allowance is NOT used in this calculation (only in comparison)

3. **Fiscal Partner Optimization**:
   - Automatically allocates Box 3 assets between partners to maximize tax credits
   - Utilizes the non-working partner's General Tax Credit (AHK)
   - Critical for partners born after 1963 (no transferability)

The comparison agent presents both statutory and actual return methods with recommendations, showing potential savings.

## 🧪 Testing

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=dutch_tax_agent

# Test with synthetic data
uv run pytest tests/integration/test_end_to_end.py
```

## 📝 Configuration

### Environment Variables

Key environment variables:

- `OPENAI_API_KEY`: For LLM calls
- `LANGSMITH_API_KEY`: For tracing (optional)
- `LANGSMITH_ENDPOINT`: LangSmith endpoint URL (e.g., `https://eu.smith.langchain.com` for EU region)
- `ECB_API_KEY`: For currency rates (optional, falls back to cached rates)

### Fiscal Partner Configuration

By default, the system assumes a fiscal partnership (enables optimization). To disable:

```bash
# CLI flag
--no-fiscal-partner

# Or in code
agent = DutchTaxAgent(tax_year=2024, has_fiscal_partner=False)
```

The default fiscal partner configuration:
- Date of birth: 1970-01-01 (born after 1963 threshold)
- Box 1 income: €0 (non-working partner)
- Enables Box 3 asset allocation optimization

### PII Name Configuration

See the [Security & Privacy](#-security--privacy) section above for setting up `pii_names.json`.

## 🛠️ Development

```bash
# Install dev dependencies
uv add --dev pytest pytest-cov ruff mypy

# Lint
uv run ruff check .

# Type check
uv run mypy src/

# Format
uv run ruff format .
```

## 📄 License

MIT License - This is a demonstration project for educational purposes.

## ⚠️ Disclaimer

This is a **demonstration project** and should not be used for actual tax filing without proper legal review and compliance validation.

