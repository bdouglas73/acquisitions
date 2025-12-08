#!/usr/bin/env python3
"""
M&A Press Release Monitoring Script
Automatically pulls M&A press releases from Business Wire, extracts contact info,
generates enhanced reports, and commits to GitHub.

Runs twice daily at 8 AM and 1 PM Eastern Time
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

# Configuration
BUSINESS_WIRE_URL = "https://www.businesswire.com/newsroom?language=en&subject=1000011&region=1000490&filter=1958561"
GITHUB_REPO_PATH = "/home/ubuntu/acquisitions"
MAKE_WEBHOOK_URL = "https://hook.us2.make.com/4c7xqjcjt3yxhbdvnxkw5u6qxr6cqb3y"  # Update this URL

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

def log(message):
    """Print timestamped log message"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}")

def get_today_date():
    """Get today's date in YYYY-MM-DD format"""
    return datetime.now().strftime("%Y-%m-%d")

def extract_press_releases_from_page():
    """
    Extract press release URLs and summaries from Business Wire filtered page
    Returns list of dicts with title, url, time, summary
    """
    log("Fetching Business Wire M&A press releases...")
    
    headers = {'User-Agent': USER_AGENT}
    
    try:
        response = requests.get(BUSINESS_WIRE_URL, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        press_releases = []
        today = get_today_date()
        
        # Parse the page content - look for press release blocks
        # This is a simplified version - you may need to adjust selectors
        articles = soup.find_all(['article', 'div'], class_=re.compile(r'bwNewsFeedItem|feed-item|news-item'))
        
        if not articles:
            # Fallback: look for any links with /news/home/ in them
            log("Using fallback method to extract press releases")
            all_links = soup.find_all('a', href=re.compile(r'/news/home/\d{8}'))
            
            for link in all_links:
                href = link.get('href')
                if href and '/news/home/' in href:
                    full_url = href if href.startswith('http') else f"https://www.businesswire.com{href}"
                    title = link.get_text(strip=True)
                    
                    if title and len(title) > 10:  # Filter out short/empty titles
                        press_releases.append({
                            'title': title,
                            'url': full_url,
                            'time': 'Unknown',
                            'summary': ''
                        })
        
        log(f"Found {len(press_releases)} press releases")
        return press_releases
        
    except Exception as e:
        log(f"Error fetching press releases: {e}")
        return []

def extract_contact_info(pr_url):
    """
    Extract contact information from a single press release
    Returns dict with contacts list
    """
    log(f"  Extracting contacts from: {pr_url}")
    
    headers = {'User-Agent': USER_AGENT}
    
    try:
        response = requests.get(pr_url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Get title
        title_tag = soup.find('h1')
        title = title_tag.get_text(strip=True) if title_tag else 'Unknown'
        
        # Get summary (first few paragraphs)
        content_div = soup.find('div', class_=re.compile(r'bw-release-body|release-body|bw-release-main'))
        summary = ''
        
        if content_div:
            paragraphs = content_div.find_all('p')
            summary_parts = []
            for p in paragraphs[:3]:
                text = p.get_text(strip=True)
                if text and len(text) > 50:
                    summary_parts.append(text)
            summary = ' '.join(summary_parts)[:800]
        
        # Extract contact information
        contacts = []
        
        # Look for contact section
        full_text = soup.get_text()
        
        # Find emails
        emails = re.findall(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', full_text)
        
        # Find phone numbers
        phones = re.findall(r'\+?1?[-.]?\(?\d{3}\)?[-.]?\d{3}[-.]?\d{4}', full_text)
        
        # Try to find structured contact info
        contact_section = soup.find('div', class_=re.compile(r'bw-release-contact|contacts'))
        
        if contact_section:
            contact_text = contact_section.get_text(separator='\n', strip=True)
            lines = [line.strip() for line in contact_text.split('\n') if line.strip()]
            
            # Simple parsing - group by email
            for i, line in enumerate(lines):
                email_match = re.search(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', line)
                if email_match:
                    contact = {'email': email_match.group()}
                    
                    # Look for name in previous lines
                    if i > 0:
                        prev_line = lines[i-1]
                        if not re.search(r'@|http|www', prev_line):
                            contact['name'] = prev_line
                    
                    # Look for phone in same or next line
                    phone_match = re.search(r'\+?1?[-.]?\(?\d{3}\)?[-.]?\d{3}[-.]?\d{4}', line)
                    if phone_match:
                        contact['phone'] = phone_match.group()
                    elif i < len(lines) - 1:
                        phone_match = re.search(r'\+?1?[-.]?\(?\d{3}\)?[-.]?\d{3}[-.]?\d{4}', lines[i+1])
                        if phone_match:
                            contact['phone'] = phone_match.group()
                    
                    contacts.append(contact)
        
        # If no structured contacts found, just return emails and phones
        if not contacts and emails:
            contacts = [{'email': email} for email in emails[:3]]  # Limit to first 3
        
        return {
            'title': title,
            'url': pr_url,
            'summary': summary,
            'contacts': contacts,
            'success': True
        }
        
    except Exception as e:
        log(f"  Error extracting from {pr_url}: {e}")
        return {
            'title': 'Error',
            'url': pr_url,
            'summary': f'Error: {str(e)}',
            'contacts': [],
            'success': False
        }

def is_private_company_acquisition(title, summary):
    """
    Determine if this is a private company acquisition
    Exclude public companies and non-acquisition announcements
    """
    # Keywords that indicate public companies
    public_indicators = [
        'NYSE:', 'NASDAQ:', 'OTCQX:', 'TSX:', 'LSE:',
        'publicly traded', 'public company',
        'Euronext', 'ASX:'
    ]
    
    # Keywords that indicate non-acquisitions
    non_acquisition_indicators = [
        'opposition to', 'opposes', 'against',
        'announces closing', 'completes acquisition' # These might be follow-ups
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
    acquisition_keywords = ['acquires', 'acquisition', 'joins', 'partnership', 'acquired']
    has_acquisition = any(keyword in combined_text for keyword in acquisition_keywords)
    
    return has_acquisition

def generate_enhanced_report(press_releases, report_date):
    """
    Generate enhanced markdown report with all press releases
    """
    log("Generating enhanced report...")
    
    report_lines = []
    report_lines.append(f"# Enhanced M&A Report - {report_date}\n")
    report_lines.append(f"**Report Generated:** {datetime.now().strftime('%B %d, %Y at %I:%M %p ET')}\n")
    report_lines.append("**Source:** Business Wire M&A Press Releases (United States)\n")
    report_lines.append("**Filter:** Private Company Acquisitions Only\n")
    report_lines.append("\n---\n")
    
    # Filter for private acquisitions
    private_acquisitions = [
        pr for pr in press_releases 
        if pr['success'] and is_private_company_acquisition(pr['title'], pr['summary'])
    ]
    
    report_lines.append(f"\n## Summary\n")
    report_lines.append(f"\nThis report contains **{len(private_acquisitions)} private company acquisitions** ")
    report_lines.append("announced on " + report_date + ", with complete press release summaries, URLs, and contact information for media inquiries.\n")
    report_lines.append("\n---\n")
    
    # Add each acquisition
    for i, pr in enumerate(private_acquisitions, 1):
        report_lines.append(f"\n## {i}. {pr['title']}\n")
        report_lines.append(f"\n**Press Release URL:** {pr['url']}\n")
        
        if pr['summary']:
            report_lines.append(f"\n### Summary\n")
            report_lines.append(f"\n{pr['summary']}\n")
        
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
        
        report_lines.append("\n---\n")
    
    report_lines.append("\n**End of Report**\n")
    
    return ''.join(report_lines)

def commit_and_push_to_github(report_file, report_date):
    """
    Commit the report to GitHub
    """
    log("Committing to GitHub...")
    
    try:
        os.chdir(GITHUB_REPO_PATH)
        
        # Add the file
        subprocess.run(['git', 'add', report_file], check=True)
        
        # Commit
        commit_message = f"Add enhanced M&A report for {report_date}"
        subprocess.run(['git', 'commit', '-m', commit_message], check=True)
        
        # Push
        subprocess.run(['git', 'push', 'origin', 'main'], check=True)
        
        log("Successfully pushed to GitHub")
        return True
        
    except subprocess.CalledProcessError as e:
        log(f"Git error: {e}")
        return False

def trigger_make_webhook(report_data):
    """
    Trigger Make.com webhook with report data
    """
    log("Triggering Make.com webhook...")
    
    try:
        response = requests.post(
            MAKE_WEBHOOK_URL,
            json=report_data,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        
        if response.status_code == 200:
            log("Webhook triggered successfully")
            return True
        else:
            log(f"Webhook returned status {response.status_code}: {response.text}")
            return False
            
    except Exception as e:
        log(f"Webhook error: {e}")
        return False

def main():
    """Main execution function"""
    log("=" * 80)
    log("M&A PRESS RELEASE MONITORING - STARTED")
    log("=" * 80)
    
    # Get today's date
    report_date = get_today_date()
    report_file = f"enhanced_ma_report_{report_date}.md"
    
    # Step 1: Extract press releases from Business Wire
    press_releases = extract_press_releases_from_page()
    
    if not press_releases:
        log("No press releases found. Exiting.")
        return
    
    # Step 2: Extract contact info from each press release
    detailed_releases = []
    for pr in press_releases[:10]:  # Limit to first 10 to avoid overwhelming
        details = extract_contact_info(pr['url'])
        detailed_releases.append(details)
        time.sleep(2)  # Be polite to the server
    
    # Step 3: Generate enhanced report
    report_content = generate_enhanced_report(detailed_releases, report_date)
    
    # Save report
    report_path = os.path.join(GITHUB_REPO_PATH, report_file)
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_content)
    
    log(f"Report saved to {report_path}")
    
    # Step 4: Commit to GitHub
    commit_success = commit_and_push_to_github(report_file, report_date)
    
    # Step 5: Trigger Make.com webhook
    if commit_success:
        webhook_data = {
            'report_date': report_date,
            'report_type': 'enhanced',
            'total_acquisitions': len([pr for pr in detailed_releases if pr['success']]),
            'github_url': f"https://github.com/bdouglas73/acquisitions/blob/main/{report_file}",
            'report_file': report_file
        }
        trigger_make_webhook(webhook_data)
    
    log("=" * 80)
    log("M&A PRESS RELEASE MONITORING - COMPLETED")
    log("=" * 80)

if __name__ == '__main__':
    main()
