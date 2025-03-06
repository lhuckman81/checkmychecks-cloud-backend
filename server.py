import os
import re
import pytesseract
import pdf2image
import cv2
import numpy as np
from fpdf import FPDF
from flask import Flask, request, jsonify, send_file

app = Flask(__name__)

# ✅ Home route to check if the API is running
@app.route("/")
def home():
    return "Flask App is Running on Render!"

# ✅ Pay stub processing route
@app.route("/process-paystub", methods=["POST"])
def process_paystub():
    try:
        data = request.json
        file_url = data.get("file_url")
        email = data.get("email")

        if not file_url:
            return jsonify({"error": "No file URL provided"}), 400

        # Simulate pay stub parsing & compliance check
        employee_name = "John Doe"
        reported_wages = 1500.00
        calculated_wages = 1525.00
        tip_credit_valid = False  
        overtime_valid = True  
        status = "✅ Wages Match!" if reported_wages == calculated_wages else "⚠️ Mismatch Detected!"

        # ✅ Remove emojis and unsupported characters
        clean_status = re.sub(r'[^\x00-\x7F]+', '', status)

        # ✅ Set PDF Path
        pdf_path = os.path.join(os.getcwd(), "paystub_report.pdf")

        # ✅ Generate PDF report
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", style="", size=12)

        # ✅ Add Logo
        logo_path = "static/logo.png"  # Ensure this file exists!
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
        pdf.cell(200, 10, f"Employee: {employee_name}", ln=True)

        pdf.ln(5)  

        # ✅ Table Headers
        pdf.set_font("Arial", style="B", size=10)
        pdf.cell(90, 10, "Expected Value", border=1, align="C")
        pdf.cell(90, 10, "Reported Value", border=1, align="C")
        pdf.ln()

        # ✅ Table Data (Wages)
        pdf.set_font("Arial", size=10)
        pdf.cell(90, 10, f"Calculated Wages: ${calculated_wages}", border=1, align="C")
        pdf.cell(90, 10, f"Reported Wages: ${reported_wages}", border=1, align="C")
        pdf.ln()

        # ✅ Compliance Check - Tip Credit
        pdf.cell(90, 10, "Tip Credit Compliance", border=1, align="C")
        pdf.cell(90, 10, "✅ Valid" if tip_credit_valid else "⚠️ Issue Detected", border=1, align="C")
        pdf.ln()

        # ✅ Compliance Check - Overtime
        pdf.cell(90, 10, "Overtime Compliance", border=1, align="C")
        pdf.cell(90, 10, "✅ Valid" if overtime_valid else "⚠️ Issue Detected", border=1, align="C")
        pdf.ln()

        # ✅ Summary Status
        pdf.set_font("Arial", style="B", size=12)
        pdf.cell(200, 10, f"Status: {clean_status}", ln=True, align="L")

        # ✅ Save PDF
        pdf.output(pdf_path)

        # ✅ Debugging Log
        if not os.path.exists(pdf_path):
            print(f"❌ ERROR: PDF file was not created at {pdf_path}")
            return jsonify({"error": "PDF file was not generated"}), 500

        print(f"✅ PDF file exists at {pdf_path}, sending file...")

        # ✅ Return the PDF file
        return if not os.path.exists(pdf_path):
    print(f"❌ ERROR: PDF file was NOT created at {pdf_path}")
    return jsonify({"error": "PDF file was not generated"}), 500

# ✅ Check file size to ensure it's not empty
file_size = os.path.getsize(pdf_path)
if file_size < 500:  # Arbitrary threshold for a valid PDF
    print(f"❌ ERROR: PDF file is too small ({file_size} bytes). It may be corrupted.")
    return jsonify({"error": "PDF file is invalid"}), 500

print(f"✅ PDF file successfully created at {pdf_path} with size {file_size} bytes")
send_file(pdf_path, mimetype="application/pdf", as_attachment=True, cache_timeout=0)

    except Exception as e:
        print(f"❌ ERROR: {e}")
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500

# ✅ Ensure Flask runs correctly on Render
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)