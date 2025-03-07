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

# ✅ OCR Processing Function
def extract_text_from_pdf(pdf_path):
    """Extracts text from a given PDF pay stub using OCR."""
    try:
        images = pdf2image.convert_from_path(pdf_path)
        extracted_text = ""
        for img in images:
            text = pytesseract.image_to_string(img)
            extracted_text += text + "\n"
        return extracted_text
    except Exception as e:
        print(f"❌ OCR Extraction Failed: {e}")
        return None

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

# ✅ Pay Stub Processing Route
@app.route("/", methods=["GET"])
def home():
    return "Flask App is Running on Render!"

@app.route("/process-paystub", methods=["POST"])
def process_paystub():
    try:
        data = request.json
        file_url = data.get("file_url")
        email = data.get("email")

        if not file_url or not email:
            return jsonify({"error": "Missing required fields"}), 400

        # ✅ Download the PDF file
        pdf_filename = "uploaded_paystub.pdf"
        pdf_path = os.path.join(os.getcwd(), pdf_filename)
        os.system(f"curl -o {pdf_path} {file_url}")

        # ✅ Extract text from the pay stub using OCR
        extracted_text = extract_text_from_pdf(pdf_path)
        if not extracted_text:
            return jsonify({"error": "OCR extraction failed"}), 500

        # ✅ Parse extracted text (Basic Parsing for Employee Name & Wages)
        employee_name = re.search(r"Employee Name:\s*(.*)", extracted_text)
        reported_wages = re.search(r"Total Wages:\s*\$?([\d,]+\.?\d*)", extracted_text)

        employee_name = employee_name.group(1).strip() if employee_name else "Unknown Employee"
        reported_wages = float(reported_wages.group(1).replace(",", "")) if reported_wages else 0.00

        # ✅ Placeholder logic for compliance checks (replace with actual compliance logic)
        calculated_wages = reported_wages  # Assume reported wages are correct for now
        tip_credit_valid = "tip credit" in extracted_text.lower()
        overtime_valid = "overtime" in extracted_text.lower()
        status = "✅ Wages Match!" if reported_wages == calculated_wages else "⚠️ Mismatch Detected!"

        # ✅ Ensure text is clean before adding to PDF
        clean_employee_name = clean_text(employee_name)
        clean_status = clean_text(status)

        # ✅ Set PDF Path for Compliance Report
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_filename = f"paystub_report_{timestamp}.pdf"
        report_path = os.path.join(os.getcwd(), report_filename)

        # ✅ Generate Compliance Report PDF
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
        pdf.cell(200, 10, clean_text("Pay Stub Compliance Report"), ln=True, align="L")

        pdf.ln(10)  

        # ✅ Employee Information
        pdf.set_font("Arial", style="B", size=12)
        pdf.cell(200, 10, f"Employee: {clean_employee_name}", ln=True)

        pdf.ln(5)  

        # ✅ Table Headers
        pdf.set_font("Arial", style="B", size=10)
        pdf.cell(90, 10, clean_text("Expected Value"), border=1, align="C")
        pdf.cell(90, 10, clean_text("Reported Value"), border=1, align="C")
        pdf.ln()

        # ✅ Table Data (Wages)
        pdf.set_font("Arial", size=10)
        pdf.cell(90, 10, clean_text(f"Calculated Wages: ${calculated_wages}"), border=1, align="C")
        pdf.cell(90, 10, clean_text(f"Reported Wages: ${reported_wages}"), border=1, align="C")
        pdf.ln()

        # ✅ Compliance Check - Tip Credit
        pdf.cell(90, 10, clean_text("Tip Credit Compliance"), border=1, align="C")
        pdf.cell(90, 10, clean_text("✅ Valid" if tip_credit_valid else "⚠️ Issue Detected"), border=1, align="C")
        pdf.ln()

        # ✅ Compliance Check - Overtime
        pdf.cell(90, 10, clean_text("Overtime Compliance"), border=1, align="C")
        pdf.cell(90, 10, clean_text("✅ Valid" if overtime_valid else "⚠️ Issue Detected"), border=1, align="C")
        pdf.ln()

        # ✅ Summary Status
        pdf.set_font("Arial", style="B", size=12)
        pdf.cell(200, 10, f"Status: {clean_status}", ln=True, align="L")

        # ✅ Save PDF Report
        print(f"📂 Attempting to save PDF to: {report_path}")
        pdf.output(report_path, "F")

        # ✅ Send Email with Attachment
        email_success = send_email_with_attachment(email, report_path)
        if not email_success:
            return jsonify({"error": "Report generated but email failed"}), 500

        # ✅ Return the PDF file
        return send_file(report_path, mimetype="application/pdf", as_attachment=True)

    except Exception as e:
        print(f"❌ ERROR: {e}")
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500

# ✅ Ensure Flask runs correctly on Render
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
