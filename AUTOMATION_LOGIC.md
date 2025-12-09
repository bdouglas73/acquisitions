# M&A Monitoring Automation Logic

## Overview
The automation runs twice daily (8 AM and 1 PM ET) to capture M&A press releases from Business Wire.

## Key Features

### 1. Smart Deduplication
- Only NEW acquisitions are added to reports
- Checks existing report for URLs already processed
- Prevents duplicates across multiple runs

### 2. Previous Day Checking (Morning Runs Only)
**Problem:** Press releases published between 1 PM and midnight are missed

**Solution:** Morning runs (8 AM) check BOTH:
- Previous day (to catch late press releases from 1 PM - midnight)
- Current day (to catch early morning press releases)

**Implementation:**
```python
current_hour = datetime.now().hour

if current_hour < 12:  # Morning run (8 AM)
    # Check previous day first
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    check_date_for_press_releases(yesterday)
    
    # Then check today
    today = datetime.now().strftime("%Y-%m-%d")
    check_date_for_press_releases(today)
else:  # Afternoon run (1 PM)
    # Only check today
    today = datetime.now().strftime("%Y-%m-%d")
    check_date_for_press_releases(today)
```

### 3. Report Generation
- **Markdown (.md):** Human-readable report with all details
- **JSON (.json):** Google Docs API format with H2 headers and hyperlinks
- Both committed to GitHub

### 4. Google Docs Integration
- JSON is fetched by Make.com
- Inserts at index 1 (beginning of document)
- **Prepends** new acquisitions (newest at top)
- Nothing is overwritten - old content pushed down

## Workflow

### Morning Run (8 AM ET)
1. Check previous day for late press releases (1 PM - midnight)
2. Check current day for early press releases (midnight - 8 AM)
3. Deduplicate against existing report
4. Generate report with ALL new acquisitions
5. Commit to GitHub
6. Make.com fetches at 8:30 AM and updates Google Doc

### Afternoon Run (1 PM ET)
1. Check current day for new press releases (8 AM - 1 PM)
2. Deduplicate against existing report
3. Generate report with ONLY new acquisitions since morning
4. Commit to GitHub
5. Make.com fetches at 1:30 PM and updates Google Doc

## File Naming Convention
- Report date is based on press release date, NOT run date
- Morning run may generate TWO reports:
  - `enhanced_ma_report_2025-12-07.md` (late from previous day)
  - `enhanced_ma_report_2025-12-08.md` (early from current day)
- Make.com fetches both and updates Google Doc twice

## Example Timeline

**December 7, 2025:**
- 8:00 AM: Morning run captures 6 acquisitions → Report generated
- 1:00 PM: Afternoon run captures 3 more → Report updated (9 total)
- 5:00 PM: **2 late acquisitions published** (MISSED by afternoon run)

**December 8, 2025:**
- 8:00 AM: Morning run checks:
  - December 7: Finds 2 late acquisitions → Updates Dec 7 report (11 total)
  - December 8: Finds 4 early acquisitions → Creates Dec 8 report (4 total)
- 1:00 PM: Afternoon run captures 5 more → Dec 8 report updated (9 total)

**Result:** No acquisitions missed!

## Make.com Configuration

### Schedule
- 8:30 AM ET (30 min after Manus morning run)
- 1:30 PM ET (30 min after Manus afternoon run)

### Workflow
1. HTTP GET: Fetch JSON from GitHub
   - URL: `https://raw.githubusercontent.com/bdouglas73/acquisitions/main/enhanced_ma_report_{{formatDate(now; "YYYY-MM-DD")}}.json`
2. HTTP POST: Send to Google Docs API
   - URL: `https://docs.googleapis.com/v1/documents/{DOC_ID}:batchUpdate`
   - Body: JSON from step 1
   - Auth: OAuth 2.0 (Google Docs API)

### Google Docs Result
- H2 headers for each acquisition title
- Hyperlinked URLs
- Proper formatting
- New acquisitions prepended to top
- Old acquisitions remain below
