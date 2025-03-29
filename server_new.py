import os
import logging
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
        # For testing, return a mock status
        return jsonify({
            'status': 'processing',
            'message': 'Test status response',
            'file_url': file_url
        })
    except Exception as e:
        logger.error(f"Error checking status: {e}")
        return jsonify({
            'error': 'Failed to check processing status',
            'details': str(e)
        }), 500

if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
