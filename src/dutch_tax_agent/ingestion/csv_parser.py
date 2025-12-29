"""CSV transaction file parsing (deterministic, no LLM)."""

import csv
import hashlib
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from dutch_tax_agent.tools.currency import CurrencyConverter

logger = logging.getLogger(__name__)


class CSVParsingError(Exception):
    """Raised when CSV parsing fails."""

    pass


def detect_csv_format(csv_path: Path) -> str:
    """Detect the format of a CSV file by examining its headers.
    
    Args:
        csv_path: Path to CSV file
        
    Returns:
        Format identifier: "investment_fund", "multi_currency_investment_fund", "transaction", or "unknown"
        
    Raises:
        CSVParsingError: If file cannot be read
    """
    if not csv_path.exists():
        raise CSVParsingError(f"CSV file not found: {csv_path}")
    
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                return "unknown"
            
            fieldnames = [col.strip() for col in reader.fieldnames]
            
            # Check for multi-currency investment fund format
            # Must have Date, Description, Value EUR, and a foreign currency Value column
            has_date = "Date" in fieldnames
            has_description = "Description" in fieldnames
            has_value_eur = "Value, EUR" in fieldnames
            
            # Check for foreign currency value column (e.g., "Value, USD", "Value, GBP")
            has_foreign_currency = False
            for col in fieldnames:
                if col.startswith("Value, ") and col != "Value, EUR":
                    has_foreign_currency = True
                    break
            
            if has_date and has_description and has_value_eur and has_foreign_currency:
                return "multi_currency_investment_fund"
            
            # Check for investment fund format (EUR only)
            investment_fund_columns = [
                "Date",
                "Description",
                "Value, EUR",
                "Price per share",
                "Quantity of shares",
            ]
            if all(col in fieldnames for col in investment_fund_columns):
                return "investment_fund"
            
            # Check for transaction format
            transaction_columns = [
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
            if all(col in fieldnames for col in transaction_columns):
                return "transaction"
            
            return "unknown"
    except Exception as e:
        raise CSVParsingError(f"Failed to detect CSV format: {e}") from e


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


class InvestmentFundCSVParser:
    """Parses investment fund CSV transaction files and extracts Box 3 asset data.
    
    Expected CSV format:
    Date,Description,"Value, EUR",Price per share,Quantity of shares
    
    Transaction types:
    - BUY: Purchase (positive value) = deposit
    - SELL: Sale (negative value) = withdrawal
    - Service Fee Charged: Fee (negative value) = withdrawal
    - Return PAID: Dividend/distribution (positive value) = realized gain
    """

    REQUIRED_COLUMNS = [
        "Date",
        "Description",
        "Value, EUR",
        "Price per share",
        "Quantity of shares",
    ]

    def __init__(self, currency_converter: Optional[CurrencyConverter] = None):
        """Initialize CSV parser.
        
        Args:
            currency_converter: Optional CurrencyConverter instance.
                                If None, creates a new one (not used for EUR).
        """
        self.currency_converter = currency_converter or CurrencyConverter()

    def parse(self, csv_path: Path, tax_year: int) -> dict:
        """Parse an investment fund CSV transaction file and extract Box 3 data.
        
        Args:
            csv_path: Path to the CSV file
            tax_year: Tax year to validate against
            
        Returns:
            dict with keys:
                - jan1_balance_eur: Balance before first transaction (Jan 1 value)
                - dec31_balance_eur: Balance after last transaction (Dec 31 value)
                - total_deposits_eur: Total deposits during the year (BUY transactions)
                - total_withdrawals_eur: Total withdrawals during the year (SELL + fees)
                - realized_gains_eur: Realized gains (Return PAID transactions)
                - currency: Always "EUR"
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
                
                # Read all rows
                rows = list(reader)
                
                if not rows:
                    raise CSVParsingError("CSV file has no data rows")
                
                # Parse and sort transactions by date
                transactions = []
                for row in rows:
                    try:
                        trans_date = self._parse_date(row["Date"])
                        description = row["Description"].strip()
                        value_str = row["Value, EUR"].strip()
                        
                        # Parse value (handle commas)
                        if not value_str:
                            continue  # Skip empty rows
                        value = float(value_str.replace(",", ""))
                        
                        transactions.append({
                            "date": trans_date,
                            "description": description,
                            "value": value,
                        })
                    except (ValueError, KeyError) as e:
                        logger.warning(f"Skipping row with invalid data: {e}")
                        continue
                
                if not transactions:
                    raise CSVParsingError("No valid transactions found in CSV file")
                
                # Sort by date
                transactions.sort(key=lambda t: t["date"])
                
                first_transaction = transactions[0]
                last_transaction = transactions[-1]
                
                first_date = first_transaction["date"]
                last_date = last_transaction["date"]
                
                # Validate tax year
                if first_date.year != tax_year and last_date.year != tax_year:
                    raise CSVParsingError(
                        f"CSV transactions do not match tax year {tax_year}. "
                        f"First transaction: {first_date.year}, "
                        f"Last transaction: {last_date.year}"
                    )
                
                # Calculate running balance and categorize transactions
                # We'll track the balance by processing transactions chronologically
                # The balance represents the value of holdings at each point
                balance = 0.0
                total_deposits = 0.0
                total_withdrawals = 0.0
                total_fees = 0.0
                realized_gains = 0.0
                
                # Process transactions chronologically to build balance
                for trans in transactions:
                    value = trans["value"]
                    desc = trans["description"].upper()
                    
                    if "BUY" in desc:
                        # Purchase = deposit (increases holdings and balance)
                        total_deposits += abs(value)  # Value is positive for BUY
                        balance += value
                    elif "SELL" in desc:
                        # Sale = withdrawal (decreases holdings and balance)
                        total_withdrawals += abs(value)  # Value is negative for SELL, store as positive
                        balance += value  # Add negative value
                    elif "SERVICE FEE" in desc or "FEE CHARGED" in desc:
                        # Fee = withdrawal (decreases balance, doesn't change holdings)
                        total_fees += abs(value)  # Value is negative, store as positive
                        total_withdrawals += abs(value)
                        balance += value  # Add negative value
                    elif "RETURN PAID" in desc or "RETURN" in desc:
                        # Return/dividend = realized gain (increases balance, doesn't change holdings)
                        realized_gains += value  # Value is positive
                        balance += value
                    else:
                        # Unknown transaction type - treat value as-is
                        logger.warning(f"Unknown transaction type: {desc}, treating as balance change")
                        balance += value
                        if value > 0:
                            total_deposits += value
                        else:
                            total_withdrawals += abs(value)
                
                # For investment fund CSV files, we cannot calculate Jan 1 and Dec 31 balances
                # because we don't have the starting balance and the CSV may not cover the full year
                # Leave them as None (unknown)
                jan1_balance = None
                dec31_balance = None
                
                # All values are already in EUR, no conversion needed
                logger.info(
                    f"Successfully parsed investment fund CSV {csv_path.name}: "
                    f"{len(transactions)} transactions, "
                    f"Deposits: {total_deposits:,.2f} EUR, "
                    f"Withdrawals: {total_withdrawals:,.2f} EUR, "
                    f"Realized gains: {realized_gains:,.2f} EUR"
                )
                
                return {
                    "jan1_balance_eur": jan1_balance,
                    "dec31_balance_eur": dec31_balance,
                    "total_deposits_eur": total_deposits,
                    "total_withdrawals_eur": total_withdrawals,
                    "realized_gains_eur": realized_gains,
                    "currency": "EUR",
                    "first_transaction_date": first_date,
                    "last_transaction_date": last_date,
                    "transaction_count": len(transactions),
                }
                
        except CSVParsingError:
            raise
        except Exception as e:
            raise CSVParsingError(f"Failed to parse investment fund CSV: {e}") from e

    def _parse_date(self, date_str: str) -> datetime:
        """Parse date string in format 'Dec 31, 2024, 12:28:06 PM'.
        
        Args:
            date_str: Date string to parse
            
        Returns:
            datetime object
            
        Raises:
            ValueError: If date cannot be parsed
        """
        date_str = date_str.strip()
        # Try the expected format: "Dec 31, 2024, 12:28:06 PM"
        try:
            return datetime.strptime(date_str, "%b %d, %Y, %I:%M:%S %p")
        except ValueError:
            # Try without seconds: "Dec 31, 2024, 12:28 PM"
            try:
                return datetime.strptime(date_str, "%b %d, %Y, %I:%M %p")
            except ValueError:
                # Try date only: "Dec 31, 2024"
                try:
                    return datetime.strptime(date_str, "%b %d, %Y")
                except ValueError:
                    raise ValueError(f"Invalid date format: {date_str}. Expected format: 'Dec 31, 2024, 12:28:06 PM'")


class MultiCurrencyInvestmentFundCSVParser:
    """Parses multi-currency investment fund CSV transaction files and extracts Box 3 asset data.
    
    Expected CSV format:
    Date,Description,"Value, USD","Value, EUR",FX Rate,Price per share,Quantity of shares
    
    Supports multiple currencies (USD, GBP, etc.) with pre-converted EUR values.
    
    Transaction types:
    - BUY: Purchase (positive value) = deposit
    - SELL: Sale (negative value) = withdrawal
    - Service Fee Charged: Fee (negative value) = withdrawal
    - Return PAID: Dividend/distribution (positive value) = realized gain
    - Return WITHDRAWN: Withdrawal of returns (negative value) = withdrawal
    - Return Reinvested: Reinvestment of returns (negative value) = no deposit/withdrawal
    """

    REQUIRED_COLUMNS = [
        "Date",
        "Description",
        "Value, EUR",
    ]

    def __init__(self, currency_converter: Optional[CurrencyConverter] = None):
        """Initialize CSV parser.
        
        Args:
            currency_converter: Optional CurrencyConverter instance.
                                Not used since EUR values are already provided.
        """
        self.currency_converter = currency_converter or CurrencyConverter()

    def _detect_currency(self, fieldnames: list[str]) -> str:
        """Detect currency from column names.
        
        Args:
            fieldnames: List of column names
            
        Returns:
            Currency code (e.g., "USD", "GBP") or "EUR" if not found
        """
        for col in fieldnames:
            if col.startswith("Value, ") and col != "Value, EUR":
                # Extract currency from "Value, USD" -> "USD"
                currency = col.replace("Value, ", "").strip()
                return currency.upper()
        return "EUR"

    def parse(self, csv_path: Path, tax_year: int) -> dict:
        """Parse a multi-currency investment fund CSV transaction file and extract Box 3 data.
        
        Args:
            csv_path: Path to the CSV file
            tax_year: Tax year to validate against
            
        Returns:
            dict with keys:
                - jan1_balance_eur: Balance before first transaction (Jan 1 value) - None
                - dec31_balance_eur: Balance after last transaction (Dec 31 value) - None
                - total_deposits_eur: Total deposits during the year (BUY transactions)
                - total_withdrawals_eur: Total withdrawals during the year (SELL + fees + withdrawals)
                - realized_gains_eur: Realized gains (Return PAID transactions)
                - currency: Detected currency code (USD, GBP, etc.)
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
                
                fieldnames = [col.strip() for col in reader.fieldnames]
                
                missing_columns = [
                    col for col in self.REQUIRED_COLUMNS
                    if col not in fieldnames
                ]
                if missing_columns:
                    raise CSVParsingError(
                        f"Missing required columns: {', '.join(missing_columns)}"
                    )
                
                # Detect currency from column names
                currency = self._detect_currency(fieldnames)
                
                # Read all rows
                rows = list(reader)
                
                if not rows:
                    raise CSVParsingError("CSV file has no data rows")
                
                # Parse and sort transactions by date
                transactions = []
                for row in rows:
                    try:
                        trans_date = self._parse_date(row["Date"])
                        description = row["Description"].strip()
                        value_str = row["Value, EUR"].strip()
                        
                        # Parse value (handle commas)
                        if not value_str:
                            continue  # Skip empty rows
                        value = float(value_str.replace(",", ""))
                        
                        transactions.append({
                            "date": trans_date,
                            "description": description,
                            "value": value,
                        })
                    except (ValueError, KeyError) as e:
                        logger.warning(f"Skipping row with invalid data: {e}")
                        continue
                
                if not transactions:
                    raise CSVParsingError("No valid transactions found in CSV file")
                
                # Sort by date
                transactions.sort(key=lambda t: t["date"])
                
                first_transaction = transactions[0]
                last_transaction = transactions[-1]
                
                first_date = first_transaction["date"]
                last_date = last_transaction["date"]
                
                # Validate tax year
                if first_date.year != tax_year and last_date.year != tax_year:
                    raise CSVParsingError(
                        f"CSV transactions do not match tax year {tax_year}. "
                        f"First transaction: {first_date.year}, "
                        f"Last transaction: {last_date.year}"
                    )
                
                # Calculate running balance and categorize transactions
                total_deposits = 0.0
                total_withdrawals = 0.0
                total_fees = 0.0
                realized_gains = 0.0
                
                # Process transactions chronologically to categorize them
                for trans in transactions:
                    value = trans["value"]
                    desc = trans["description"].upper()
                    
                    if "BUY" in desc:
                        # Purchase = deposit (increases holdings and balance)
                        total_deposits += abs(value)  # Value is positive for BUY
                    elif "SELL" in desc:
                        # Sale = withdrawal (decreases holdings and balance)
                        total_withdrawals += abs(value)  # Value is negative for SELL, store as positive
                    elif "SERVICE FEE" in desc or "FEE CHARGED" in desc:
                        # Fee = withdrawal (decreases balance, doesn't change holdings)
                        total_fees += abs(value)  # Value is negative, store as positive
                        total_withdrawals += abs(value)
                    elif "RETURN PAID" in desc:
                        # Return/dividend = realized gain (increases balance, doesn't change holdings)
                        realized_gains += value  # Value is positive
                    elif "RETURN WITHDRAWN" in desc:
                        # Withdrawal of returns = withdrawal
                        total_withdrawals += abs(value)  # Value is negative, store as positive
                    elif "RETURN REINVESTED" in desc:
                        # Reinvestment = no deposit/withdrawal (just a balance change)
                        # Do not count as deposit or withdrawal
                        pass
                    else:
                        # Unknown transaction type - treat value as-is
                        logger.warning(f"Unknown transaction type: {desc}, treating as balance change")
                        if value > 0:
                            total_deposits += value
                        else:
                            total_withdrawals += abs(value)
                
                # For investment fund CSV files, we cannot calculate Jan 1 and Dec 31 balances
                # because we don't have the starting balance and the CSV may not cover the full year
                # Leave them as None (unknown)
                jan1_balance = None
                dec31_balance = None
                
                # All values are already in EUR, no conversion needed
                logger.info(
                    f"Successfully parsed multi-currency investment fund CSV {csv_path.name}: "
                    f"{len(transactions)} transactions, "
                    f"Currency: {currency}, "
                    f"Deposits: {total_deposits:,.2f} EUR, "
                    f"Withdrawals: {total_withdrawals:,.2f} EUR, "
                    f"Realized gains: {realized_gains:,.2f} EUR"
                )
                
                return {
                    "jan1_balance_eur": jan1_balance,
                    "dec31_balance_eur": dec31_balance,
                    "total_deposits_eur": total_deposits,
                    "total_withdrawals_eur": total_withdrawals,
                    "realized_gains_eur": realized_gains,
                    "currency": currency,
                    "first_transaction_date": first_date,
                    "last_transaction_date": last_date,
                    "transaction_count": len(transactions),
                }
                
        except CSVParsingError:
            raise
        except Exception as e:
            raise CSVParsingError(f"Failed to parse multi-currency investment fund CSV: {e}") from e

    def _parse_date(self, date_str: str) -> datetime:
        """Parse date string in format 'Jul 17, 2024, 10:25:38 AM'.
        
        Args:
            date_str: Date string to parse
            
        Returns:
            datetime object
            
        Raises:
            ValueError: If date cannot be parsed
        """
        date_str = date_str.strip()
        # Try the expected format: "Jul 17, 2024, 10:25:38 AM"
        try:
            return datetime.strptime(date_str, "%b %d, %Y, %I:%M:%S %p")
        except ValueError:
            # Try without seconds: "Jul 17, 2024, 10:25 AM"
            try:
                return datetime.strptime(date_str, "%b %d, %Y, %I:%M %p")
            except ValueError:
                # Try date only: "Jul 17, 2024"
                try:
                    return datetime.strptime(date_str, "%b %d, %Y")
                except ValueError:
                    raise ValueError(f"Invalid date format: {date_str}. Expected format: 'Jul 17, 2024, 10:25:38 AM'")


def parse_csv(
    csv_path: Path,
    tax_year: int,
    currency_converter: Optional[CurrencyConverter] = None
) -> dict:
    """Parse a CSV file, automatically detecting format and routing to appropriate parser.
    
    This is the main entry point for CSV parsing. It detects the CSV format
    and routes to the appropriate parser (MultiCurrencyInvestmentFundCSVParser,
    InvestmentFundCSVParser, or CSVTransactionParser).
    
    Args:
        csv_path: Path to the CSV file
        tax_year: Tax year to validate against
        currency_converter: Optional CurrencyConverter instance
        
    Returns:
        dict with keys:
            - jan1_balance_eur: Balance before first transaction (Jan 1 value)
            - dec31_balance_eur: Balance after last transaction (Dec 31 value)
            - total_deposits_eur: Total deposits during the year
            - total_withdrawals_eur: Total withdrawals during the year
            - realized_gains_eur: Realized gains (only for investment fund formats)
            - currency: Original currency code
            - first_transaction_date: Date of first transaction
            - last_transaction_date: Date of last transaction
            - transaction_count: Number of transactions
            
    Raises:
        CSVParsingError: If parsing fails or format is unknown
    """
    format_type = detect_csv_format(csv_path)
    
    if format_type == "multi_currency_investment_fund":
        parser = MultiCurrencyInvestmentFundCSVParser(currency_converter)
        return parser.parse(csv_path, tax_year)
    elif format_type == "investment_fund":
        parser = InvestmentFundCSVParser(currency_converter)
        return parser.parse(csv_path, tax_year)
    elif format_type == "transaction":
        parser = CSVTransactionParser(currency_converter)
        return parser.parse(csv_path, tax_year)
    else:
        raise CSVParsingError(
            f"Unknown CSV format. Expected one of: "
            f"multi-currency investment fund format (Date, Description, Value XXX, Value EUR, ...), "
            f"investment fund format (Date, Description, Value EUR, Price per share, Quantity of shares), "
            f"or transaction format (Type, Product, Started Date, Completed Date, etc.)"
        )

