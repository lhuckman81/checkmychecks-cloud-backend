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
from unidecode import unidecode
from datetime import datetime
import requests

app = Flask(__name__)

# ✅ Ensure uploads directory exists
UPLOADS_DIR = "uploads"
os.makedirs(UPLOADS_DIR, exist_ok=True)

# ✅ Load Email Credentials from Environment Variables
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "info@mytips.pro")
EMAIL_AUTH_USER = os.getenv("EMAIL_AUTH_USER", "leif@mytips.pro")  # Login email
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
SMTP_SERVER = os.getenv("EMAIL_SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", 465))

# ✅ Helper function to clean text (removes unsupported characters)
def clean_text(text):
    """ Remove unsupported characters and force ASCII encoding """
    return unidecode(str(text))

# ✅ Function to download the uploaded file
def download_pdf(file_url, save_path):
    """ Downloads the pay stub from a given URL """
    try:
        response = requests.get(file_url)
        if response.status_code == 200:
            with open(save_path, "wb") as f:
                f.write(response.content)
            print(f"✅ File downloaded successfully: {save_path}")
            return True
        else:
            print(f"❌ Failed to download file: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error downloading file: {e}")
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

        print(f"✅ OCR Extraction Complete! Extracted Text:\n{text}")
        return extracted_text
    except Exception as e:
        print(f"❌ OCR Extraction Failed: {e}")
        return None

# ✅ Email Sending Function
def send_email_with_attachment(to_email, pdf_path):
    """ Sends an email with the compliance report attached """
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
        data = request.json
        file_url = data.get("file_url")
        email = data.get("email")

        if not file_url or not email:
            return jsonify({"error": "Missing required fields"}), 400

        # ✅ Define file path
        pdf_filename = f"uploaded_paystub_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        pdf_path = os.path.join(UPLOADS_DIR, pdf_filename)

        # ✅ Download the uploaded pay stub
        if not download_pdf(file_url, pdf_path):
            return jsonify({"error": "Failed to download pay stub"}), 500

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
        report_filename = f"paystub_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        report_path = os.path.join(os.getcwd(), report_filename)

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", style="", size=12)

        # ✅ Add Logo (if available)
        logo_path = "static/checkmychecks_logo.png"
        if os.path.exists(logo_path):
            pdf.image(logo_path, x=10, y=8, w=40)
        else:
            print("⚠️ WARNING: Logo file not found, skipping logo.")

        # ✅ Title
        pdf.set_xy(60, 10)
        pdf.set_font("Arial", style="B", size=16)
        pdf.cell(200, 10, "Pay Stub Compliance Report", ln=True, align="L")
        pdf.ln(10)

        # ✅ Employee Information
        pdf.set_font("Arial", style="B", size=12)
        pdf.cell(200, 10, f"Employee: {clean_text(employee_name)}", ln=True)
        pdf.ln(5)

        # ✅ Summary Status
        pdf.set_font("Arial", style="B", size=12)
        pdf.cell(200, 10, f"Status: {clean_text(status)}", ln=True, align="L")

        # ✅ Save PDF
        pdf.output(report_path, "F")
        print(f"✅ PDF file successfully created at {report_path}")

        # ✅ Send Email with Attachment
        email_success = send_email_with_attachment(email, report_path)
        if not email_success:
            return jsonify({"error": "Report generated but email failed"}), 500

        return send_file(report_path, mimetype="application/pdf", as_attachment=True)

    except Exception as e:
        print(f"❌ ERROR: {e}")
    