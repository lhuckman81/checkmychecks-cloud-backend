import os
import re
import json
import uuid
import logging
import traceback
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

import requests
import PyPDF2
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from fpdf import FPDF
import email_validator
from flask_cors import CORS
from werkzeug.utils import secure_filename

# Google Cloud libraries
from google.cloud import storage
from google.cloud import firestore
from flask_mail import Mail, Message

# Constants
MINIMUM_WAGE = float(os.getenv('MINIMUM_WAGE', '15.0'))
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB max file size
ALLOWED_EXTENSIONS = {'pdf'}
BUCKET_ID = os.getenv('BUCKET_ID', "cs-poc-zgdkpqzt6vx3fwnl4kk8dky_cloudbuild")

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

# Enhanced CORS configuration
CORS(app, resources={r"/*": {
    "origins": "*",
    "methods": ["GET", "POST", "OPTIONS"],
    "allow_headers": ["Content-Type", "Authorization"]
}})

# Add rate limiting
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)
limiter.init_app(app)

# Configure Flask-Mail
app.config.update(
    MAIL_SERVER=os.getenv('MAIL_SERVER', 'smtp.gmail.com'),
    MAIL_PORT=int(os.getenv('MAIL_PORT', '587')),
    MAIL_USE_TLS=os.getenv('MAIL_USE_TLS', 'True').lower() in ['true', '1', 't'],
    MAIL_USERNAME=os.getenv('MAIL_USERNAME'),
    MAIL_PASSWORD=os.getenv('MAIL_PASSWORD'),
    MAIL_DEFAULT_SENDER=os.getenv('MAIL_DEFAULT_SENDER', 'info@mytips.pro')
)

mail = Mail(app)

# Initialize Firestore client
db = firestore.Client()


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
    """Process paystubs for compliance checking"""

    # Define regex patterns as class constants
    PATTERNS = {
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
            # Verify file exists and is valid
            self._validate_pdf_file(pdf_path)

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

    def _validate_pdf_file(self, pdf_path: str) -> bool:
        """Validate that the file exists, is not empty, and is actually a PDF

        Args:
            pdf_path: Path to PDF file

        Returns:
            True if valid, False otherwise. Raises exception if invalid.
        """
        # Verify file exists
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")

        # Check file size
        file_size = os.path.getsize(pdf_path)
        if file_size == 0:
            raise ValueError(f"PDF file is empty: {pdf_path}")

        # Check file is actually a PDF
        with open(pdf_path, 'rb') as file:
            header = file.read(5)
            if header != b'%PDF-':
                raise ValueError(f"File is not a valid PDF: {pdf_path}")

        return True

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

        results = {}  # Initialize results
        try:
            for key, pattern_list in self.PATTERNS.items():
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

    def perform_compliance_checks(self, data: Dict[str, Any]) -> Dict[str, bool]:
        """Perform compliance checks on paystub data."""
        checks = {
            'minimum_wage': False,
            'overtime_compliant': False,
            'total_compensation_valid': False
        }

        # Safely extract values with defaults
        net_pay = float(data.get('net_pay', 0) or 0)
        total_hours = float(data.get('total_hours', 0) or 0)
        gross_pay = float(data.get('gross_pay', 0) or 0)

        # Check total compensation validity
        checks['total_compensation_valid'] = net_pay > 0 and gross_pay > 0

        # Only perform calculations if we have valid values
        if net_pay > 0 and total_hours > 0:
            # Calculate the regular hourly rate
            regular_hourly_rate = net_pay / total_hours if total_hours <= 40 else gross_pay / total_hours

            # Check minimum wage compliance
            checks['minimum_wage'] = regular_hourly_rate >= MINIMUM_WAGE

            # Check overtime compliance (if applicable)
            checks['overtime_compliant'] = self._check_overtime_compliance(
                total_hours, regular_hourly_rate, gross_pay
            )

        return checks

    def _check_overtime_compliance(self, hours: float, hourly_rate: float, gross_pay: float) -> bool:
        """Check if overtime pay complies with regulations

        Args:
            hours: Total hours worked
            hourly_rate: Regular hourly rate
            gross_pay: Gross pay amount

        Returns:
            True if overtime pay complies with regulations, False otherwise
        """
        if hours <= 40:
            return True

        overtime_hours = hours - 40
        overtime_pay = gross_pay - (40 * hourly_rate)
        return overtime_pay >= (overtime_hours * hourly_rate * 1.5)

    def generate_compliance_report(
        self, 
        employee_data: Dict[str, Any], 
        compliance_results: Dict[str, bool]
    ) -> str:
        """Generate PDF compliance report with color-coded status
        
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
        pdf.set_text_color(0, 0, 0)  # Black
        pdf.set_font("Arial", 'B', 14)  # Larger, bold font for title
        pdf.cell(0, 10, "Pay Stub Compliance Report", ln=True, align='C')
        pdf.ln(10)

        # Employee Information
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, f"Employee: {employee_data.get('employee_name', 'Unknown')}", ln=True)
        pdf.ln(5)

        # Paystub Details
        pdf.set_font("Arial", 'B', 12)  # Bold for section title
        pdf.cell(0, 10, "Paystub Details:", ln=True)
        pdf.set_font("Arial", '', 12)  # Back to normal
        
        pdf.cell(0, 10, f"Total Hours: {employee_data.get('total_hours', 'N/A')}", ln=True)
        
        # Format currency with two decimal places
        gross_pay = employee_data.get('gross_pay', 'N/A')
        if isinstance(gross_pay, (int, float)):
            gross_pay = f"${gross_pay:.2f}"
        elif gross_pay != 'N/A':
            gross_pay = f"${gross_pay}"
            
        net_pay = employee_data.get('net_pay', 'N/A')
        if isinstance(net_pay, (int, float)):
            net_pay = f"${net_pay:.2f}"
        elif net_pay != 'N/A':
            net_pay = f"${net_pay}"
        
        pdf.cell(0, 10, f"Gross Pay: {gross_pay}", ln=True)
        pdf.cell(0, 10, f"Net Pay: {net_pay}", ln=True)
        pdf.ln(5)

        # Compliance Checks
        pdf.set_font("Arial", 'B', 12)  # Bold for section title
        pdf.cell(0, 10, "Compliance Check Results:", ln=True)
        pdf.set_font("Arial", '', 12)  # Back to normal
        
        for check, result in compliance_results.items():
            check_name = check.replace('_', ' ').title()
            
            # First part of text - always black
            pdf.set_text_color(0, 0, 0)  # Black
            pdf.cell(pdf.get_string_width(f"{check_name}: "), 10, f"{check_name}: ")
            
            # Status text with color
            if result:
                pdf.set_text_color(0, 128, 0)  # Green for PASSED
                status = "PASSED"
            else:
                pdf.set_text_color(220, 0, 0)  # Red for FAILED
                status = "FAILED"
                
            pdf.cell(0, 10, status, ln=True)
        
        # Reset text color to black for any following content
        pdf.set_text_color(0, 0, 0)
        
        # Add timestamp at the bottom
        pdf.ln(10)
        pdf.set_font("Arial", '', 10)
        pdf.set_text_color(128, 128, 128)  # Gray
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        pdf.cell(0, 10, f"Report generated: {timestamp}", ln=True, align='C')

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
        # Log the incoming file_url for debugging
        logger.info(f"Generating document ID for file_url: {file_url}")

        # Normalize the file_url to ensure consistency
        # Focus on the filename part if it has a path
        if '/' in file_url:
            parts = file_url.split('/')
            normalized_url = '/'.join(parts[-2:]) if len(parts) >= 2 else file_url
        else:
            normalized_url = file_url

        logger.info(f"Normalized URL for ID generation: {normalized_url}")

        # Create a hash of the normalized file_url to use as the document ID
        doc_id = hashlib.md5(normalized_url.encode()).hexdigest()
        logger.info(f"Generated document ID: {doc_id}")
        return doc_id

    def update_processing_status(self, file_url: str, email: str, status: str, message: str = "") -> bool:
        """Update processing status in Firestore
        
        Args:
            file_url: File URL
            email: User email
            status: Processing status
            message: Optional status message
            
        Returns:
            True if update succeeded, False otherwise
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
            
            logger.info(f"Updated processing status for {file_url} to {status}")
            return True
        except Exception as e:
            logger.error(f"Failed to update processing status: {e}")
            return False


# Create a global instance of the processor
processor = PaystubProcessor()

@app.route('/process-paystub', methods=['POST'])
def process_paystub():
    """Process a paystub PDF and generate a compliance report.
    
    Request:
        - file_url: URL to the paystub PDF in Google Cloud Storage
        - email: Email address to send the report to
        
    Returns:
        - JSON response with processing status
    """
    if not request.is_json:
        return jsonify({'error': 'Request must be JSON'}), 400
    
    data = request.get_json()
    
    file_url = data.get('file_url')
    email = data.get('email')
    
    if not file_url:
        return jsonify({'error': 'file_url is required'}), 400
    
    if not email:
        return jsonify({'error': 'email is required'}), 400
    
    # Validate email
    email_validation_error = processor.validate_email(email)
    if email_validation_error:
        return jsonify({'error': f'Invalid email: {email_validation_error}'}), 400
    
    # Update status to processing
    processor.update_processing_status(
        file_url=file_url,
        email=email,
        status='processing',
        message='Starting paystub processing'
    )
    
    try:
        # Process the file asynchronously (in this case, we're just spawning a thread)
        # In a production environment, you would use a task queue like Cloud Tasks
        from threading import Thread
        thread = Thread(target=process_paystub_async, args=(file_url, email))
        thread.daemon = True
        thread.start()
        
        return jsonify({
            'status': 'processing',
            'message': 'Paystub processing started',
            'file_url': file_url
        })
    
    except Exception as e:
        logger.error(f"Error starting processing: {e}")
        logger.error(traceback.format_exc())
        
        # Update status to failed
        processor.update_processing_status(
            file_url=file_url,
            email=email,
            status='failed',
            message=f'Error starting processing: {str(e)}'
        )
        
        return jsonify({
            'error': 'Failed to start processing',
            'details': str(e)
        }), 500


def process_paystub_async(file_url: str, email: str):
    """Process the paystub asynchronously.
    
    Args:
        file_url: URL to the paystub PDF in Google Cloud Storage
        email: Email address to send the report to
    """
    try:
        # Download the PDF
        logger.info(f"Downloading PDF from {file_url}")
        pdf_path = processor.download_pdf(file_url)
        
        if not pdf_path:
            logger.error(f"Failed to download PDF from {file_url}")
            processor.update_processing_status(
                file_url=file_url,
                email=email,
                status='failed',
                message='Failed to download PDF'
            )
            return
        
        # Extract text from PDF
        logger.info(f"Extracting text from {pdf_path}")
        text = processor.extract_pdf_text(pdf_path)
        
        if not text:
            logger.error(f"Failed to extract text from {pdf_path}")
            processor.update_processing_status(
                file_url=file_url,
                email=email,
                status='failed',
                message='Failed to extract text from PDF'
            )
            return
        
        # Parse paystub data
        logger.info("Parsing paystub data")
        data = processor.parse_paystub_data(text)
        
        if not data:
            logger.error("Failed to parse paystub data")
            processor.update_processing_status(
                file_url=file_url,
                email=email,
                status='failed',
                message='Failed to parse paystub data'
            )
            return
        
        # Perform compliance checks
        logger.info("Performing compliance checks")
        compliance_results = processor.perform_compliance_checks(data)
        
        # Generate compliance report
        logger.info("Generating compliance report")
        report_path = processor.generate_compliance_report(data, compliance_results)
        
        # Send email with report
        logger.info(f"Sending email to {email}")
        email_sent = processor.send_email_report(email, report_path)
        
        if email_sent:
            # Update status to completed
            processor.update_processing_status(
                file_url=file_url,
                email=email,
                status='completed',
                message='Paystub processing completed successfully'
            )
            logger.info(f"Processing completed for {file_url}")
        else:
            # Update status to completed but with email failure
            processor.update_processing_status(
                file_url=file_url,
                email=email,
                status='completed_with_errors',
                message='Processing completed but failed to send email'
            )
            logger.warning(f"Processing completed but email sending failed for {file_url}")
        
    except Exception as e:
        logger.error(f"Error processing paystub: {e}")
        logger.error(traceback.format_exc())
        
        # Update status to failed
        processor.update_processing_status(
            file_url=file_url,
            email=email,
            status='failed',
            message=f'Error processing paystub: {str(e)}'
        )


@app.route('/check-status', methods=['GET'])
def check_status():
    """Check the status of a paystub processing job.
    
    Request:
        - file_url: URL to the paystub PDF in Google Cloud Storage
        
    Returns:
        - JSON response with processing status
    """
    file_url = request.args.get('file_url')
    
    if not file_url:
        return jsonify({'error': 'file_url is required'}), 400
    
    try:
        # Get the document ID for the file URL
        doc_id = processor.generate_document_id(file_url)
        
        # Get the document from Firestore
        doc_ref = db.collection('processing_status').document(doc_id)
        doc = doc_ref.get()
        
        if not doc.exists:
            return jsonify({
                'status': 'unknown',
                'message': 'No processing status found for this file'
            }), 404
        
        # Get the document data
        data = doc.to_dict()
        
        return jsonify({
            'status': data.get('status', 'unknown'),
            'message': data.get('message', ''),
            'file_url': data.get('file_url', file_url),
            'updated_at': data.get('updated_at')
        })
    
    except Exception as e:
        logger.error(f"Error checking status: {e}")
        logger.error(traceback.format_exc())
        
        return jsonify({
            'error': 'Failed to check processing status',
            'details': str(e)
        }), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({'status': 'healthy'})


if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
