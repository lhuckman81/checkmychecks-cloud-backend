import os
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
    data = request.json
    file_url = data.get("file_url")
    email = data.get("email")

    if not file_url:
        return jsonify({"error": "No file URL provided"}), 400

    # Simulate pay stub parsing & compliance check
    employee_name = "John Doe"
    reported_wages = 1500.00
    calculated_wages = 1525.00
    status = "✅ Wages Match!" if reported_wages == calculated_wages else "⚠️ Mismatch Detected!"

    # ✅ Generate PDF report
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt="Pay Stub Compliance Report", ln=True, align="C")
    pdf.cell(200, 10, txt=f"Employee: {employee_name}", ln=True)
    pdf.cell(200, 10, txt=f"Reported Wages: ${reported_wages}", ln=True)
    pdf.cell(200, 10, txt=f"Calculated Wages: ${calculated_wages}", ln=True)
    pdf.cell(200, 10, txt=f"Status: {status}", ln=True)
    
    pdf_path = "/tmp/paystub_report.pdf"
    pdf.output(pdf_path)

    # ✅ Send report as API response
return send_file(pdf_path, mimetype="application/pdf", as_attachment=True)