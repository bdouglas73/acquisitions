#!/usr/bin/env python3
"""
M&A Press Release Monitoring Script with Smart Deduplication
Automatically pulls M&A press releases from Business Wire via Google News RSS,
extracts contact info using Selenium (headless Chrome) to bypass blocks,
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

# Auto-install dependencies if missing
try:
    import selenium
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "selenium", "webdriver-manager"])

# Selenium imports
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# Configuration
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
            
            if " - Business Wire" in title:
                title = title.replace(" - Business Wire", "")
            
            press_releases.append({
                'title': title,
                'url': link,
                'time': pub_date,
                'summary': description,
                'original_url': link
            })
            
        log(f"Found {len(press_releases)} press releases in RSS feed")
        return press_releases
        
    except Exception as e:
        log(f"Error fetching RSS feed: {e}")
        return []

def setup_driver():
    """Setup headless Chrome driver"""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument(f"user-agent={USER_AGENT}")
    
    # Try to use ChromeDriverManager, fallback to system chromedriver
    try:
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
    except:
        driver = webdriver.Chrome(options=chrome_options)
        
    return driver

def extract_contact_info_selenium(driver, url):
    """
    Extract contact information using Selenium
    """
    log(f"  Navigating to: {url}")
    
    try:
        driver.get(url)
        
        # Wait for body to load
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        
        # Check if we are on a Google News redirect page
        if "news.google.com" in driver.current_url:
            # Wait for redirect
            time.sleep(3)
        
        # Get page source
        content = driver.page_source
        
        # Check for access denied
        if "Access Denied" in content:
            log("  Access Denied via Selenium")
            return None
            
        return content
        
    except Exception as e:
        log(f"  Selenium error: {e}")
        return None

def extract_contact_info(pr_data, driver):
    """
    Extract contact information from a single press release
    """
    url = pr_data['url']
    log(f"  Extracting contacts from: {pr_data['title'][:30]}...")
    
    content = extract_contact_info_selenium(driver, url)
    
    if not content:
        log(f"  Failed to fetch content for {url}")
        return {
            'title': pr_data['title'],
            'url': url,
            'summary': pr_data['summary'],
            'contacts': [],
            'success': True
        }
    
    try:
        soup = BeautifulSoup(content, 'html.parser')
        
        summary = pr_data['summary']
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
        
        contacts = []
        full_text = soup.get_text()
        
        emails = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', full_text)
        phones = re.findall(r'\+?1?[-.]?\(?\d{3}\)?[-.]?\d{3}[-.]?\d{4}', full_text)
        
        contact_section = soup.find('div', class_=re.compile(r'bw-release-contact|contacts'))
        
        if contact_section:
            contact_text = contact_section.get_text(separator='\n', strip=True)
            lines = [line.strip() for line in contact_text.split('\n') if line.strip()]
            
            for i, line in enumerate(lines):
                email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', line)
                if email_match:
                    contact = {'email': email_match.group()}
                    if i > 0:
                        prev_line = lines[i-1]
                        if not re.search(r'@|http|www', prev_line) and len(prev_line) < 50:
                            contact['name'] = prev_line
                    phone_match = re.search(r'\+?1?[-.]?\(?\d{3}\)?[-.]?\d{3}[-.]?\d{4}', line)
                    if phone_match:
                        contact['phone'] = phone_match.group()
                    contacts.append(contact)
        
        if not contacts and emails:
            valid_emails = [e for e in emails if not any(x in e.lower() for x in ['info@', 'press@', 'news@', 'contact@'])]
            if not valid_emails and emails:
                valid_emails = emails
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
    
    for indicator in public_indicators:
        if indicator.lower() in combined_text:
            return False
    
    for indicator in non_acquisition_indicators:
        if indicator.lower() in combined_text:
            return False
    
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
    
    start_number = existing_count + 1
    for i, pr in enumerate(private_acquisitions, start_number):
        report_lines.append(f"\n## {i}. {pr['title']}\n")
        report_lines.append(f"\n**Press Release URL:** {pr['url']}\n")
        
        if pr['summary']:
            report_lines.append(f"\n### Summary\n")
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
    log("Starting M&A Press Release Monitor (Selenium Edition)...")
    
    today = get_today_date()
    report_filename = f"{today}.md"
    report_path = os.path.join(GITHUB_REPO_PATH, report_filename)
    
    existing_urls = get_existing_urls_from_report(report_path)
    all_press_releases = fetch_from_google_news_rss()
    
    if not all_press_releases:
        log("No press releases found. Exiting.")
        return
    
    new_press_releases = []
    for pr in all_press_releases:
        is_duplicate = False
        if pr['url'] in existing_urls:
            is_duplicate = True
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
    
    # Setup Selenium Driver
    driver = setup_driver()
    
    try:
        processed_releases = []
        for pr in new_press_releases:
            details = extract_contact_info(pr, driver)
            processed_releases.append(details)
            time.sleep(2)
    finally:
        driver.quit()
    
    is_update = os.path.exists(report_path)
    existing_count = len(existing_urls)
    
    report_content = generate_enhanced_report(processed_releases, today, is_update, existing_count)
    
    if is_update:
        with open(report_path, 'a', encoding='utf-8') as f:
            parts = report_content.split("## Summary")
            if len(parts) > 1:
                item_start = re.search(r'\n## \d+\.', report_content)
                if item_start:
                    new_items = report_content[item_start.start():]
                    f.write(new_items)
                    log("Appended new items to existing report")
    else:
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report_content)
        log("Created new report")

    # Generate JSON report for Make.com
    json_filename = f"enhanced_ma_report_{today}.json"
    json_path = os.path.join(GITHUB_REPO_PATH, json_filename)
    
    # If updating, we should read the existing JSON and append, or just overwrite with full list if we had it
    # But since we only have 'processed_releases' (new ones), we might want to just save the new ones 
    # or read the existing markdown to reconstruct the full list.
    # For simplicity and Make.com compatibility, let's save the NEW items to a separate file or overwrite the daily file with ALL items if possible.
    # Make.com likely expects the full list or just the new ones.
    # Let's save the full list of TODAY's acquisitions to the JSON file.
    
    # We need to reconstruct the full list from the markdown or just save what we have.
    # Since 'processed_releases' only has new ones, let's try to read the existing JSON if it exists.
    
    all_json_data = []
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                all_json_data = json.load(f)
        except:
            pass
            
    # Append new releases
    all_json_data.extend(processed_releases)
    
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(all_json_data, f, indent=2)
    log(f"Created/Updated JSON report: {json_filename}")
    
    try:
        os.chdir(GITHUB_REPO_PATH)
        subprocess.run(["git", "config", "user.name", "GitHub Action"], check=True)
        subprocess.run(["git", "config", "user.email", "action@github.com"], check=True)
        subprocess.run(["git", "add", report_filename], check=True)
        subprocess.run(["git", "add", json_filename], check=True)
        
        commit_message = f"Add {len(processed_releases)} M&A reports for {today}"
        subprocess.run(["git", "commit", "-m", commit_message], check=True)
        subprocess.run(["git", "push"], check=True)
        log("Successfully pushed to GitHub")
        
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
