import random

def simulate_ocr_extraction(file_obj):
    """
    Simulates Google Cloud Vision OCR text extraction for Philippine Business Permits.
    In production, you would call the official google-cloud-vision SDK here.
    """
    # Mocking extracted data and confidence scores for capstone demonstration
    extracted_data = {
        "business_name": "Verified Local Establishment",
        "permit_number": f"BP-{random.randint(10000, 99999)}",
        "expiry_date": "2027-12-31",
        "confidence_score": round(random.uniform(85.0, 98.5), 2) # Score between 1-100
    }
    return extracted_data