import os
import re
import json
import uuid
import logging
import traceback
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional

import requests
import PyPDF2
from flask import Flask, request, jsonify, send_file, redirect, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from fpdf import FPDF
import email_validator
import numpy as np
from flask_cors import CORS
from werkzeug.utils import secure_filename

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

# Constants
MINIMUM_WAGE = float(os.getenv('MINIMUM_WAGE', '15.0'))
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB max file size
ALLOWED_EXTENSIONS = {'pdf'}

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

# Add rate limiting
limiter = Limiter(
    app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Configure Flask-Mail
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', '587'))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True').lower() in ['true', '1', 't']
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER', 'info@mytips.pro')

mail = Mail(app)

# Initialize Firestore client
db = firestore.Client()

# Bucket ID
BUCKET_ID = os.getenv('BUCKET_ID', "cs-poc-zgdkpqzt6vx3fwnl4kk8dky_cloudbuild")


class StorageService:
    """Service for handling Google Cloud Storage operations"""
    
    def __init__(self, bucket_id: str):
        """Initialize the storage service
        
        Args:
            bucket_id: Google Cloud Storage bucket ID
        """
        self.bucket_id = bucket_id
        self.client = storage.Client()
        self.bucket = self.client.bucket(bucket_id)
    
    def upload_file(self, file, path_prefix: str = "") -> str:
        """Upload a file to Google Cloud Storage
        
        Args:
            file: File object to upload
            path_prefix: Optional path prefix for the file
            
        Returns:
            The path of the uploaded file
        """
        try:
            # Create a unique filename with secure name
            safe_filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{path_prefix}/{timestamp}_{safe_filename}"
            
            # Upload the file
            blob = self.bucket.blob(filename)
            blob.upload_from_file(file)
            
            logger.info(f"File uploaded to GCS: {filename}")
            return filename
        except Exception as e:
            logger.error(f"File upload failed: {e}")
            raise
    
    def download_file(self, file_url: str, destination: str) -> str:
        """Download a file from Google Cloud Storage
        
        Args:
            file_url: The path to the file in the bucket
            destination: The local directory to download to
            
        Returns:
            The path to the downloaded file
        """
        try:
            # Get just the filename part
            filename = os.path.basename(file_url)
            local_path = os.path.join(destination, filename)
            
            # Download the file
            blob = self.bucket.blob(file_url)
            blob.download_to_filename(local_path)
            
            logger.info(f"Downloaded file from GCS: {local_path}")
            return local_path
        except Exception as e:
            logger.error(f"File download failed: {e}")
            raise


class PaystubProcessor:
    def __init__(self, temp_dir: str = '/tmp'):
        """Initialize the Paystub Processor
        
        Args:
            temp_dir: Directory for temporary file storage
        """
        self.temp_dir = temp_dir
        os.makedirs(self.temp_dir, exist_ok=True)
        self.storage_service = StorageService(BUCKET_ID)

    def validate_email(self, email: str) -> str:
        """Validate the email using email_validator library
        
        Args:
            email: Email address to validate
            
        Returns:
            Error message if invalid, otherwise empty string
        """
        try:
            email_validator.validate_email(email)
            return ""
        except email_validator.EmailNotValidError as e:
            return str(e)

    def validate_file(self, file) -> str:
        """Validate the uploaded file
        
        Args:
            file: File object to validate
            
        Returns:
            Error message if invalid, otherwise empty string
        """
        if not file or file.filename == '':
            return "No file selected"
            
        # Check file extension
        ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
        if ext not in ALLOWED_EXTENSIONS:
            return f"Only {', '.join(ALLOWED_EXTENSIONS)} files are allowed"
            
        # Check file size
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)  # Reset file pointer
        
        if size > MAX_FILE_SIZE:
            return f"File size exceeds {MAX_FILE_SIZE / (1024 * 1024)}MB limit"
            
        return ""

    def download_pdf(self, file_url: str) -> Optional[str]:
        """Download PDF from Google Cloud Storage
        
        Args:
            file_url: The file URL within the GCS bucket
            
        Returns:
            Path to the downloaded PDF or None if download fails
        """
        try:
            return self.storage_service.download_file(file_url, self.temp_dir)
        except Exception as e:
            logger.error(f"PDF download from GCS failed: {e}")
            return None

    def extract_pdf_text(self, pdf_path: str) -> str:
        """Extract text from PDF with robust error handling
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Extracted text or empty string on failure
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
        """Parse paystub data with robust error handling
        
        Args:
            text: Extracted text from PDF
            
        Returns:
            Dictionary of extracted information
        """
        if not text:
            logger.error("No text provided for parsing")
            return {}
            
        results = {}  # Initialize results here before the try block
        try:
            # Robust regex patterns with fallbacks
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

        except Exception as e:
            logger.error(f"Paystub data parsing failed: {e}")
            logger.error(traceback.format_exc())
        
        return results

    def is_total_compensation_valid(self, net_pay: float, gross_pay: float) -> bool:
        """Check if total compensation is valid.
        
        Args:
            net_pay: Net pay amount
            gross_pay: Gross pay amount
            
        Returns:
            True if both net_pay and gross_pay are greater than 0, otherwise False
        """
        return net_pay > 0 and gross_pay > 0

    def perform_compliance_checks(self, data: Dict[str, Any]) -> Dict[str, bool]:
        """Perform compliance checks on paystub data.
        
        Args:
            data: Dictionary containing paystub data
            
        Returns:
            Dictionary with compliance check results
        """
        checks = {
            'minimum_wage': False,
            'overtime_compliant': False,
            'total_compensation_valid': False
        }

        # Safely extract values with defaults
        net_pay = data.get('net_pay', 0)
        total_hours = data.get('total_hours', 0)
        gross_pay = data.get('gross_pay', 0)

        # Only perform calculations if we have valid values
        if net_pay > 0 and total_hours > 0:
            # Calculate the regular hourly rate
            regular_hourly_rate = net_pay / total_hours if total_hours <= 40 else gross_pay / total_hours

            # Check minimum wage compliance
            checks['minimum_wage'] = regular_hourly_rate >= MINIMUM_WAGE

            # Check overtime compliance
            if total_hours > 40:
                overtime_hours = total_hours - 40
                overtime_pay = gross_pay - (40 * regular_hourly_rate)
                checks['overtime_compliant'] = overtime_pay >= (overtime_hours * regular_hourly_rate * 1.5)
            else:
                checks['overtime_compliant'] = True

        # Check total compensation validity
        checks['total_compensation_valid'] = self.is_total_compensation_valid(net_pay, gross_pay)

        return checks

    def generate_compliance_report(
        self, 
        employee_data: Dict[str, Any], 
        compliance_results: Dict[str, bool]
    ) -> str:
        """Generate PDF compliance report
        
        Args:
            employee_data: Employee data dictionary
            compliance_results: Compliance check results
            
        Returns:
            Path to generated PDF report
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

        # Paystub Details
        pdf.cell(0, 10, "Paystub Details:", ln=True)
        pdf.cell(0, 10, f"Total Hours: {employee_data.get('total_hours', 'N/A')}", ln=True)
        pdf.cell(0, 10, f"Gross Pay: ${employee_data.get('gross_pay', 'N/A')}", ln=True)
        pdf.cell(0, 10, f"Net Pay: ${employee_data.get('net_pay', 'N/A')}", ln=True)
        pdf.ln(5)

        # Compliance Checks
        pdf.cell(0, 10, "Compliance Check Results:", ln=True)
        for check, result in compliance_results.items():
            status = "✅ Passed" if result else "❌ Failed"
            pdf.cell(0, 10, f"{check.replace('_', ' ').title()}: {status}", ln=True)

        # Output the PDF
        request_id = uuid.uuid4().hex[:8]
        report_path = os.path.join(
            self.temp_dir, 
            f"compliance_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{request_id}.pdf"
        )
        pdf.output(report_path)
        logger.info(f"Compliance report generated: {report_path}")
        return report_path

    def send_email_report(self, email: str, report_path: str) -> bool:
        """Send email with compliance report
        
        Args:
            email: Recipient email address
            report_path: Path to the report file
            
        Returns:
            True if email sent successfully, False otherwise
        """
        try:
            msg = Message(
                "Your Compliance Report",
                sender=app.config['MAIL_DEFAULT_SENDER'],
                recipients=[email],
                body="Please find your compliance report attached.",
            )
            
            # Attach the report as a PDF file
            with open(report_path, "rb") as f:
                msg.attach("compliance_report.pdf", "application/pdf", f.read())

            # Send the email
            mail.send(msg)
            logger.info(f"Email sent to {email} with report {report_path}")
            return True
        except Exception as e:
            logger.error(f"Email sending failed: {e}")
            logger.error(traceback.format_exc())
            return False

    def generate_document_id(self, file_url: str) -> str:
        """Generate a secure document ID for Firestore
        
        Args:
            file_url: The file URL to hash
            
        Returns:
            A secure document ID
        """
        # Create a hash of the file_url to use as the document ID
        return hashlib.md5(file_url.encode()).hexdigest()

    def update_processing_status(self, file_url: str, email: str, status: str, message: str = "") -> bool:
        """Update processing status in Firestore
        
        Args:
            file_url: The file URL being processed
            email: User's email address
            status: Current status (processing, completed, failed)
            message: Optional status message
            
        Returns:
            True if update successful, False otherwise
        """
        try:
            doc_id = self.generate_document_id(file_url)
            doc_ref = db.collection('processing_status').document(doc_id)
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
            logger.error(traceback.format_exc())
            return False

    def cleanup_files(self, *file_paths) -> None:
        """Remove temporary files after processing
        
        Args:
            file_paths: Paths to files that should be deleted
        """
        for file_path in file_paths:
            try:
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)
                    logger.info(f"Removed file: {file_path}")
            except Exception as e:
                logger.error(f"Error removing file {file_path}: {e}")


@app.route("/", methods=["GET"])
def health_check():
    """Simple health check endpoint for Cloud Run"""
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()}), 200


@app.route("/upload-paystub", methods=["POST"])
@limiter.limit("10 per minute")
def upload_paystub():
    """Upload paystub file to Google Cloud Storage"""
    request_id = uuid.uuid4().hex
    logger.info(f"Request {request_id}: Starting file upload")
    
    try:
        # Check if file is in request
        if 'file' not in request.files:
            logger.error(f"Request {request_id}: No file part in the request")
            return jsonify({"error": "No file part"}), 400
            
        file = request.files['file']
        email = request.form.get('email')
        
        # Validate inputs
        processor = PaystubProcessor()
        
        # Check file
        file_error = processor.validate_file(file)
        if file_error:
            logger.error(f"Request {request_id}: {file_error}")
            return jsonify({"error": file_error}), 400
            
        # Check email
        if not email:
            logger.error(f"Request {request_id}: Email is required")
            return jsonify({"error": "Email is required"}), 400
            
        email_error = processor.validate_email(email)
        if email_error:
            logger.error(f"Request {request_id}: Invalid email - {email}")
            return jsonify({"error": email_error}), 400
            
        # Upload to GCS
        logger.info(f"Request {request_id}: Uploading file: {file.filename}")
        filename = processor.storage_service.upload_file(file, "paystub_uploads")
        
        # Set initial processing status
        processor.update_processing_status(filename, email, "uploaded", "File uploaded, awaiting processing")
        
        # Return success
        return jsonify({
            "message": "File uploaded successfully",
            "file_url": filename,
            "email": email,
            "status": "uploaded",
            "request_id": request_id
        })
        
    except Exception as e:
        error_message = str(e)
        logger.error(f"Request {request_id}: Upload failed - {error_message}")
        logger.error(traceback.format_exc())
        return jsonify({
            "error": "File upload failed", 
            "details": error_message,
            "request_id": request_id
        }), 500


@app.route("/process-paystub", methods=["POST"])
@limiter.limit("5 per minute")
def process_paystub():
    """Process a previously uploaded paystub"""
    request_id = uuid.uuid4().hex
    processor = PaystubProcessor()
    
    try:
        # Validate request data
        data = request.get_json()
        if not data or "file_url" not in data or "email" not in data:
            logger.error(f"Request {request_id}: Missing required fields")
            return jsonify({"error": "Missing required fields", "request_id": request_id}), 400

        file_url = data['file_url']
        email = data['email']
        
        # Update status to processing
        processor.update_processing_status(file_url, email, "processing", "Started processing paystub")
        logger.info(f"Request {request_id}: Processing paystub for {email}, file: {file_url}")

        # Validate email again
        email_error = processor.validate_email(email)
        if email_error:
            processor.update_processing_status(file_url, email, "failed", email_error)
            return jsonify({"error": email_error, "request_id": request_id}), 400

        # Download PDF from GCS
        logger.info(f"Request {request_id}: Downloading PDF from GCS")
        pdf_path = processor.download_pdf(file_url)
        if not pdf_path:
            processor.update_processing_status(file_url, email, "failed", "PDF download failed")
            return jsonify({"error": "PDF download failed from GCS", "request_id": request_id}), 400

        # Extract text from the PDF
        logger.info(f"Request {request_id}: Extracting text from PDF")
        extracted_text = processor.extract_pdf_text(pdf_path)
        if not extracted_text:
            processor.update_processing_status(file_url, email, "failed", "Text extraction failed")
            return jsonify({"error": "Text extraction failed", "request_id": request_id}), 400

        # Parse paystub data
        logger.info(f"Request {request_id}: Parsing paystub data")
        paystub_data = processor.parse_paystub_data(extracted_text)
        if not paystub_data:
            processor.update_processing_status(file_url, email, "failed", "Unable to parse paystub data")
            return jsonify({"error": "Unable to parse pay stub data", "request_id": request_id}), 400

        # Perform compliance checks
        logger.info(f"Request {request_id}: Performing compliance checks")
        compliance_results = processor.perform_compliance_checks(paystub_data)

        # Generate compliance report
        logger.info(f"Request {request_id}: Generating compliance report")
        report_path = processor.generate_compliance_report(paystub_data, compliance_results)
        
        # Check if report was generated
        if not os.path.exists(report_path):
            processor.update_processing_status(file_url, email, "failed", "Failed to generate report")
            return jsonify({"error": "Failed to generate the compliance report", "request_id": request_id}), 500

        # Send email with the report
        logger.info(f"Request {request_id}: Sending email report to {email}")
        email_sent = processor.send_email_report(email, report_path)
        if not email_sent:
            processor.update_processing_status(file_url, email, "failed", "Failed to send email")
            return jsonify({"error": "Failed to send email", "request_id": request_id}), 500

        # Update status on success
        processor.update_processing_status(file_url, email, "completed", "Report sent via email")
        
        # Cleanup the temporary files
        processor.cleanup_files(pdf_path, report_path)

        return jsonify({
            'message': 'Paystub processed and report sent successfully.',
            'email': email,
            'status': 'completed',
            'request_id': request_id
        })

    except Exception as e:
        error_message = str(e)
        logger.error(f"Request {request_id}: Processing failed - {error_message}")
        logger.error(traceback.format_exc())
        
        # Update status on failure if we have the necessary info
        if 'file_url' in locals() and 'email' in locals():
            processor.update_processing_status(file_url, email, "failed", error_message)
            
        return jsonify({
            "error": "Processing failed", 
            "details": error_message,
            "request_id": request_id
        }), 500


@app.route("/check-status", methods=["GET"])
def check_status():
    """Check the processing status of a file"""
    file_url = request.args.get('file_url')
    if not file_url:
        return jsonify({"error": "Missing file_url parameter"}), 400

    try:
        # Generate document ID from file_url
        processor = PaystubProcessor()
        doc_id = processor.generate_document_id(file_url)
        
        # Get status from Firestore
        doc_ref = db.collection('processing_status').document(doc_id)
        doc = doc_ref.get()
        
        if doc.exists:
            data = doc.to_dict()
            return jsonify({
                "file_url": file_url,
                "status": data.get("status", "unknown"),
                "message": data.get("message", ""),
                "updated_at": data.get("updated_at", "")
            })
        else:
            return jsonify({
                "file_url": file_url,
                "status": "unknown",
                "message": "No status found for this file"
            })
    except Exception as e:
        error_message = str(e)
        logger.error(f"Status check error: {error_message}")
        logger.error(traceback.format_exc())
        return jsonify({
            "error": "Failed to check status", 
            "details": error_message
        }), 500


if __name__ == "__main__":
    port = int(os.environ.get('PORT', 8080))
    debug = os.environ.get('DEBUG', 'False').lower() in ['true', '1', 't']
    app.run(debug=debug, host='0.0.0.0', port=port)