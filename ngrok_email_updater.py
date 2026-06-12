#!/usr/bin/env python3
"""
Ngrok Auto-Restart & Email Notifier
Runs every 2 hours to get a fresh ngrok URL and email it.

This helper is scoped to a single configured port so it does not kill
unrelated ngrok tunnels, such as the public website tunnel on port 5050.
"""

import os
import subprocess
import time
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from pathlib import Path

# Email configuration (edit these)
GMAIL_ADDRESS = ""  # Your Gmail address
GMAIL_APP_PASSWORD = ""  # Gmail app-specific password (not your regular password)
SEND_TO = ""  # Where to send the URL (can be same as GMAIL_ADDRESS)

# Dashboard info
DASHBOARD_PORT = int(os.environ.get("NGROK_PORT", "8888"))
LOCAL_IP = os.environ.get("LOCAL_IP", "192.168.1.162")
NGROK_RESERVED_URL = os.environ.get("NGROK_RESERVED_URL", "").strip()

def kill_existing_ngrok():
    """Kill only the ngrok process for the configured port."""
    try:
        subprocess.run(
            ["pkill", "-f", f"ngrok http.*{DASHBOARD_PORT}"],
            check=False,
        )
        time.sleep(2)
    except Exception as e:
        print(f"Error killing ngrok: {e}")

def start_ngrok():
    """Start ngrok tunnel"""
    try:
        command = ["ngrok", "http"]
        if NGROK_RESERVED_URL:
            command.extend(["--domain", NGROK_RESERVED_URL])
        command.append(str(DASHBOARD_PORT))

        # Start ngrok in background
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(3)  # Wait for tunnel to establish
        return True
    except Exception as e:
        print(f"Error starting ngrok: {e}")
        return False

def get_public_url():
    """Get the public URL from ngrok API"""
    try:
        result = subprocess.run(
            ["curl", "-s", "http://localhost:4040/api/tunnels"],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode == 0:
            data = json.loads(result.stdout)
            tunnels = data.get("tunnels", [])

            for tunnel in tunnels:
                if tunnel.get("proto") == "https":
                    return tunnel.get("public_url")

        return None
    except Exception as e:
        print(f"Error getting URL: {e}")
        return None

def send_email(public_url):
    """Send email with the new public URL"""
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD or not SEND_TO:
        print("⚠️  Email not configured - skipping email")
        print(f"   Edit {__file__} to set:")
        print(f"   - GMAIL_ADDRESS")
        print(f"   - GMAIL_APP_PASSWORD")
        print(f"   - SEND_TO")
        return False

    try:
        # Create message
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"🚀 New Training Dashboard URL - {datetime.now().strftime('%I:%M %p')}"
        msg['From'] = GMAIL_ADDRESS
        msg['To'] = SEND_TO

        # Email body
        text = f"""
Training Dashboard - New Public URL

Your training dashboard is now accessible at:
{public_url}

Local access: http://{LOCAL_IP}:{DASHBOARD_PORT}

This URL is valid for 2 hours. You'll receive a new URL automatically.

Dashboard Features:
• Real-time dataset download progress
• Training status and metrics
• System resources (RAM, disk)
• Process health monitoring
• Lockout controls

Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}
Next update: In 2 hours
"""

        html = f"""
<html>
  <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
    <h2 style="color: #00ff00; background: #000; padding: 15px; border-radius: 5px;">
      🚀 Training Dashboard - New URL
    </h2>

    <div style="background: #f5f5f5; padding: 20px; border-radius: 5px; margin: 20px 0;">
      <p style="font-size: 14px; color: #666;">Your dashboard is now accessible at:</p>
      <p style="font-size: 18px; margin: 10px 0;">
        <a href="{public_url}" style="color: #0066cc; text-decoration: none; font-weight: bold;">
          {public_url}
        </a>
      </p>
      <p style="font-size: 12px; color: #999;">
        Local access: <a href="http://{LOCAL_IP}:{DASHBOARD_PORT}">http://{LOCAL_IP}:{DASHBOARD_PORT}</a>
      </p>
    </div>

    <div style="background: #e8f4f8; padding: 15px; border-left: 4px solid #0066cc; margin: 20px 0;">
      <p style="margin: 5px 0; color: #333;"><strong>✓</strong> Real-time dataset download progress</p>
      <p style="margin: 5px 0; color: #333;"><strong>✓</strong> Training status and metrics</p>
      <p style="margin: 5px 0; color: #333;"><strong>✓</strong> System resources (RAM, disk)</p>
      <p style="margin: 5px 0; color: #333;"><strong>✓</strong> Process health monitoring</p>
      <p style="margin: 5px 0; color: #333;"><strong>✓</strong> Lockout controls</p>
    </div>

    <div style="background: #fff3cd; padding: 10px; border-radius: 5px; margin: 20px 0;">
      <p style="margin: 5px 0; font-size: 12px; color: #856404;">
        ⏰ This URL is valid for 2 hours<br>
        📧 You'll receive a new URL automatically
      </p>
    </div>

    <p style="font-size: 11px; color: #999; margin-top: 30px;">
      Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}<br>
      Next update: In 2 hours
    </p>
  </body>
</html>
"""

        # Attach both text and HTML versions
        part1 = MIMEText(text, 'plain')
        part2 = MIMEText(html, 'html')
        msg.attach(part1)
        msg.attach(part2)

        # Send via Gmail SMTP
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.send_message(msg)

        print(f"✓ Email sent to {SEND_TO}")
        return True

    except Exception as e:
        print(f"✗ Error sending email: {e}")
        return False

def save_url_to_file(public_url):
    """Save URL to file for reference"""
    try:
        url_file = Path.home() / "Desktop" / "test" / "dashboard_public_url.txt"
        with open(url_file, 'w') as f:
            f.write(f"{public_url}\n")
            f.write(f"Updated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}\n")
            f.write(f"Valid for: 2 hours\n")
        print(f"✓ URL saved to {url_file}")
    except Exception as e:
        print(f"Warning: Could not save URL to file: {e}")

def main():
    """Auto-generated docstring."""
    print("=" * 50)
    print("  Ngrok Auto-Restart & Email Notifier")
    print("=" * 50)
    print(f"Started: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}")
    print()

    # Step 1: Kill existing ngrok
    print("1. Stopping existing ngrok tunnels...")
    kill_existing_ngrok()
    print("   ✓ Done")

    # Step 2: Start new ngrok
    print("2. Starting new ngrok tunnel...")
    if not start_ngrok():
        print("   ✗ Failed to start ngrok")
        return 1
    print("   ✓ Tunnel started")

    # Step 3: Get public URL
    print("3. Getting public URL...")
    max_retries = 5
    public_url = None

    for attempt in range(max_retries):
        public_url = get_public_url()
        if public_url:
            break
        time.sleep(2)

    if not public_url:
        print("   ✗ Failed to get public URL")
        return 1

    print(f"   ✓ URL: {public_url}")

    # Step 4: Save to file
    print("4. Saving URL to file...")
    save_url_to_file(public_url)

    # Step 5: Send email
    print("5. Sending email notification...")
    send_email(public_url)

    print()
    print("=" * 50)
    print("  ✓ Complete!")
    print("=" * 50)
    print(f"Access dashboard: {public_url}")
    print(f"Next update: In 2 hours")
    print()

    return 0

if __name__ == "__main__":
    exit(main())
