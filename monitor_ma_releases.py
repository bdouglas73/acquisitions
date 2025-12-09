#!/usr/bin/env python3
"""
M&A Press Release Monitoring Script with Smart Deduplication
Automatically pulls M&A press releases from Business Wire via Google News RSS,
extracts contact info using robust fallback strategies (Cache/Proxy),
generates enhanced reports, and commits to GitHub.

Runs twice daily at 8 AM and 1 PM Eastern Time
Only adds NEW acquisitions to avoid duplicates
"""

import os
import sys
import json
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import subprocess
import re
import time
import xml.etree.ElementTree as ET

# Configuration
# Google News RSS for "site:businesswire.com acquisition" (past 24 hours)
RSS_URL = "https://news.google.com/rss/search?q=site:businesswire.com+acquisition+when:1d&hl=en-US&gl=US&ceid=US:en"
GITHUB_REPO_PATH = "/home/ubuntu/acquisitions"
MAKE_WEBHOOK_URL = "https://hook.us2.make.com/e5racqynovtehtqosma6geutfi6ksy26"

USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

def log(message):
    """Print timestamped log message"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")

def get_today_date():
    """Get today's date in YYYY-MM-DD format"""
    return datetime.now().strftime("%Y-%m-%d")

def get_existing_urls_from_report(report_path):
    """
    Extract URLs of acquisitions already in the report
    Returns set of URLs
    """
    if not os.path.exists(report_path):
        return set()
    
    try:
        with open(report_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Extract all press release URLs from the report
        # Note: Google News URLs are different, so we might need to track titles or resolved URLs
        # For now, we'll try to extract both standard BW URLs and Google News URLs
        urls = set(re.findall(r'https://www\.businesswire\.com/news/home/\d+/[^\s\)]+', content))
        google_urls = set(re.findall(r'https://news\.google\.com/rss/articles/[^\s\)]+', content))
        urls.update(google_urls)
        
        log(f"Found {len(urls)} existing acquisitions in report")
        return urls
    
    except Exception as e:
        log(f"Error reading existing report: {e}")
        return set()

def fetch_from_google_news_rss():
    """
    Fetch press releases from Google News RSS feed
    Returns list of dicts with title, url, time, summary
    """
    log(f"Fetching press releases from Google News RSS: {RSS_URL}")
    
    try:
        response = requests.get(RSS_URL, timeout=15)
        response.raise_for_status()
        
        root = ET.fromstring(response.content)
        items = root.findall('.//item')
        
        press_releases = []
        
        for item in items:
            title = item.find('title').text
            link = item.find('link').text
            pub_date = item.find('pubDate').text
            description = item.find('description').text if item.find('description') is not None else ""
            
            # Clean title (remove " - Business Wire" suffix)
            if " - Business Wire" in title:
                title = title.replace(" - Business Wire", "")
            
            press_releases.append({
                'title': title,
                'url': link,
                'time': pub_date,
                'summary': description, # Initial summary from RSS
                'original_url': link
            })
            
        log(f"Found {len(press_releases)} press releases in RSS feed")
        return press_releases
        
    except Exception as e:
        log(f"Error fetching RSS feed: {e}")
        return []

def fetch_content_with_fallback(url):
    """
    Try to fetch content using multiple strategies:
    1. Direct curl (often blocked)
    2. Google Cache (reliable for recent content)
    3. Google Translate Proxy (last resort)
    """
    
    # Strategy 1: Direct Curl
    try:
        cmd = [
            "curl", "-s", "-L",
            "-H", f"User-Agent: {USER_AGENT}",
            "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "-H", "Accept-Language: en-US,en;q=0.9",
            "-H", "Referer: https://www.google.com/",
            url
        ]
        output = subprocess.check_output(cmd, timeout=10)
        content = output.decode('utf-8', errors='ignore')
        
        if "Access Denied" not in content and len(content) > 1000:
            return content, "direct"
    except Exception:
        pass
        
    # Strategy 2: Google Cache (Resolve URL first if it's a Google News redirect)
    # Note: Google News URLs redirect to the real URL. We need the real URL for cache.
    real_url = url
    if "news.google.com" in url:
        try:
            # Follow redirect with requests (might be blocked but HEAD often works)
            r = requests.head(url, allow_redirects=True, timeout=5)
            real_url = r.url
        except:
            pass
            
    cache_url = f"http://webcache.googleusercontent.com/search?q=cache:{real_url}"
    try:
        cmd = [
            "curl", "-s", "-L",
            "-H", f"User-Agent: {USER_AGENT}",
            cache_url
        ]
        output = subprocess.check_output(cmd, timeout=15)
        content = output.decode('utf-8', errors='ignore')
        
        if "404" not in content and len(content) > 1000:
            return content, "cache"
    except Exception:
        pass

    # Strategy 3: Google Translate Proxy
    proxy_url = f"https://translate.google.com/translate?sl=auto&tl=en&u={real_url}&client=webapp"
    try:
        cmd = [
            "curl", "-s", "-L",
            "-H", f"User-Agent: {USER_AGENT}",
            proxy_url
        ]
        output = subprocess.check_output(cmd, timeout=15)
        content = output.decode('utf-8', errors='ignore')
        
        if len(content) > 1000:
            return content, "proxy"
    except Exception:
        pass
        
    return None, "failed"

def extract_contact_info(pr_data):
    """
    Extract contact information from a single press release
    """
    url = pr_data['url']
    log(f"  Extracting contacts from: {pr_data['title'][:30]}...")
    
    content, source = fetch_content_with_fallback(url)
    
    if not content:
        log(f"  Failed to fetch content for {url}")
        return {
            'title': pr_data['title'],
            'url': url,
            'summary': pr_data['summary'], # Use RSS summary as fallback
            'contacts': [],
            'success': True # Still mark as success so it gets added to report
        }
    
    log(f"  Fetched content via {source}")
    
    try:
        soup = BeautifulSoup(content, 'html.parser')
        
        # Extract full summary if possible
        # Note: Selectors might vary based on source (Cache vs Proxy)
        summary = pr_data['summary']
        
        # Try to find the main article body
        # Business Wire usually uses .bw-release-body or itemprop="articleBody"
        article_body = soup.find('div', class_=re.compile(r'bw-release-body|release-body|bw-release-main'))
        if not article_body:
            article_body = soup.find('div', itemprop='articleBody')
            
        if article_body:
            paragraphs = article_body.find_all('p')
            summary_parts = []
            for p in paragraphs[:3]:
                text = p.get_text(strip=True)
                if text and len(text) > 50:
                    summary_parts.append(text)
            if summary_parts:
                summary = ' '.join(summary_parts)[:800]
        
        # Extract contact information
        contacts = []
        full_text = soup.get_text()
        
        # Find emails
        emails = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', full_text)
        
        # Find phone numbers
        phones = re.findall(r'\+?1?[-.]?\(?\d{3}\)?[-.]?\d{3}[-.]?\d{4}', full_text)
        
        # Try to find structured contact info
        # Look for "Contacts" or "Contact Information" section
        contact_section = soup.find('div', class_=re.compile(r'bw-release-contact|contacts'))
        
        if contact_section:
            contact_text = contact_section.get_text(separator='\n', strip=True)
            lines = [line.strip() for line in contact_text.split('\n') if line.strip()]
            
            for i, line in enumerate(lines):
                email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', line)
                if email_match:
                    contact = {'email': email_match.group()}
                    
                    # Look for name in previous lines
                    if i > 0:
                        prev_line = lines[i-1]
                        if not re.search(r'@|http|www', prev_line) and len(prev_line) < 50:
                            contact['name'] = prev_line
                    
                    # Look for phone
                    phone_match = re.search(r'\+?1?[-.]?\(?\d{3}\)?[-.]?\d{3}[-.]?\d{4}', line)
                    if phone_match:
                        contact['phone'] = phone_match.group()
                    
                    contacts.append(contact)
        
        # If no structured contacts found, just return emails
        if not contacts and emails:
            # Filter out common junk emails
            valid_emails = [e for e in emails if not any(x in e.lower() for x in ['info@', 'press@', 'news@', 'contact@'])]
            if not valid_emails and emails:
                valid_emails = emails # Fallback to generic if no specific ones
                
            contacts = [{'email': email} for email in valid_emails[:3]]
        
        return {
            'title': pr_data['title'],
            'url': url,
            'summary': summary,
            'contacts': contacts,
            'success': True
        }
        
    except Exception as e:
        log(f"  Error parsing content: {e}")
        return {
            'title': pr_data['title'],
            'url': url,
            'summary': pr_data['summary'],
            'contacts': [],
            'success': True
        }

def is_private_company_acquisition(title, summary):
    """
    Determine if this is a private company acquisition
    Exclude public companies and non-acquisition announcements
    """
    public_indicators = [
        'NYSE:', 'NASDAQ:', 'OTCQX:', 'TSX:', 'LSE:',
        'publicly traded', 'public company',
        'Euronext', 'ASX:'
    ]
    
    non_acquisition_indicators = [
        'opposition to', 'opposes', 'against', 'lawsuit', 'investigation', 'class action'
    ]
    
    combined_text = f"{title} {summary}".lower()
    
    # Check for public company indicators
    for indicator in public_indicators:
        if indicator.lower() in combined_text:
            return False
    
    # Check for non-acquisition indicators
    for indicator in non_acquisition_indicators:
        if indicator.lower() in combined_text:
            return False
    
    # Must contain acquisition keywords
    acquisition_keywords = ['acquires', 'acquisition', 'joins', 'partnership', 'acquired', 'launches', 'merger', 'invests', 'investment']
    has_acquisition = any(keyword in combined_text for keyword in acquisition_keywords)
    
    return has_acquisition

def generate_enhanced_report(press_releases, report_date, is_update=False, existing_count=0):
    """
    Generate enhanced markdown report with all press releases
    """
    log("Generating enhanced report...")
    
    report_lines = []
    report_lines.append(f"# Enhanced M&A Report - {report_date}\n")
    report_lines.append(f"**Report Generated:** {datetime.now().strftime('%B %d, %Y at %I:%M %p ET')}\n")
    report_lines.append("**Source:** Business Wire M&A Press Releases (via Google News)\n")
    report_lines.append("**Filter:** Private Company Acquisitions Only\n")
    report_lines.append("\n---\n")
    
    # Filter for private acquisitions
    private_acquisitions = [
        pr for pr in press_releases 
        if pr['success'] and is_private_company_acquisition(pr['title'], pr['summary'])
    ]
    
    total_count = existing_count + len(private_acquisitions)
    
    report_lines.append(f"\n## Summary\n")
    report_lines.append(f"\nThis report contains **{total_count} private company acquisitions** ")
    report_lines.append("announced on " + report_date + ", with complete press release summaries, URLs, and contact information for media inquiries.\n")
    
    if is_update and len(private_acquisitions) > 0:
        report_lines.append(f"\n**New acquisitions added:** {len(private_acquisitions)}\n")
    
    report_lines.append("\n---\n")
    
    # Add each acquisition
    start_number = existing_count + 1
    for i, pr in enumerate(private_acquisitions, start_number):
        report_lines.append(f"\n## {i}. {pr['title']}\n")
        report_lines.append(f"\n**Press Release URL:** {pr['url']}\n")
        
        if pr['summary']:
            report_lines.append(f"\n### Summary\n")
            # Clean up summary (remove HTML tags if any remain)
            clean_summary = re.sub(r'<[^>]+>', '', pr['summary'])
            report_lines.append(f"\n{clean_summary}\n")
        
        if pr['contacts']:
            report_lines.append(f"\n### Contact Information\n")
            for j, contact in enumerate(pr['contacts'], 1):
                if len(pr['contacts']) > 1:
                    report_lines.append(f"\n**Contact {j}:**\n")
                else:
                    report_lines.append(f"\n")
                
                if 'name' in contact:
                    report_lines.append(f"- Name: {contact['name']}\n")
                if 'title' in contact:
                    report_lines.append(f"- Title: {contact['title']}\n")
                if 'company' in contact:
                    report_lines.append(f"- Company: {contact['company']}\n")
                if 'email' in contact:
                    report_lines.append(f"- Email: {contact['email']}\n")
                if 'phone' in contact:
                    report_lines.append(f"- Phone: {contact['phone']}\n")
        else:
            report_lines.append(f"\n### Contact Information\n")
            report_lines.append("No specific contact information found in press release.\n")
            
        report_lines.append("\n---\n")
        
    return "\n".join(report_lines)

def main():
    log("Starting M&A Press Release Monitor (Google News RSS Edition)...")
    
    # Setup paths
    today = get_today_date()
    report_filename = f"{today}.md"
    report_path = os.path.join(GITHUB_REPO_PATH, report_filename)
    
    # 1. Get existing URLs to avoid duplicates
    existing_urls = get_existing_urls_from_report(report_path)
    
    # 2. Fetch press releases from Google News RSS
    all_press_releases = fetch_from_google_news_rss()
    
    if not all_press_releases:
        log("No press releases found. Exiting.")
        return
    
    # 3. Filter out existing ones
    new_press_releases = []
    for pr in all_press_releases:
        # Check if URL or Title is already in report
        # (Titles are safer because URLs might change with redirects)
        is_duplicate = False
        if pr['url'] in existing_urls:
            is_duplicate = True
        
        # Also check title in existing file content if we have it
        if os.path.exists(report_path):
            with open(report_path, 'r') as f:
                if pr['title'] in f.read():
                    is_duplicate = True
        
        if not is_duplicate:
            new_press_releases.append(pr)
    
    log(f"Found {len(new_press_releases)} NEW press releases")
    
    if not new_press_releases:
        log("No new press releases to process. Exiting.")
        return
    
    # 4. Extract details for new releases
    processed_releases = []
    for pr in new_press_releases:
        details = extract_contact_info(pr)
        processed_releases.append(details)
        # Be nice to the server
        time.sleep(2)
    
    # 5. Generate Report
    is_update = os.path.exists(report_path)
    existing_count = len(existing_urls)
    
    report_content = generate_enhanced_report(processed_releases, today, is_update, existing_count)
    
    # 6. Save/Append to Report
    if is_update:
        # Append to existing report
        with open(report_path, 'a', encoding='utf-8') as f:
            # Remove the last "---" from existing report if it exists to make it clean?
            # Actually, just appending is fine, our format handles it.
            # But we need to skip the header part of the new report content
            # The generate_enhanced_report function creates a full report.
            # We should only append the *new items*.
            
            # Let's extract just the items part
            parts = report_content.split("## Summary")
            if len(parts) > 1:
                # Reconstruct just the items
                # Find where the first item starts (## X.)
                item_start = re.search(r'\n## \d+\.', report_content)
                if item_start:
                    new_items = report_content[item_start.start():]
                    f.write(new_items)
                    log("Appended new items to existing report")
    else:
        # Create new report
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report_content)
        log("Created new report")
    
    # 7. Commit and Push to GitHub
    try:
        os.chdir(GITHUB_REPO_PATH)
        subprocess.run(["git", "config", "user.name", "GitHub Action"], check=True)
        subprocess.run(["git", "config", "user.email", "action@github.com"], check=True)
        subprocess.run(["git", "add", report_filename], check=True)
        
        commit_message = f"Add {len(processed_releases)} M&A reports for {today}"
        subprocess.run(["git", "commit", "-m", commit_message], check=True)
        
        # Push using the token provided in the environment or remote URL
        subprocess.run(["git", "push"], check=True)
        log("Successfully pushed to GitHub")
        
        # 8. Trigger Webhook (Optional)
        try:
            requests.post(MAKE_WEBHOOK_URL, json={
                "date": today,
                "count": len(processed_releases),
                "message": "New M&A reports added"
            }, timeout=5)
        except:
            pass
            
    except Exception as e:
        log(f"Error during git operations: {e}")

if __name__ == "__main__":
    main()
