import os
import sys
import pytesseract
from pdf2image import convert_from_path

# ✅ Ensure Poppler's `pdftoppm` is in PATH
os.environ["PATH"] += os.pathsep + "/opt/homebrew/bin"

# ✅ Check if an argument (PDF path) is provided
if len(sys.argv) < 2:
    print("❌ ERROR: No PDF file provided. Usage: python3 test_ocr.py /full/path/to/file.pdf")
    sys.exit(1)

# ✅ Use the provided PDF path
pdf_path = sys.argv[1]

# ✅ Ensure the file exists
if not os.path.exists(pdf_path):
    print(f"❌ ERROR: File not found at {pdf_path}")
    sys.exit(1)

print(f"📄 Processing PDF: {pdf_path}")

try:
    # ✅ Convert PDF to images using Poppler
    images = convert_from_path(pdf_path)
    if not images:
        print("❌ ERROR: No images extracted. Possible Poppler issue.")
        sys.exit(1)

    print(f"📸 Extracted {len(images)} page(s) from PDF.")

    # ✅ Extract text from images using OCR
    extracted_text = []
    for i, image in enumerate(images):
        text = pytesseract.image_to_string(image)
        extracted_text.append(text)
        print(f"🔍 Extracted text from page {i+1}:\n{text[:500]}...")  # Print first 500 chars

    # ✅ Save OCR output
    output_text = "\n".join(extracted_text)
    output_file = "ocr_output.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(output_text)

    print(f"✅ OCR Extraction Complete! Saved to {output_file}")

except Exception as e:
    print(f"❌ OCR Extraction Failed: {e}")
    sys.exit(1)

