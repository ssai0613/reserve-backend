import io
import os
import re
import json
from google.cloud import vision
from django.conf import settings

def extract_cebu_permit_data(file_path):
    """
    Production Anchor-Text OCR Engine calibrated for Cebu City Business Permits.
    Extracts Permit Number, Business Name, Physical Address, Nature of Business,
    Calendar Year, Date Issued, Taxpayer Name, and Representative.
    """
    full_path = os.path.join(settings.MEDIA_ROOT, str(file_path))
    
    # Fallback structure if file or API fails
    result = {
        "permit_number": "Not Detected",
        "business_name": "Not Detected",
        "business_address": "Not Detected",
        "nature_of_business": "Not Detected",
        "calendar_year": "Not Detected",
        "date_issued": "Not Detected",
        "expiry_date": "Not Detected",
        "taxpayer_name": "Not Detected",
        "representative": "Not Detected",
        "ownership_type": "Not Detected",
        "lgu_anchor": "Unverified",
        "confidence_score": 0.0,
        "raw_text": ""
    }

    if not os.path.exists(full_path):
        return result

    try:
        client = vision.ImageAnnotatorClient()
        with io.open(full_path, 'rb') as image_file:
            content = image_file.read()

        image = vision.Image(content=content)
        response = client.document_text_detection(image=image)

        if response.error.message:
            raise Exception(response.error.message)

        full_text = response.full_text_annotation.text
        result["raw_text"] = full_text

        # 1. Base Google Vision Page Confidence
        pages = response.full_text_annotation.pages
        base_confidence = (sum(p.confidence for p in pages) / len(pages) * 100) if pages else 85.0

        # 2. Municipal LGU Anchor Verification
        lgu_markers = ["CEBU CITY GOVERNMENT", "OFFICE OF THE MAYOR", "BUSINESS PERMIT"]
        matched_markers = [m for m in lgu_markers if re.search(m, full_text, re.IGNORECASE)]
        if len(matched_markers) >= 2:
            result["lgu_anchor"] = "Cebu City Government (Verified)"
        else:
            result["lgu_anchor"] = "Generic/Unverified LGU"

        # 3. Extract Permit Number (e.g., PERMIT NO. 147579 or PERMIT NO.147579)
        permit_match = re.search(r'PERMIT\s*(?:NO\.?|NUMBER)?\s*[:.]?\s*([A-Z0-9\-\.\/]+)', full_text, re.IGNORECASE)
        if permit_match:
            # Clean up potential trailing labels
            raw_pno = permit_match.group(1).strip()
            clean_pno = re.split(r'[\r\n\s]', raw_pno)[0]
            result["permit_number"] = clean_pno

        # 4. Extract Business Name
        # Searches text directly between 'Business Name:' and 'Business Address'
        bname_match = re.search(r'Business\s*Name\s*[:\-]?(.*?)(?=Business\s*Address|Line/Nature|Taxpayer|$)', full_text, re.DOTALL | re.IGNORECASE)
        if bname_match:
            bname = bname_match.group(1).strip()
            bname_clean = " ".join([line.strip() for line in bname.splitlines() if line.strip()])
            if bname_clean:
                result["business_name"] = bname_clean

        # 5. Extract Business Address
        baddr_match = re.search(r'Business\s*Address\s*[:\-]?(.*?)(?=Line/Nature|For\s*Calendar|Gross|$)', full_text, re.DOTALL | re.IGNORECASE)
        if baddr_match:
            baddr = baddr_match.group(1).strip()
            baddr_clean = " ".join([line.strip() for line in baddr.splitlines() if line.strip()])
            if baddr_clean:
                result["business_address"] = baddr_clean

        # 6. Extract Line / Nature of Business
        nature_match = re.search(r'Line/Nature\s*of\s*Business.*?:?(.*?)(?=This\s*permit|For\s*Calendar|Sanitary|$)', full_text, re.DOTALL | re.IGNORECASE)
        if nature_match:
            nature = nature_match.group(1).strip()
            # Strip leading code numbers like "9206"
            nature_clean = re.sub(r'^\d+\s*', '', " ".join([line.strip() for line in nature.splitlines() if line.strip()]))
            if nature_clean:
                result["nature_of_business"] = nature_clean

        # 7. Extract Calendar Year & Derive Expiry Date
        year_match = re.search(r'For\s*Calendar\s*Year\s*[:\-]?(.*?)(?=Date\s*Issued|APPROVED|$)', full_text, re.DOTALL | re.IGNORECASE)
        if year_match:
            raw_year = year_match.group(1).strip()
            year_clean = re.findall(r'\d{4}', raw_year)
            if year_clean:
                latest_year = max(year_clean)
                result["calendar_year"] = "-".join(year_clean) if len(year_clean) > 1 else year_clean[0]
                result["expiry_date"] = f"{latest_year}-12-31"

        # 8. Extract Date Issued (e.g., January 25, 2020)
        issued_match = re.search(r'Date\s*Issued\s*[:\-]?(.*?)(?=Business\s*Status|Taxpayer|$)', full_text, re.DOTALL | re.IGNORECASE)
        if issued_match:
            raw_date = issued_match.group(1).strip()
            date_clean = re.search(r'([A-Za-z]+\s+\d{1,2},?\s+\d{4})', raw_date)
            if date_clean:
                result["date_issued"] = date_clean.group(1).strip()

        # 9. Extract Legal Owner / Taxpayer & Representative
        taxpayer_match = re.search(r'Taxpayer(?:\'s)?\s*Name\s*[:\-]?(.*?)(?=Authorized|TIN|Form|$)', full_text, re.DOTALL | re.IGNORECASE)
        if taxpayer_match:
            tp = taxpayer_match.group(1).strip()
            result["taxpayer_name"] = " ".join([l.strip() for l in tp.splitlines() if l.strip()])

        rep_match = re.search(r'Authorized\s*Representative\s*[:\-]?(.*?)(?=TIN|Form|Capital|$)', full_text, re.DOTALL | re.IGNORECASE)
        if rep_match:
            rep = rep_match.group(1).strip()
            result["representative"] = " ".join([l.strip() for l in rep.splitlines() if l.strip()])

        # 10. Extract Form of Ownership
        owner_match = re.search(r'Form\s*of\s*Ownership\s*[:\-]?(.*?)(?=Capital|Approved|$)', full_text, re.DOTALL | re.IGNORECASE)
        if owner_match:
            owner = owner_match.group(1).strip()
            result["ownership_type"] = " ".join([l.strip() for l in owner.splitlines() if l.strip()])

        # Weight confidence score based on anchors found
        anchors_found_count = sum(1 for k in ["permit_number", "business_name", "business_address", "date_issued"] if result[k] != "Not Detected")
        adjusted_confidence = min(99.4, (base_confidence * 0.6) + (anchors_found_count * 10))
        result["confidence_score"] = round(adjusted_confidence, 1)

        return result

    except Exception as e:
        print(f"Vision API Processing Error: {e}")
        return result

# Backward compatibility alias
simulate_ocr_extraction = extract_cebu_permit_data