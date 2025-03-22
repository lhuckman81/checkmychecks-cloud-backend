import os
import re
import json
import logging
import traceback
from datetime import datetime
from typing import Dict, Any, Optional

import requests
import PyPDF2
from flask import Flask, request, jsonify, send_file, redirect, url_for
from fpdf import FPDF
import email_validator
import numpy as np  # For more robust calculations
from flask_cors import CORS  # Add this import

# Google Cloud libraries
try:
    from google.cloud import storage
    from google.cloud import firestore
except ImportError:
    # Try alternate import path if the direct one fails
    from google.cloud.firestore_v1 import Client as firestore_client
    
    # Create a compatibility wrapper
    class FirestoreCompatibilityWrapper:
        def __init__(self):
            pass
            
        def Client(self):
            return firestore_client()
    
    # Create the compatibility module
    firestore = FirestoreCompatibilityWrapper()
from flask_mail import Mail, Message

# Configure logging
logging.basicConfig(
   level=logging.INFO,
   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
   handlers=[
       logging.FileHandler('paystub_processor.log'),
       logging.StreamHandler()
   ]
)
logger = logging.getLogger(__name__)

# Flask app initialization
app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Configure Flask-Mail
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'leif@mytips.pro'  # Update with your email
app.config['MAIL_PASSWORD'] = 'xgpb pqzk jedu brqk'     # Update with your app password
app.config['MAIL_DEFAULT_SENDER'] = 'info@mytips.pro'

mail = Mail(app)

# Initialize Firestore client
db = firestore.Client()

# Bucket ID
BUCKET_ID = "cs-poc-zgdkpqzt6vx3fwnl4kk8dky_cloudbuild"


class PaystubProcessor:
   def __init__(self, temp_dir='/tmp'):
       """
       Initialize the Paystub Processor with configuration
       
       :param temp_dir: Directory for temporary file storage
       """
       self.temp_dir = temp_dir
       os.makedirs(self.temp_dir, exist_ok=True)

   def validate_email(self, email: str) -> str:
       """
       Validate the email format.

       :param email: Email address to validate
       :return: Error message if invalid, otherwise empty string
       """
       # Basic email pattern
       email_pattern = r"^[a-zA-Z0-9._-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,6}$"
       
       if not re.match(email_pattern, email):
           return "Please enter a valid email address."
       return ""

   def download_pdf(self, file_url: str) -> Optional[str]:
       """
       Download PDF directly from Google Cloud Storage.
       
       :param file_url: The file URL within the GCS bucket
       :return: Path to the downloaded PDF or None if download fails
       """
       try:
           # Initialize Google Cloud Storage client
           client = storage.Client()
           bucket = client.bucket(BUCKET_ID)  # Match the Express.js bucket name
           blob = bucket.blob(file_url)  # file_url is now just the path inside the bucket

           # Create a temporary file path
           filename = os.path.join(self.temp_dir, file_url.split("/")[-1])

           # Download the file from GCS
           blob.download_to_filename(filename)

           logger.info(f"Successfully downloaded PDF from GCS: {filename}")
           return filename

       except Exception as e:
           logger.error(f"PDF download from GCS failed: {e}")
           return None

   def extract_pdf_text(self, pdf_path: str) -> str:
       """
       Extract text from PDF using PyPDF2 with improved error handling
       
       :param pdf_path: Path to PDF file
       :return: Extracted text or empty string on failure
       """
       try:
           # Verify file exists
           if not os.path.exists(pdf_path):
               logger.error(f"PDF file not found: {pdf_path}")
               return ""
               
           # Check file size
           file_size = os.path.getsize(pdf_path)
           if file_size == 0:
               logger.error(f"PDF file is empty: {pdf_path}")
               return ""
               
           # Check file is actually a PDF
           with open(pdf_path, 'rb') as file:
               header = file.read(5)
               if header != b'%PDF-':
                   logger.error(f"File is not a valid PDF: {pdf_path}")
                   return ""
                   
           # Process the PDF
           with open(pdf_path, 'rb') as file:
               try:
                   reader = PyPDF2.PdfReader(file)
                   if len(reader.pages) == 0:
                       logger.warning("PDF has no pages")
                       return ""
                       
                   text = ""
                   for page in reader.pages:
                       try:
                           page_text = page.extract_text()
                           text += page_text if page_text else ""
                       except Exception as e:
                           logger.warning(f"Error extracting text from page: {e}")
                           # Continue with next page
                   
                   if not text.strip():
                       logger.warning("No text extracted from PDF")
                   
                   return text
                   
               except PyPDF2.errors.PdfReadError as e:
                   logger.error(f"PDF read error: {e}")
                   return ""
                   
       except Exception as e:
           logger.error(f"Text extraction failed: {e}")
           logger.error(traceback.format_exc())
           return ""

   def parse_paystub_data(self, text: str) -> Dict[str, Any]:
       """
       Parse paystub data with improved error handling
       
       :param text: Extracted text from PDF
       :return: Dictionary of extracted information
       """
       if not text:
           logger.error("No text provided for parsing")
           return {}
           
       try:
           # More robust regex patterns with fallbacks
           patterns = {
               'employee_name': [
                   r"EMPLOYEE\s*NAME:\s*([\w\s]+)",
                   r"NAME:\s*([\w\s]+)",
                   r"EMPLOYEE:\s*([\w\s]+)"
               ],
               'net_pay': [
                   r"NET\s*PAY:\s*\$?([\d,]+\.\d{2})",
                   r"NET\s*PAY\s*\$?([\d,]+\.\d{2})",
                   r"TOTAL\s*NET\s*PAY:\s*\$?([\d,]+\.\d{2})"
               ],
               'total_hours': [
                   r"TOTAL\s*HOURS:\s*([\d.]+)",
                   r"HOURS\s*WORKED:\s*([\d.]+)",
                   r"HOURS:\s*([\d.]+)"
               ],
               'gross_pay': [
                   r"GROSS\s*PAY:\s*\$?([\d,]+\.\d{2})",
                   r"GROSS\s*EARNINGS:\s*\$?([\d,]+\.\d{2})",
                   r"TOTAL\s*GROSS:\s*\$?([\d,]+\.\d{2})"
               ]
           }

           results = {}
           for key, pattern_list in patterns.items():
               for pattern in pattern_list:
                   match = re.search(pattern, text, re.IGNORECASE)
                   if match:
                       value = match.group(1).replace(',', '')
                       try:
                           results[key] = float(value) if key != 'employee_name' else value.strip()
                           break  # Found a match, stop trying patterns
                       except ValueError:
                           logger.warning(f"Failed to convert {key} value: {value}")
                           continue
               
               if key not in results:
                   results[key] = None
                   logger.warning(f"Could not extract {key}")

           return results

       except Exception as e:
           logger.error(f"Paystub data parsing failed: {e}")
           logger.error(traceback.format_exc())
           return {}

   def perform_compliance_checks(self, data: Dict[str, Any]) -> Dict[str, bool]:
       """
       Perform compliance checks on extracted data
       
       :param data: Extracted paystub data
       :return: Dictionary of compliance check results
       """
       checks = {
           'minimum_wage': False,
           'overtime_compliant': False,
           'total_compensation_valid': False
       }

       # Actual compliance logic (replace with your specific requirements)
       if data.get('net_pay') and data.get('total_hours'):
           # Example checks - customize for your specific use case
           checks['minimum_wage'] = (data['net_pay'] / data['total_hours']) >= 15.0
           checks['overtime_compliant'] = data['total_hours'] <= 40
           checks['total_compensation_valid'] = (
               data.get('net_pay', 0) > 0 and 
               data.get('gross_pay', 0) > 0
           )

       return checks

   def generate_compliance_report(
       self, 
       employee_data: Dict[str, Any], 
       compliance_results: Dict[str, bool]
   ) -> str:
       """
       Generate PDF compliance report
       
       :param employee_data: Employee data dictionary
       :param compliance_results: Compliance check results
       :return: Path to generated PDF report
       """
       pdf = FPDF()
       pdf.add_page()
       pdf.set_font("Arial", size=12)

       # Report Title
       pdf.cell(0, 10, "Pay Stub Compliance Report", ln=True, align='C')
       pdf.ln(10)

       # Employee Information
       pdf.cell(0, 10, f"Employee: {employee_data.get('employee_name', 'Unknown')}", ln=True)
       pdf.ln(5)

       # Compliance Checks
       pdf.cell(0, 10, "Compliance Check Results:", ln=True)
       for check, result in compliance_results.items():
           status = "✅ Passed" if result else "❌ Failed"
           pdf.cell(0, 10, f"{check.replace('_', ' ').title()}: {status}", ln=True)

       # Output the PDF
       report_path = os.path.join(
           self.temp_dir, 
           f"compliance_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
       )
       pdf.output(report_path)
       logger.info(f"Compliance report generated: {report_path}")
       return report_path

   def send_email_report(self, email: str, report_path: str) -> bool:
       """
       Send email with compliance report using Gmail's SMTP server
       """
       try:
           msg = Message(
               "Your Compliance Report",
               sender="info@mytips.pro",  # Your 'from' email address
               recipients=[email],
               body="Please find your compliance report attached.",
           )
           
           # Attach the report as a PDF file
           with open(report_path, "rb") as f:
               msg.attach("compliance_report.pdf", "application/pdf", f.read())

           # Send the email via Gmail's SMTP server
           mail.send(msg)
           logger.info(f"Email sent to {email} with report {report_path}")
           return True
       except Exception as e:
           logger.error(f"Email sending failed: {e}")
           return False

   def update_processing_status(self, file_url, email, status, message=""):
       """
       Update processing status in Firestore
       
       :param file_url: The file URL being processed
       :param email: User's email address
       :param status: Current status (processing, completed, failed)
       :param message: Optional status message
       """
       try:
           doc_ref = db.collection('processing_status').document(f"{file_url.replace('/', '_')}")
           doc_ref.set({
               'file_url': file_url,
               'email': email,
               'status': status,
               'message': message,
               'updated_at': firestore.SERVER_TIMESTAMP
           })
           logger.info(f"Updated status for {file_url} to {status}")
           return True
       except Exception as e:
           logger.error(f"Failed to update status: {e}")
           return False

   def cleanup_files(self, *file_paths):
       """ Remove temporary files after processing """
       for file_path in file_paths:
           try:
               if file_path and os.path.exists(file_path):
                   os.remove(file_path)
                   logger.info(f"Removed file: {file_path}")
           except Exception as e:
               logger.error(f"Error removing file {file_path}: {e}")


@app.route("/", methods=["GET"])
def health_check():
   """
   Simple health check endpoint for Cloud Run
   """
   return jsonify({"status": "healthy"}), 200


@app.route("/upload-paystub", methods=["POST"])
def upload_paystub():
   """
   Upload paystub file to Google Cloud Storage
   """
   try:
       if 'file' not in request.files:
           logger.error("No file part in the request")
           return jsonify({"error": "No file part"}), 400
           
       file = request.files['file']
       email = request.form.get('email')
       
       if not file or file.filename == '':
           logger.error("No file selected")
           return jsonify({"error": "No file selected"}), 400
           
       if not email:
           logger.error("Email is required")
           return jsonify({"error": "Email is required"}), 400
           
       # Validate email
       processor = PaystubProcessor()
       email_error = processor.validate_email(email)
       if email_error:
           logger.error(f"Invalid email format: {email}")
           return jsonify({"error": email_error}), 400
           
       # Save to GCS
       logger.info(f"Starting upload to GCS for file: {file.filename}")
       client = storage.Client()
       bucket = client.bucket(BUCKET_ID)
       
       # Create a unique filename
       filename = f"paystub_uploads/{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
       blob = bucket.blob(filename)
       
       # Upload the file
       blob.upload_from_file(file)
       logger.info(f"File uploaded to GCS: {filename}")
       
       # Initiate processing asynchronously
       # For now, just return success and file URL
       return jsonify({
           "message": "File uploaded successfully",
           "file_url": filename,
           "email": email,
           "status": "processing"
       })
       
   except Exception as e:
       logger.error(f"File upload failed: {e}")
       logger.error(traceback.format_exc())
       return jsonify({"error": "File upload failed", "details": str(e)}), 500


@app.route("/process-paystub", methods=["POST"])
def process_paystub():
    try:
        data = request.get_json()
        if not data or "file_url" not in data or "email" not in data:
            logger.error("Missing required fields in process request")
            return jsonify({"error": "Missing required fields"}), 400

        processor = PaystubProcessor()
        file_url = data['file_url']
        email = data['email']
        
        # Set initial status
        processor.update_processing_status(file_url, email, "processing", "Started processing paystub")

        # Validate email
        email_error = processor.validate_email(email)
        if email_error:
            processor.update_processing_status(file_url, email, "failed", email_error)
            return jsonify({"error": email_error}), 400

        # Download PDF from GCS
        logger.info(f"Downloading PDF from GCS: {file_url}")
        pdf_path = processor.download_pdf(file_url)
        if not pdf_path:
            processor.update_processing_status(file_url, email, "failed", "PDF download failed")
            return jsonify({"error": "PDF download failed from GCS"}), 400

        # Extract text from the PDF
        logger.info(f"Extracting text from PDF: {pdf_path}")
        extracted_text = processor.extract_pdf_text(pdf_path)
        if not extracted_text:
            processor.update_processing_status(file_url, email, "failed", "Text extraction failed")
            return jsonify({"error": "Text extraction failed"}), 400

        # Parse paystub data
        logger.info("Parsing paystub data")
        paystub_data = processor.parse_paystub_data(extracted_text)
        if not paystub_data:
            processor.update_processing_status(file_url, email, "failed", "Unable to parse paystub data")
            return jsonify({"error": "Unable to parse pay stub data"}), 400

        # Perform compliance checks
        logger.info("Performing compliance checks")
        compliance_results = processor.perform_compliance_checks(paystub_data)

        # Generate compliance report
        logger.info("Generating compliance report")
        report_path = processor.generate_compliance_report(paystub_data, compliance_results)
        
        # Check if report was generated
        if not os.path.exists(report_path):
            processor.update_processing_status(file_url, email, "failed", "Failed to generate report")
            return jsonify({"error": "Failed to generate the compliance report"}), 500

        # Send email with the report
        logger.info(f"Sending email report to: {email}")
        email_sent = processor.send_email_report(email, report_path)
        if not email_sent:
            processor.update_processing_status(file_url, email, "failed", "Failed to send email")
            return jsonify({"error": "Failed to send email"}), 500

        # Update status on success
        processor.update_processing_status(file_url, email, "completed", "Report sent via email")
        
        # Cleanup the temporary files
        processor.cleanup_files(pdf_path, report_path)

        return jsonify({
            'message': 'Paystub processed and report sent successfully.',
            'email': email,
            'status': 'completed'
        })

    except Exception as e:
        # Update status on failure
        if 'file_url' in locals() and 'email' in locals():
            processor.update_processing_status(file_url, email, "failed", str(e))
        logger.error(f"Unexpected error: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500


@app.route("/check-status", methods=["GET"])
def check_status():
    file_url = request.args.get('file_url')
    if not file_url:
        return jsonify({"error": "Missing file_url parameter"}), 400

    try:
        # Get status from Firestore
        doc_ref = db.collection('processing_status').document(f"{file_url.replace('/', '_')}")
        doc = doc_ref.get()
        
        if doc.exists:
            data = doc.to_dict()
            return jsonify({
                "file_url": file_url,
                "status": data.get("status", "unknown"),
                "message": data.get("message", "")
            })
        else:
            return jsonify({
                "file_url": file_url,
                "status": "unknown",
                "message": "No status found for this file"
            })
    except Exception as e:
        logger.error(f"Status check error: {e}")
        return jsonify({"error": "Failed to check status", "details": str(e)}), 500


if __name__ == "__main__":
   app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))