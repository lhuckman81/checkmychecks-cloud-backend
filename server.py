import os
from flask import Flask, request, jsonify

app = Flask(__name__)

# ✅ Add a home route to confirm the server is running
@app.route("/")
def home():
    return "Flask App is Running on Render!"
from flask import Flask, request, jsonify, send_file
import os
import pytesseract
import pdf2image
import cv2
import numpy as np
from fpdf import FPDF

app = Flask(__name__)

@app.route("/process-paystub", methods=["POST"])
def process_paystub():
    data = request.json
    file_url = data.get("file_url")
    email = data.get("email")

    if not file_url:
        return jsonify({"error": "No file URL provided"}), 400

    # Simulate processing
    return jsonify({"message": "Pay stub processed successfully", "file_url": file_url, "email": email})

import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
import os
from flask import Flask, request, jsonify

app = Flask(__name__)

# ✅ Add a home route to confirm the server is running
@app.route("/")
def home():
    return "Flask App is Running on Render!"

@app.route("/process-paystub", methods=["POST"])
def process_paystub():
    data = request.json
    file_url = data.get("file_url")
    email = data.get("email")

    if not file_url:
        return jsonify({"error": "No file URL provided"}), 400

    return jsonify({"message": "Pay stub processed successfully", "file_url": file_url, "email": email})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)