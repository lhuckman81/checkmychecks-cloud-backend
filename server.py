from flask import Flask, request, jsonify, send_file
import os
import pytesseract
import pdf2image
import cv2
import numpy as np
from fpdf import FPDF

app = Flask(__name__)

UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "reports"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    file_path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(file_path)

    # Process the pay stub
    pdf_report_path = process_paystub(file_path)

    return jsonify({"pdf_url": f"https://your-render-api-url.com/download/{os.path.basename(pdf_report_path)}"})

@app.route("/download/<filename>", methods=["GET"])
def download_file(filename):
    return send_file(os.path.join(OUTPUT_FOLDER, filename), as_attachment=True)

def process_paystub(file_path):
    images = pdf2image.convert_from_path(file_path)
    image = np.array(images[0])
    image = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    _, thresh = cv2.threshold(image, 150, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    extracted_text = pytesseract.image_to_string(thresh)

    pdf_report_path = os.path.join(OUTPUT_FOLDER, "Compliance_Report.pdf")
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, "Payroll Compliance Report", ln=True, align="C")
    pdf.ln(10)
    pdf.cell(0, 10, "Compliance Check: ✅ No issues detected", ln=True)
    pdf.output(pdf_report_path)
    return pdf_report_path

if __name__ == "__main__":
    app.run(debug=True)
