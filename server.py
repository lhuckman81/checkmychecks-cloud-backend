import os
import re
import smtplib
import pytesseract
import pdf2image
import cv2
import numpy as np
from fpdf import FPDF
from flask import Flask, request, jsonify, send_file
from email.message import EmailMessage
from unidecode import unidecode  # Ensure this is installed in requirements.txt

app = Flask(__name__)

# ✅ Load Email Credentials from Render Environment Variables
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "info@mytips.pro")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
SMTP_SERVER = os.getenv("EMAIL_SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", 465))

# ✅ Helper function to clean text (removes unsupported characters)
def clean_text(text):
    """ Remove unsupported characters and force ASCII encoding """
    return unidecode(str(text))  # Converts special characters to closest ASCII match

# ✅ Email Sending Function
def send_email_with_attachment(to_email, pdf_path):
    try:
        msg = EmailMessage()
        msg["Subject"] = "Your Pay Stub Compliance Report"
        msg["From"] = EMAIL_SENDER
        msg["To"] = to_email
        msg.set_content("Attached is your compliance report. Please review it.")

        with open(pdf_path, "rb") as f:
            msg.add_attachment(f.read(), maintype="application", subtype="pdf", filename=os.path.basename(pdf_path))

        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)

        print(f"✅ Email sent successfully to {to_email}")
        return True
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        return False

#