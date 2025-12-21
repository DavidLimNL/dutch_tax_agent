# Architectural Design Specification: Secure Dutch Tax Agent

## 1. Executive Summary

This solution automates personal income tax filing (Box 1 & Box 3) while adhering to a **Zero-Trust Data Policy**.

* **Governance First:** We separate "Reading" (deterministic) from "Reasoning" (probabilistic). No unredacted PII (BSN, Name) ever touches the LLM or the database state.
* **Parallel Execution:** We use LangGraph's `Send` API to process multiple documents simultaneously, ensuring that one corrupt file does not crash the entire pipeline.
* **Legal Compliance:** The system models the current ambiguity in Dutch "Box 3" law by running two parallel calculation methods ("Fictional Yield" vs. "Actual Return") and letting the human decide.

## 2. System Architecture Diagram

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
        Reducer -->|Command: goto="start_box3" or END| Check{Reducer Routing}
        
        Check -->|Quarantine or No Assets| End1[END - Skip Box 3]
        
        Check -->|Valid & Has Assets| StartBox3[Start Box 3]
        
        StartBox3 --> Statutory[Statutory Calculation<br/>Savings Variant / Legacy<br/>+ Fiscal Partner Optimization]
        StartBox3 --> Actual[Actual Return<br/>Hoge Raad Method<br/>+ Fiscal Partner Optimization]
        
        Statutory --> Compare[Comparison Node]
        Actual --> Compare
        Compare --> End2[END - Final State]
    end
```

## 3. Data Flow

### Phase 1: Ingestion (Safe Zone)
1. User uploads PDFs
2. `pdfplumber` extracts text (fails if < 50 chars)
3. Presidio scrubs PII using English language recognizers:
   - **NL_BSN**: Dutch BSN (Burgerservicenummer), including "citizen service number"
   - **NL_IBAN**: Dutch IBAN numbers
   - **NL_DATE_OF_BIRTH**: Dutch date formats
   - **NL_ADDRESS**: Dutch addresses (postal codes, streets, cities)
   - **PERSON_NAME**: Custom name recognizer from `pii_names.json` (handles full names, concatenated, reversed/inverted, and case variations)
   - **PERSON**: Person names (English recognizer, fallback)
   - **EMAIL_ADDRESS**: Email addresses
   - **PHONE_NUMBER**: Phone numbers
   - **LOCATION**: Addresses and locations
4. **Zero-Trust Policy**: Documents that fail scrubbing are **excluded** (not passed through with PII)
5. Output: List of `ScrubbedDocument` objects (only successfully scrubbed documents)

### Phase 2: LangGraph Map-Reduce
1. **Dispatcher** classifies documents and returns `Command` with:
   - State update: `classified_documents`
   - Routing: `Send` objects for parallel routing to parser agents
2. **Parser Agents** extract structured data (no raw text in output)
   - Each parser returns `extraction_status` (not `status` to avoid state conflicts)
3. **Validators** normalize currency and validate types
   - Results accumulated in `state.validated_results`
4. **Aggregator** collects all validated Box1/Box3 items from `state.validated_results`
5. **Reducer** calculates totals, validates completeness, and returns `Command` with:
   - State update: totals, validation status
   - Routing: `"start_box3"` or `END` based on validation/assets

### Phase 3: Box 3 Calculation & Optimization
1. **Reducer Command Routing**: Determines if Box 3 should run
   - If quarantine or no assets → `END` (skip Box 3)
   - If valid and has assets → `"start_box3"`
2. **Start Box 3**: Triggers parallel Box 3 calculations
3. **Parallel Calculations**: Both methods run simultaneously
   - **Statutory Calculation**: 
     - Savings Variant (standard for 2023-2025): Categorizes assets into Savings, Other Assets, Debts
     - Legacy Method (2022 only): Bracket-based with assumed asset mix
     - For 2022: Automatically selects the lower tax between Legacy and Savings Variant
     - **Fiscal Partner Optimization**: Applied after calculation (if fiscal partner exists)
       - Optimizes Box 3 asset allocation between partners
       - Maximizes utilization of non-working partner's General Tax Credit (AHK)
       - Critical for partners born after 1963 (no transferability)
   - **Actual Return (Hoge Raad Method)**: 
     - Based on Supreme Court rulings (June 2024)
     - Includes unrealized capital gains
     - Tax-free allowance NOT used in calculation (only in comparison)
     - **Fiscal Partner Optimization**: Applied after calculation (if fiscal partner exists)
       - Same optimization logic as statutory calculation
       - Ensures both methods benefit from partner allocation optimization
4. **Comparison Agent**: Analyzes differences between statutory and actual return methods
6. **Final State**: Returns to main graph with calculation results and recommendations

## 4. Security Model

| Layer | Protection |
|-------|-----------|
| **Ingestion** | PII scrubbed before LLM |
| **Graph State** | Only structured data stored |
| **Tools** | Deterministic (no LLM for math) |
| **Audit** | Every value links to source doc + page |

## 5. Error Handling

- **PII Scrubbing Failures**: Documents that fail scrubbing are **excluded** from processing (Zero-Trust policy). If all documents fail, the pipeline raises a `RuntimeError`.
- **Partial Failures**: `Send` API isolates document failures - one failed document doesn't crash the pipeline
- **Quarantine State**: Missing data sets status to "quarantine" and skips Box 3 calculation
- **Early Exit**: Graph ends early if no Box 3 assets or data is invalid
- **Note**: Human-in-the-loop (HITL) resume logic is not yet implemented in this demo version

