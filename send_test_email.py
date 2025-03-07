import smtplib
import os
from email.message import EmailMessage

# ✅ Load Email Credentials
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "info@mytips.pro")
EMAIL_AUTH_USER = os.getenv("EMAIL_AUTH_USER", "leif@mytips.pro")  # Use for login
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")  # App Password from Google
SMTP_SERVER = os.getenv("EMAIL_SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", 465))

def send_test_email():
    try:
        print("📨 Starting email test...")

        # ✅ Create the email
        msg = EmailMessage()
        msg["Subject"] = "SMTP Test Email"
        msg["From"] = EMAIL_SENDER
        msg["To"] = "your-real-email@gmail.com"  # Update with a real test email
        msg.set_content("This is a test email from CheckMyChecks.")

        print("🔗 Connecting to SMTP server...")

        # ✅ Connect to SMTP Server
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            print("🔑 Logging in...")
            server.login(EMAIL_AUTH_