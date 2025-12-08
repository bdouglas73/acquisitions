# Private Company Acquisitions Tracker

This repository contains daily reports of private company acquisitions announced on PR Newswire and Business Wire.

## Structure

- `daily-reports/` - Daily acquisition reports in markdown format
  - Files are named: `YYYY-MM-DD-private-acquisitions.md`

## Automated Updates

Reports are automatically generated and committed daily at 8:00 AM via scheduled task.

## Report Contents

Each daily report includes:
- List of private companies that announced or closed acquisitions
- Official website links for each acquiring company
- Target company names
- Press release sources (PR Newswire or Business Wire)
- Summary statistics
- Full references with links to press releases

## Criteria

Reports include only:
- ✅ Privately-held companies (not publicly traded)
- ✅ PE-backed companies that are not public
- ✅ Acquisitions announced or closed on the report date
- ❌ Public companies are excluded
