import io
import os
import re
from google.cloud import vision
from django.conf import settings

def simulate_ocr_extraction(file_path):
    """
    Real Google Cloud Vision OCR Engine.
    Reads the physical file, extracts text, and calculates confidence.
    """
    # Get the absolute path to the uploaded image in your media folder
    full_path = os.path.join(settings.MEDIA_ROOT, str(file_path))
    
    try:
        # Initialize Google Vision Client
        client = vision.ImageAnnotatorClient()
        
        # Open the physical image file
        with io.open(full_path, 'rb') as image_file:
            content = image_file.read()
            
        image = vision.Image(content=content)
        
        # Perform Dense Document Text Detection (Best for permits)
        response = client.document_text_detection(image=image)
        
        if response.error.message:
            raise Exception(response.error.message)
            
        full_text = response.full_text_annotation.text
        
        # Calculate AI Confidence Score based on the recognized pages
        pages = response.full_text_annotation.pages
        if pages:
            confidence = sum(page.confidence for page in pages) / len(pages) * 100
        else:
            confidence = 0.0

        # Anchor Text Algorithm: Search the extracted text for Cebu patterns
        cebu_anchors_found = []
        target_keywords = ["lapu-lapu", "cebu", "business permit", "mayor"]
        
        for keyword in target_keywords:
            if re.search(keyword, full_text, re.IGNORECASE):
                cebu_anchors_found.append(keyword.title())

        # Attempt to find dates in the chaotic OCR text using Regex
        extracted_date = "Unknown"
        date_match = re.search(r'(20\d{2}-\d{2}-\d{2}|[A-Z][a-z]+\s\d{1,2},?\s20\d{2})', full_text)
        if date_match:
            extracted_date = date_match.group(0)

        return {
            "raw_text": full_text,
            "anchors": cebu_anchors_found,
            "confidence_score": round(confidence, 2),
            "extracted_date": extracted_date
        }
        
    except Exception as e:
        print(f"OCR Error: {e}")
        return {
            "raw_text": "OCR Scanning Failed.",
            "anchors": [],
            "confidence_score": 0.0,
            "extracted_date": "Unknown"
        }