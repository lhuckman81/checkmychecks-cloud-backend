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

# Google OAuth Libraries
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
import pathlib
from google.cloud import storage
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

# Configure Flask-Mail
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'your-email@gmail.com'  # Update with your email
app.config['MAIL_PASSWORD'] = 'your-app-password'     # Update with your app password
app.config['MAIL_DEFAULT_SENDER'] = 'info@mytips.pro'

mail = Mail(app)

# OAuth credentials setup
CLIENT_SECRETS_FILE = "client_secret.json"  # Path to your OAuth client secret JSON file
SCOPES = ['https://www.googleapis.com/auth/gmail.send']  # Permission to send emails
REDIRECT_URI = 'https://checkmychecks.com/oauth2callback'  # Your OAuth2 callback URL

# Create OAuth flow object
flow = Flow.from_client_secrets_file(
    CLIENT_SECRETS_FILE,
    scopes=SCOPES,
    redirect_uri=REDIRECT_URI
)

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
        Extract text from PDF using PyPDF2
        
        :param pdf_path: Path to PDF file
        :return: Extracted text
        """
        try:
            with open(pdf_path, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                text = ""
                for page in reader.pages:
                    text += page.extract_text()
            
            if not text.strip():
                logger.warning("No text extracted from PDF")
            
            return text
        except Exception as e:
            logger.error(f"Text extraction failed: {e}")
            return ""

    def parse_paystub_data(self, text: str) -> Dict[str, Any]:
        """
        Parse paystub data using regex
        
        :param text: Extracted text from PDF
        :return: Dictionary of extracted information
        """
        try:
            # More robust regex patterns
            patterns = {
                'employee_name': r"EMPLOYEE\s*NAME:\s*([\w\s]+)",
                'net_pay': r"NET\s*PAY:\s*\$?([\d,]+\.\d{2})",
                'total_hours': r"TOTAL\s*HOURS:\s*([\d.]+)",
                'gross_pay': r"GROSS\s*PAY:\s*\$?([\d,]+\.\d{2})"
            }

            results = {}
            for key, pattern in patterns.items():
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    value = match.group(1).replace(',', '')
                    results[key] = float(value) if key != 'employee_name' else value.strip()
                else:
                    results[key] = None
                    logger.warning(f"Could not extract {key}")

            return results

        except Exception as e:
            logger.error(f"Paystub data parsing failed: {e}")
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

    def cleanup_files(self, *file_paths):
        """ Remove temporary files after processing """
        for file_path in file_paths:
            try:
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"Removed file: {file_path}")
            except Exception as e:
                logger.error(f"Error removing file {file_path}: {e}")


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
    """
    Process pay stub PDF
    """
    try:
        data = request.get_json()
        if not data or "file_url" not in data or "email" not in data:
            logger.error("Missing required fields in process request")
            return jsonify({"error": "Missing required fields"}), 400

        processor = PaystubProcessor()

        # Validate email
        email_error = processor.validate_email(data['email'])
        if email_error:
            logger.error(f"Invalid email format: {data['email']}")
            return jsonify({"error": email_error}), 400

        # Download PDF from GCS
        logger.info(f"Downloading PDF from GCS: {data['file_url']}")
        pdf_path = processor.download_pdf(data['file_url'])
        if not pdf_path:
            logger.error(f"PDF download failed from GCS: {data['file_url']}")
            return jsonify({"error": "PDF download failed from GCS"}), 400

        # Extract text from the PDF
        logger.info(f"Extracting text from PDF: {pdf_path}")
        extracted_text = processor.extract_pdf_text(pdf_path)
        if not extracted_text:
            logger.error("Text extraction failed")
            return jsonify({"error": "Text extraction failed"}), 400

        # Parse paystub data
        logger.info("Parsing paystub data")
        paystub_data = processor.parse_paystub_data(extracted_text)
        if not paystub_data:
            logger.error("Unable to parse pay stub data")
            return jsonify({"error": "Unable to parse pay stub data"}), 400

        # Perform compliance checks
        logger.info("Performing compliance checks")
        compliance_results = processor.perform_compliance_checks(paystub_data)

        # Generate compliance report
        logger.info("Generating compliance report")
        report_path = processor.generate_compliance_report(paystub_data, compliance_results)
        
        # Check if report was generated
        if not os.path.exists(report_path):
            logger.error("Failed to generate the compliance report")
            return jsonify({"error": "Failed to generate the compliance report"}), 500

        # Send email with the report
        logger.info(f"Sending email report to: {data['email']}")
        email_sent = processor.send_email_report(data['email'], report_path)
        if not email_sent:
            logger.error(f"Failed to send email to: {data['email']}")
            return jsonify({"error": "Failed to send email"}), 500

        # Cleanup the temporary files
        processor.cleanup_files(pdf_path, report_path)

        return jsonify({
            'message': 'Paystub processed and report sent successfully.',
            'email': data['email'],
            'status': 'completed'
        })

    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Internal Server Error", "details": str(e)}), 500


@app.route("/check-status", methods=["GET"])
def check_status():
    """
    Check the status of a paystub processing job
    """
    file_url = request.args.get('file_url')
    if not file_url:
        return jsonify({"error": "Missing file_url parameter"}), 400

    # In a real application, you would check a database or task queue
    # For now, we'll just return a mock status
    return jsonify({
        "file_url": file_url,
        "status": "completed",  # or "processing", "failed"
        "message": "Check your email for the report."
    })


if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))