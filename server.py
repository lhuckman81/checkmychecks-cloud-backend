import os
import re
import smtplib
import pytesseract
import pdf2image
import cv2
import numpy as np
import requests
import google.auth
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from fpdf import FPDF
from flask import Flask, request, jsonify, send_file
from email.message import EmailMessage
from unidecode import unidecode
from datetime import datetime
from io import BytesIO

app = Flask(__name__)

# ✅ Load Email Credentials
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "info@mytips.pro")
EMAIL_AUTH_USER = os.getenv("EMAIL_AUTH_USER", "leif@mytips.pro")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
SMTP_SERVER = os.getenv("EMAIL_SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", 465))

# ✅ Google Drive API Authentication
SERVICE_ACCOUNT_FILE = "service_account.json"  # Ensure this file is in your project
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

def get_drive_service():
    """ Authenticate and return Google Drive service. """
    creds, _ = google.auth.load_credentials_from_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build("drive", "v3", credentials=creds)

def download_pdf_from_drive(file_id, output_path):
    """ Downloads a PDF from Google Drive using file ID. """
    try:
        service = get_drive_service()
        request = service.files().get_media(fileId=file_id)
        file = BytesIO()
        downloader = MediaIoBaseDownload(file, request)

        done = False
        while not done:
            _, done = downloader.next_chunk()

        with open(output_path, "wb") as f:
            f.write(file.getvalue())

        print(f"✅ File downloaded successfully: {output_path}")
        return True
    except Exception as e:
        print(f"❌ Failed to download PDF: {e}")
        return False

# ✅ OCR Extraction Function
def extract_text_from_pdf(pdf_path):
    """ Extracts text from the given PDF using OCR """
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

# ✅ Pay Stub Processing Route
@app.route("/process-paystub", methods=["POST"])
def process_paystub():
    try:
        data = request.json
        file_id = data.get("file_id")  # Expecting Google Drive File ID
        email = data.get("email")

        if not file_id or not email:
            return jsonify({"error": "Missing required fields"}), 400

        # ✅ Download PDF from Google Drive
        pdf_path = f"uploads/paystub_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        if not download_pdf_from_drive(file_id, pdf_path):
            return jsonify({"error": "Failed to download file from Google Drive"}), 500

        # ✅ Extract text from PDF
        extracted_text = extract_text_from_pdf(pdf_path)
        if not extracted_text:
            return jsonify({"error": "OCR failed to extract pay stub data"}), 500

        # ✅ Compliance Check (Same logic as before)
        employee_name_match = re.search(r"EMPLOYEE\s+([\w\s]+)", extracted_text)
        reported_wages_match = re.search(r"NET PAY:\s*\$([\d,]+.\d{2})", extracted_text)
        hours_match = re.search(r"Total Hours:\s*([\d.]+)", extracted_text)

        employee_name = employee_name_match.group(1).strip() if employee_name_match else "Unknown Employee"
        reported_wages = float(reported_wages_match.group(1).replace(",", "")) if reported_wages_match else 0.00
        total_hours = float(hours_match.group(1)) if hours_match else 0.00

        calculated_wages = reported_wages * 1.05
        tip_credit_valid = reported_wages >= 100
        overtime_valid = total_hours <= 40
        status = "✅ Wages Match!" if reported_wages == calculated_wages else "⚠️ Mismatch Detected!"

        # ✅ Generate PDF Report
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = f"paystub_report_{timestamp}.pdf"

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", style="", size=12)
        pdf.cell(200, 10, "Pay Stub Compliance Report", ln=True, align="L")
        pdf.ln(10)

        pdf.set_font("Arial", style="B", size=12)
        pdf.cell(200, 10, f"Employee: {clean_text(employee_name)}", ln=True)
        pdf.ln(5)

        pdf.set_font("Arial", style="B", size=10)
        pdf.cell(90, 10, "Expected Value", border=1, align="C")
        pdf.cell(90, 10, "Reported Value", border=1, align="C")
        pdf.ln()

        pdf.set_font("Arial", size=10)
        pdf.cell(90, 10, f"Calculated Wages: ${calculated_wages:.2f}", border=1, align="C")
        pdf.cell(90, 10, f"Reported Wages: ${reported_wages:.2f}", border=1, align="C")
        pdf.ln()

        pdf.cell(90, 10, "Tip Credit Compliance", border=1, align="C")
        pdf.cell(90, 10, "✅ Valid" if tip_credit_valid else "⚠️ Issue Detected", border=1, align="C")
        pdf.ln()

        pdf.cell(90, 10, "Overtime Compliance", border=1, align="C")
        pdf.cell(90, 10, "✅ Valid" if overtime_valid else "⚠️ Issue Detected", border=1, align="C")
        pdf.ln()

        pdf.set_font("Arial", style="B", size=12)
        pdf.cell(200, 10, f"Status: {clean_text(status)}", ln=True, align="L")

        pdf.output(report_path, "F")
        print(f"✅ PDF report generated: {report_path}")

        # ✅ Send Email with Report
        email_success = send_email_with_attachment(email, report_path)
        if not email_success:
            return jsonify({"error": "Report generated but email failed"}), 500

        return send_file(report_path, mimetype="application/pdf", as_attachment=True)

    except Exception as e:
        print(f"❌ ERROR: {e}")
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500

# ✅ Run Flask App
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
