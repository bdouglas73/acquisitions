# Private Company Acquisitions Tracker

This repository contains daily reports of private company acquisitions announced on PR Newswire and Business Wire.

## Structure

- `enhanced_ma_report_YYYY-MM-DD.md` - **NEW: Enhanced reports with contact information**
- `ma_report_YYYY-MM-DD.md` - Basic acquisition reports
- `daily-reports/` - Legacy daily acquisition reports (if applicable)

## Automated Updates

Reports are automatically generated and committed **twice daily**:
- **8:00 AM Eastern Time** - Morning monitoring run
- **1:00 PM Eastern Time** - Afternoon monitoring run

## Report Types

### Enhanced Reports (NEW)
Enhanced reports include complete contact information for media inquiries:
- Press release summaries (from Business Wire)
- Direct URLs to full press releases
- Contact names, titles, emails, and phone numbers
- Formatted for easy reference

### Basic Reports
Basic reports include:
- List of private companies that announced or closed acquisitions
- Official website links for each acquiring company
- Target company names
- Press release sources (PR Newswire or Business Wire)
- Summary statistics
- Full references with links to press releases

## Data Sources

### Business Wire M&A Filter
Primary source for enhanced reports:
```
https://www.businesswire.com/newsroom?language=en&subject=1000011&region=1000490&filter=1958561
```

Filters applied:
- Language: English
- Subject: Merger/Acquisition
- Region: United States

## Criteria

Reports include only:
- ✅ Privately-held companies (not publicly traded)
- ✅ PE-backed companies that are not public
- ✅ Acquisitions announced or closed on the report date
- ❌ Public companies are excluded (NYSE, NASDAQ, etc.)
- ❌ Opposition announcements excluded
- ❌ Non-acquisition news excluded

## Integration

### GitHub
All reports are automatically committed to this repository with descriptive commit messages.

### Make.com Webhook
Enhanced reports trigger a webhook that appends data to Google Docs for further processing and distribution.

**Webhook URL:** `https://hook.us2.make.com/4c7xqjcjt3yxhbdvnxkw5u6qxr6cqb3y`

## Latest Report

**Date:** December 8, 2025  
**File:** `enhanced_ma_report_2025-12-08.md`  
**Acquisitions:** 6 private company transactions  
**Status:** ✅ Committed to GitHub

### Acquisitions Included:
1. Stonepeak Launches Peregrine Cold Logistics
2. Jade Global Acquires D4M International
3. Milliman Announces Acquisition of MorVest Capital
4. Procyon Expands with Addition of OLV Investment Group
5. Dermatology Associates of San Antonio Joins Epiphany Dermatology
6. Quantide Growth Partners Acquires Value Innorruption Advisors

## Scripts

- `monitor_ma_releases.py` - Python-based monitoring script
- `monitor_ma_with_browser.sh` - Browser-based monitoring script (recommended for avoiding 403 errors)

## Manual Execution

To manually run the monitoring:
```bash
cd /home/ubuntu/acquisitions
python3 monitor_ma_releases.py
```

---

**Last Updated:** December 8, 2025
