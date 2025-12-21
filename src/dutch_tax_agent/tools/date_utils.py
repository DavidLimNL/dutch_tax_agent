"""Date utility functions for Box 3 tax calculations."""

import logging
from datetime import date, timedelta
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def is_weekend(d: date) -> bool:
    """Check if a date is a weekend (Saturday or Sunday).
    
    Args:
        d: Date to check
        
    Returns:
        True if weekend, False otherwise
    """
    return d.weekday() >= 5  # Saturday = 5, Sunday = 6


def is_new_years_day(d: date) -> bool:
    """Check if a date is New Year's Day (January 1st).
    
    Args:
        d: Date to check
        
    Returns:
        True if New Year's Day, False otherwise
    """
    return d.month == 1 and d.day == 1


def find_closest_business_date(
    target_date: date, 
    available_dates: list[date], 
    max_days_offset: int = 3
) -> Optional[Tuple[date, int]]:
    """Find the closest business date to a target date from available dates.
    
    Accounts for weekends and holidays. Returns the closest date within max_days_offset
    and the number of days difference.
    
    Args:
        target_date: The target date (e.g., Jan 1 or Dec 31)
        available_dates: List of dates available in the document
        max_days_offset: Maximum number of days away from target to accept (default: 3)
        
    Returns:
        Tuple of (closest_date, days_difference) if found within range, None otherwise
    """
    if not available_dates:
        return None
    
    # Filter dates within acceptable range
    min_date = target_date - timedelta(days=max_days_offset)
    max_date = target_date + timedelta(days=max_days_offset)
    
    candidate_dates = [
        d for d in available_dates
        if min_date <= d <= max_date
    ]
    
    if not candidate_dates:
        return None
    
    # Find the closest date
    closest_date = min(candidate_dates, key=lambda d: abs((d - target_date).days))
    days_diff = abs((closest_date - target_date).days)
    
    return (closest_date, days_diff)


def check_document_has_required_dates(
    doc_date_range: Optional[Tuple[date, date]],
    tax_year: int,
    max_days_offset: int = 3
) -> Tuple[bool, bool, Optional[str]]:
    """Check if a document contains data for Jan 1 or Dec 31 of the tax year.
    
    Args:
        doc_date_range: Tuple of (start_date, end_date) for the document, or None
        tax_year: The tax year to check
        max_days_offset: Maximum days away from Jan 1/Dec 31 to accept
        
    Returns:
        Tuple of (has_jan1, has_dec31, warning_message)
        - has_jan1: True if document covers Jan 1 (or close date)
        - has_dec31: True if document covers Dec 31 (or close date)
        - warning_message: Warning if dates are close but not exact, None otherwise
    """
    if doc_date_range is None:
        return (False, False, "Document date range could not be determined")
    
    start_date, end_date = doc_date_range
    
    jan1_target = date(tax_year, 1, 1)
    dec31_target = date(tax_year, 12, 31)
    
    # Check if Jan 1 is within the document range (with tolerance)
    jan1_min = jan1_target - timedelta(days=max_days_offset)
    jan1_max = jan1_target + timedelta(days=max_days_offset)
    has_jan1 = jan1_min <= start_date <= jan1_max or jan1_min <= end_date <= jan1_max or \
               (start_date <= jan1_min and end_date >= jan1_max)
    
    # Check if Dec 31 is within the document range (with tolerance)
    dec31_min = dec31_target - timedelta(days=max_days_offset)
    dec31_max = dec31_target + timedelta(days=max_days_offset)
    has_dec31 = dec31_min <= start_date <= dec31_max or dec31_min <= end_date <= dec31_max or \
                (start_date <= dec31_min and end_date >= dec31_max)
    
    warning = None
    if has_jan1 and start_date != jan1_target and end_date != jan1_target:
        days_off = min(abs((start_date - jan1_target).days), abs((end_date - jan1_target).days))
        if days_off > 0:
            warning = f"Jan 1 value found {days_off} days from target date"
    
    if has_dec31 and start_date != dec31_target and end_date != dec31_target:
        days_off = min(abs((start_date - dec31_target).days), abs((end_date - dec31_target).days))
        if days_off > 0:
            if warning:
                warning += f"; Dec 31 value found {days_off} days from target date"
            else:
                warning = f"Dec 31 value found {days_off} days from target date"
    
    return (has_jan1, has_dec31, warning)

