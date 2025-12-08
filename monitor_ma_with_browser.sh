#!/bin/bash
#
# M&A Press Release Monitoring Script (Browser-based)
# Uses Manus browser automation to extract press releases and contact info
# Runs twice daily at 8 AM and 1 PM Eastern Time
#

set -e

REPO_DIR="/home/ubuntu/acquisitions"
TODAY=$(date +%Y-%m-%d)
REPORT_FILE="enhanced_ma_report_${TODAY}.md"
WEBHOOK_URL="https://hook.us2.make.com/e5racqynovtehtqosma6geutfi6ksy26"

echo "========================================================================"
echo "M&A PRESS RELEASE MONITORING - $(date)"
echo "========================================================================"

cd "$REPO_DIR"

# Create a task prompt for Manus to execute
TASK_PROMPT="Visit the Business Wire M&A filtered page at https://www.businesswire.com/newsroom?language=en&subject=1000011&region=1000490&filter=1958561

Extract all press releases from today (${TODAY}). For each press release:
1. Use the summary already shown on the results page
2. Click through to the full press release
3. Extract all contact information from the bottom (names, emails, phones)
4. Record the press release URL

Filter to include ONLY private company acquisitions (exclude public companies with stock tickers like NYSE, NASDAQ).

Generate an enhanced markdown report saved as ${REPORT_FILE} in ${REPO_DIR} with:
- Press release title
- URL
- Summary (from Business Wire results page)
- Complete contact information

After generating the report:
1. Commit to GitHub with message: 'Add enhanced M&A report for ${TODAY}'
2. Push to origin main
3. Trigger webhook at ${WEBHOOK_URL} with JSON payload containing report_date, total_acquisitions, and github_url"

# Note: This script is designed to be called by the scheduled task system
# which will execute the browser automation task

echo "Task prompt prepared for browser automation"
echo "Report will be saved as: ${REPORT_FILE}"
echo ""
echo "========================================================================"
echo "MONITORING TASK READY"
echo "========================================================================"

# Return the task prompt so the scheduler can execute it
echo "$TASK_PROMPT"
