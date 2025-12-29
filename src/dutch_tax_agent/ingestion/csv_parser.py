"""CSV transaction file parsing (deterministic, no LLM)."""

import csv
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from dutch_tax_agent.tools.currency import CurrencyConverter

logger = logging.getLogger(__name__)


class CSVParsingError(Exception):
    """Raised when CSV parsing fails."""

    pass


class CSVTransactionParser:
    """Parses CSV transaction files and extracts Box 3 asset data.
    
    Expected CSV format:
    Type,Product,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance
    """

    REQUIRED_COLUMNS = [
        "Type",
        "Product",
        "Started Date",
        "Completed Date",
        "Description",
        "Amount",
        "Fee",
        "Currency",
        "State",
        "Balance",
    ]

    def __init__(self, currency_converter: Optional[CurrencyConverter] = None):
        """Initialize CSV parser.
        
        Args:
            currency_converter: Optional CurrencyConverter instance.
                                If None, creates a new one.
        """
        self.currency_converter = currency_converter or CurrencyConverter()

    def parse(self, csv_path: Path, tax_year: int) -> dict:
        """Parse a CSV transaction file and extract Box 3 data.
        
        Args:
            csv_path: Path to the CSV file
            tax_year: Tax year to validate against
            
        Returns:
            dict with keys:
                - jan1_balance_eur: Balance before first transaction (Jan 1 value)
                - dec31_balance_eur: Balance after last transaction (Dec 31 value)
                - total_deposits_eur: Total deposits during the year
                - total_withdrawals_eur: Total withdrawals during the year
                - currency: Original currency code
                - first_transaction_date: Date of first transaction
                - last_transaction_date: Date of last transaction
                - transaction_count: Number of transactions
                
        Raises:
            CSVParsingError: If parsing fails or validation fails
        """
        if not csv_path.exists():
            raise CSVParsingError(f"CSV file not found: {csv_path}")

        try:
            with open(csv_path, "r", encoding="utf-8") as f:
                # Read CSV
                reader = csv.DictReader(f)
                
                # Validate columns
                if not reader.fieldnames:
                    raise CSVParsingError("CSV file has no header row")
                
                missing_columns = [
                    col for col in self.REQUIRED_COLUMNS
                    if col not in reader.fieldnames
                ]
                if missing_columns:
                    raise CSVParsingError(
                        f"Missing required columns: {', '.join(missing_columns)}"
                    )
                
                # Read all rows and filter out rows where Product = "Deposit"
                all_rows = list(reader)
                rows = [
                    row for row in all_rows
                    if row.get("Product", "").strip().upper() != "DEPOSIT"
                ]
                
                if not rows:
                    filtered_count = len(all_rows) - len(rows)
                    raise CSVParsingError(
                        f"CSV file has no data rows after filtering out {filtered_count} Deposit product row(s). "
                        f"All transactions were filtered out."
                    )
                
                # Sort by Completed Date to find first and last transactions
                try:
                    rows.sort(
                        key=lambda r: self._parse_date(r["Completed Date"]),
                        reverse=False
                    )
                except (ValueError, KeyError) as e:
                    raise CSVParsingError(
                        f"Failed to parse dates: {e}. "
                        f"Expected format: YYYY-MM-DD HH:MM:SS"
                    )
                
                first_row = rows[0]
                last_row = rows[-1]
                
                first_date = self._parse_date(first_row["Completed Date"])
                last_date = self._parse_date(last_row["Completed Date"])
                
                # Validate tax year
                if first_date.year != tax_year and last_date.year != tax_year:
                    raise CSVParsingError(
                        f"CSV transactions do not match tax year {tax_year}. "
                        f"First transaction: {first_date.year}, "
                        f"Last transaction: {last_date.year}"
                    )
                
                # Get currency (should be consistent across all rows)
                currencies = {row["Currency"].strip().upper() for row in rows if row["Currency"].strip()}
                if len(currencies) > 1:
                    logger.warning(
                        f"Multiple currencies found in CSV: {currencies}. "
                        f"Using first currency: {list(currencies)[0]}"
                    )
                currency = list(currencies)[0] if currencies else "EUR"
                
                # Calculate Jan 1 balance: Balance of first transaction - Amount of first transaction
                # This gives us the balance BEFORE the first transaction
                try:
                    first_balance = float(first_row["Balance"].replace(",", ""))
                    first_amount = float(first_row["Amount"].replace(",", ""))
                    jan1_balance = first_balance - first_amount
                except (ValueError, KeyError) as e:
                    raise CSVParsingError(f"Failed to parse balance/amount from first row: {e}")
                
                # Dec 31 balance: Balance of last transaction
                try:
                    dec31_balance = float(last_row["Balance"].replace(",", ""))
                except (ValueError, KeyError) as e:
                    raise CSVParsingError(f"Failed to parse balance from last row: {e}")
                
                # Calculate total deposits and withdrawals
                total_deposits = 0.0
                total_withdrawals = 0.0
                total_fees = 0.0
                
                for row in rows:
                    try:
                        amount = float(row["Amount"].replace(",", ""))
                        if amount > 0:
                            total_deposits += amount
                        else:
                            total_withdrawals += abs(amount)  # Store as positive
                        
                        # Parse and accumulate fees (treat as withdrawals)
                        fee_str = row.get("Fee", "").strip()
                        if fee_str:
                            try:
                                fee = float(fee_str.replace(",", ""))
                                if fee > 0:  # Only add positive fees
                                    total_fees += fee
                            except ValueError:
                                logger.warning(f"Skipping row with invalid fee value: {fee_str}")
                    except (ValueError, KeyError) as e:
                        logger.warning(f"Skipping row with invalid amount: {e}")
                        continue
                
                # Convert all values to EUR
                # Use Jan 1 of tax year as reference date for conversion
                from datetime import date
                reference_date = date(tax_year, 1, 1)
                
                jan1_balance_eur = self.currency_converter.convert(
                    jan1_balance,
                    from_currency=currency,
                    to_currency="EUR",
                    reference_date=reference_date
                )
                
                dec31_balance_eur = self.currency_converter.convert(
                    dec31_balance,
                    from_currency=currency,
                    to_currency="EUR",
                    reference_date=reference_date
                )
                
                total_deposits_eur = self.currency_converter.convert(
                    total_deposits,
                    from_currency=currency,
                    to_currency="EUR",
                    reference_date=reference_date
                )
                
                total_withdrawals_eur = self.currency_converter.convert(
                    total_withdrawals,
                    from_currency=currency,
                    to_currency="EUR",
                    reference_date=reference_date
                )
                
                # Convert fees to EUR and add to withdrawals
                total_fees_eur = self.currency_converter.convert(
                    total_fees,
                    from_currency=currency,
                    to_currency="EUR",
                    reference_date=reference_date
                )
                total_withdrawals_eur += total_fees_eur
                
                logger.info(
                    f"Successfully parsed {csv_path.name}: "
                    f"{len(rows)} transactions, "
                    f"Jan 1: {jan1_balance_eur:,.2f} EUR, "
                    f"Dec 31: {dec31_balance_eur:,.2f} EUR"
                )
                
                return {
                    "jan1_balance_eur": jan1_balance_eur,
                    "dec31_balance_eur": dec31_balance_eur,
                    "total_deposits_eur": total_deposits_eur,
                    "total_withdrawals_eur": total_withdrawals_eur,
                    "currency": currency,
                    "first_transaction_date": first_date,
                    "last_transaction_date": last_date,
                    "transaction_count": len(rows),
                }
                
        except CSVParsingError:
            raise
        except Exception as e:
            raise CSVParsingError(f"Failed to parse CSV: {e}") from e

    def _parse_date(self, date_str: str) -> datetime:
        """Parse date string in format 'YYYY-MM-DD HH:MM:SS'.
        
        Args:
            date_str: Date string to parse
            
        Returns:
            datetime object
            
        Raises:
            ValueError: If date cannot be parsed
        """
        date_str = date_str.strip()
        # Try the expected format first
        try:
            return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            # Try date-only format
            try:
                return datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                raise ValueError(f"Invalid date format: {date_str}")

    def hash_csv(self, csv_path: Path) -> str:
        """Generate SHA256 hash of CSV file.
        
        Args:
            csv_path: Path to CSV file
            
        Returns:
            SHA256 hash as hex string
        """
        sha256_hash = hashlib.sha256()
        
        with open(csv_path, "rb") as f:
            # Read file in chunks to handle large CSVs
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        
        return sha256_hash.hexdigest()

