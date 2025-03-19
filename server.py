import os
import re
import smtplib
import pytesseract
import pdf2image
import requests
import json
import cv2
import numpy as np
import tempfile  # ✅ Added to fix PDF file storage
from fpdf import FPDF
from flask import Flask, request, jsonify, send_file
from email.message import EmailMessage
from unidecode import unidecode
from datetime import datetime
from io import BytesIO

app = Flask(__name__)

# ✅ Email Credentials from Environment Variables
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "info@mytips.pro")
EMAIL_AUTH_USER = os.getenv("EMAIL_AUTH_USER", "leif@mytips.pro")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
SMTP_SERVER = os.getenv("EMAIL_SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", 465))

# ✅ Google Drive API Setup via OIDC Token
OIDC_TOKEN_PATH = "/var/run/secrets/tokens/oidc-token"
DRIVE_API_URL = "https://www.googleapis.com/drive/v3/files"

def get_oidc_token():
    """Retrieve OIDC token for authentication."""
    try:
        with open(OIDC_TOKEN_PATH, "r") as token_file:
            return token_file.read().strip()
    except Exception as e:
        print(f"❌ Error reading OIDC token: {e}")
        return None

def download_file_from_drive(file_id):
    """Download a file from Google Drive using OIDC authentication."""
    try:
        oidc_token = get_oidc_token()
        if not oidc_token:
            return None

        headers = {"Authorization": f"Bearer {oidc_token}"}
        download_url = f"{DRIVE_API_URL}/{file_id}?alt=media"
        
        response = requests.get(download_url, headers=headers)
        if response.status_code != 200:
            print(f"❌ Failed to download file from Google Drive: {response.text}")
            return None

        return BytesIO(response.content)
    except Exception as e:
        print(f"❌ Error downloading file from Drive: {e}")
        return None

# ✅ Helper function to clean text
def clean_text(text):
    """Remove unsupported characters and force ASCII encoding."""
    return unidecode(str(text))

# ✅ OCR Extraction Function
def extract_text_from_pdf(pdf_path):
    """Extract text from the given PDF using OCR."""
    try:
        print(f"📄 Processing PDF: {pdf_path}")
        images = pdf2image.convert_from_path(pdf_path)
        extracted_text = ""

        for i, image in enumerate(images):
            print(f"📸 Extracting text from page {i+1}...")
            text = pytesseract.image_to_string(image)
            extracted_text += text + "\n"

        print(f"✅ OCR Extraction Complete!")
        return extracted_text
    except Exception as e:
        print(f"❌ OCR Extraction Failed: {e}")
        return None

# ✅ Email Sending Function
def send_email_with_attachment(to_email, pdf_path):
    """Sends an email with the compliance report attached."""
    try:
        msg = EmailMessage()
        msg["Subject"] = "Your Pay Stub Compliance Report"
        msg["From"] = EMAIL_SENDER
        msg["To"] = to_email
        msg.set_content("Attached is your compliance report. Please review it.")

        with open(pdf_path, "rb") as f:
            msg.add_attachment(f.read(), maintype="application", subtype="pdf", filename=os.path.basename(pdf_path))

        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(EMAIL_AUTH_USER, EMAIL_PASSWORD)
            server.send_message(msg)

        print(f"✅ Email sent successfully to {to_email}")
        return True
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
        return False

# ✅ Pay Stub Processing Route
@app.route("/process-paystub", methods=["POST"])
def process_paystub():
    try:
        data = request.get_json()
        print(f"📝 Received data: {json.dumps(data, indent=2)}")  # Debugging line

        if not data or "file_url" not in data or "email" not in data:
            return jsonify({"error": "Missing required fields"}), 400

        file_url = data["file_url"]
        email = data["email"]

        temp_dir = tempfile.gettempdir()  # ✅ Cross-platform temp directory

        # ✅ Handle Google Drive file downloads
        if "drive.google.com" in file_url:
            match = re.search(r"id=([a-zA-Z0-9_-]+)", file_url)
            if not match:
                return jsonify({"error": "Invalid Google Drive link format"}), 400

            file_id = match.group(1)
            file_data = download_file_from_drive(file_id)
            if not file_data:
                return jsonify({"error": "Failed to download file from Google Drive"}), 500

            pdf_path = os.path.join(temp_dir, f"paystub_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
            with open(pdf_path, "wb") as f:
                f.write(file_data.read())
        else:
            # ✅ Download PDF from direct URL
            response = requests.get(file_url)
            if response.status_code != 200:
                return jsonify({"error": "Could not download file"}), 400

            pdf_path = os.path.join(temp_dir, f"paystub_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
            with open(pdf_path, "wb") as f:
                f.write(response.content)

        # ✅ Extract text from PDF
        extracted_text = extract_text_from_pdf(pdf_path)
        if not extracted_text:
            return jsonify({"error": "OCR failed to extract pay stub data"}), 500

        # ✅ Extract relevant info using regex
        employee_name_match = re.search(r"EMPLOYEE[:\s]+([\w\s]+)", extracted_text, re.IGNORECASE)
        reported_wages_match = re.search(r"NET PAY:\s*\$([\d,]+.\d{2})", extracted_text)
        hours_match = re.search(r"Total Hours:\s*([\d.]+)", extracted_text)

        employee_name = employee_name_match.group(1).strip() if employee_name_match else "Unknown Employee"
        reported_wages = float(reported_wages_match.group(1).replace(",", "")) if reported_wages_match else 0.00
        total_hours = float(hours_match.group(1)) if hours_match else 0.00

        # ✅ Compliance Check Logic (Needs a real formula)
        calculated_wages = reported_wages * 1.05  # Placeholder logic
        status = "✅ Wages Match!" if reported_wages == calculated_wages else "⚠️ Mismatch Detected!"

        # ✅ Generate PDF Report
        pdf_filename = os.path.join(temp_dir, f"paystub_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf")
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        pdf.cell(200, 10, "Pay Stub Compliance Report", ln=True, align="L")
        pdf.cell(200, 10, f"Employee: {clean_text(employee_name)}", ln=True)
        pdf.cell(200, 10, f"Status: {clean_text(status)}", ln=True)
        pdf.output(pdf_filename, "F")

        email_success = send_email_with_attachment(email, pdf_filename)
        if not email_success:
            return jsonify({"error": "Report generated but email failed"}), 500

        return send_file(pdf_filename, mimetype="application/pdf", as_attachment=True)

    except Exception as e:
        print(f"❌ ERROR: {e}")
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
