import os
import re
import smtplib
import pytesseract
import pdf2image
import requests
import json
import cv2
import numpy as np
from fpdf import FPDF
from flask import Flask, request, jsonify, send_file
from email.message import EmailMessage
from unidecode import unidecode
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2 import service_account
from io import BytesIO

app = Flask(__name__)

# ✅ Load Email Credentials from Environment Variables
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "info@mytips.pro")
EMAIL_AUTH_USER = os.getenv("EMAIL_AUTH_USER", "leif@mytips.pro")  # Login email
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
SMTP_SERVER = os.getenv("EMAIL_SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", 465))

# ✅ Google Drive API Setup
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
SERVICE_ACCOUNT_FILE = "service_account.json"  # Replace with your service account JSON file

def get_drive_service():
    """Authenticate and return a Google Drive service instance."""
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)

def download_file_from_drive(file_id):
    """Download a file from Google Drive given its file ID."""
    try:
        service = get_drive_service()
        request = service.files().get_media(fileId=file_id)
        file_data = BytesIO()
        downloader = MediaIoBaseDownload(file_data, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        file_data.seek(0)
        return file_data
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

        # ✅ Handle Google Drive file downloads
        if "drive.google.com" in file_url:
            match = re.search(r"id=([a-zA-Z0-9_-]+)", file_url)
            if not match:
                return jsonify({"error": "Invalid Google Drive link format"}), 400

            file_id = match.group(1)
            file_data = download_file_from_drive(file_id)
            if not file_data:
                return jsonify({"error": "Failed to download file from Google Drive"}), 500

            pdf_path = f"uploads/paystub_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            with open(pdf_path, "wb") as f:
                f.write(file_data.read())
        else:
            # ✅ Download PDF from direct URL
            response = requests.get(file_url)
            if response.status_code != 200:
                return jsonify({"error": "Could not download file"}), 400

            pdf_path = f"uploads/paystub_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            with open(pdf_path, "wb") as f:
                f.write(response.content)

        # ✅ Extract text from PDF
        extracted_text = extract_text_from_pdf(pdf_path)
        if not extracted_text:
            return jsonify({"error": "OCR failed to extract pay stub data"}), 500

        # ✅ Extract relevant info using regex
        employee_name_match = re.search(r"EMPLOYEE\s+([\w\s]+)", extracted_text)
        reported_wages_match = re.search(r"NET PAY:\s*\$([\d,]+.\d{2})", extracted_text)
        hours_match = re.search(r"Total Hours:\s*([\d.]+)", extracted_text)

        employee_name = employee_name_match.group(1).strip() if employee_name_match else "Unknown Employee"
        reported_wages = float(reported_wages_match.group(1).replace(",", "")) if reported_wages_match else 0.00
        total_hours = float(hours_match.group(1)) if hours_match else 0.00

        # ✅ Compliance Check Logic
        calculated_wages = reported_wages * 1.05  # Simulated Calculation
        tip_credit_valid = reported_wages >= 100  # Fake check for demo
        overtime_valid = total_hours <= 40  # Fake check for demo
        status = "✅ Wages Match!" if reported_wages == calculated_wages else "⚠️ Mismatch Detected!"

        # ✅ Generate PDF Report
        pdf_filename = f"paystub_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        pdf_path = os.path.join(os.getcwd(), pdf_filename)

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", style="", size=12)

        # ✅ Title
        pdf.cell(200, 10, "Pay Stub Compliance Report", ln=True, align="L")
        pdf.ln(10)

        # ✅ Employee Information
        pdf.cell(200, 10, f"Employee: {clean_text(employee_name)}", ln=True)
        pdf.ln(5)

        # ✅ Compliance Summary
        pdf.cell(200, 10, f"Status: {clean_text(status)}", ln=True, align="L")

        # ✅ Save PDF
        pdf.output(pdf_path, "F")
        print(f"✅ PDF file successfully created at {pdf_path}")

        # ✅ Send Email with Attachment
        email_success = send_email_with_attachment(email, pdf_path)
        if not email_success:
            return jsonify({"error": "Report generated but email failed"}), 500

        return send_file(pdf_path, mimetype="application/pdf", as_attachment=True)

    except Exception as e:
        print(f"❌ ERROR: {e}")
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500

# ✅ Run Flask App
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
# Update timestamp
