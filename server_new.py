import os
import logging
import hashlib
from flask import Flask, request, jsonify
from flask_cors import CORS
from google.cloud import firestore

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
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

# Initialize Firestore client
db = firestore.Client()

def generate_document_id(file_url):
    """Generate a secure document ID for Firestore"""
    logger.info(f"Generating document ID for file_url: {file_url}")
    
    # Normalize the file_url to ensure consistency
    if '/' in file_url:
        parts = file_url.split('/')
        normalized_url = '/'.join(parts[-2:]) if len(parts) >= 2 else file_url
    else:
        normalized_url = file_url
    
    # Create a hash of the normalized file_url 
    doc_id = hashlib.md5(normalized_url.encode()).hexdigest()
    return doc_id

def update_processing_status(file_url, email, status, message=""):
    """Update processing status in Firestore"""
    try:
        doc_id = generate_document_id(file_url)
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

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({'status': 'healthy'})

@app.route('/', methods=['GET'])
def root():
    return jsonify({'message': 'Flask backend is running'})

@app.route('/check-status', methods=['GET'])
def check_status():
    """Check the status of a paystub processing job."""
    file_url = request.args.get('file_url')
    
    if not file_url:
        return jsonify({'error': 'file_url is required'}), 400
    
    try:
        # Get the document ID for the file URL
        doc_id = generate_document_id(file_url)
        
        # Get the document from Firestore
        doc_ref = db.collection('processing_status').document(doc_id)
        doc = doc_ref.get()
        
        if not doc.exists:
            # For testing, if no status exists, create one
            update_processing_status(file_url, 'test@example.com', 'processing', 'Processing in progress')
            
            return jsonify({
                'status': 'processing',
                'message': 'Test status response',
                'file_url': file_url
            })
        
        # Get the document data
        data = doc.to_dict()
        
        return jsonify({
            'status': data.get('status', 'unknown'),
            'message': data.get('message', ''),
            'file_url': data.get('file_url', file_url)
        })
    except Exception as e:
        logger.error(f"Error checking status: {e}")
        
        return jsonify({
            'error': 'Failed to check processing status',
            'details': str(e)
        }), 500

@app.route('/process-paystub', methods=['POST'])
def process_paystub():
    """Process a paystub PDF and generate a compliance report."""
    if not request.is_json:
        return jsonify({'error': 'Request must be JSON'}), 400
    
    data = request.get_json()
    
    file_url = data.get('file_url')
    email = data.get('email')
    
    if not file_url:
        return jsonify({'error': 'file_url is required'}), 400
    
    if not email:
        return jsonify({'error': 'email is required'}), 400
    
    logger.info(f"Received processing request for file: {file_url}, email: {email}")
    
    # Update status to processing
    update_processing_status(
        file_url=file_url,
        email=email,
        status='processing',
        message='Starting paystub processing'
    )
    
    # For this minimal version, we'll just acknowledge the request and set status
    # No actual processing yet
    
    return jsonify({
        'status': 'processing',
        'message': 'Paystub processing started',
        'file_url': file_url
    })

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
