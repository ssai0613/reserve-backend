import os
import re
import requests
from django.conf import settings

OCR_SPACE_API_KEY = "K83141179188957"  # Your active free key

def extract_cebu_permit_data(file_path):
    """
    Real OCR extraction via OCR.space Free API with highly resilient Cebu City anchor parsing.
    """
    full_path = os.path.join(settings.MEDIA_ROOT, str(file_path))
    
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
        with open(full_path, 'rb') as img_file:
            payload = {
                'apikey': OCR_SPACE_API_KEY,
                'language': 'eng',
                'isOverlayRequired': False,
                'detectOrientation': True,
                'scale': True,
                'OCREngine': 2 
            }
            response = requests.post(
                'https://api.ocr.space/parse/image',
                files={'file': img_file},
                data=payload,
                timeout=30
            )

        resp_data = response.json()

        if resp_data.get("IsErroredOnProcessing"):
            error_msg = resp_data.get("ErrorMessage", ["Unknown error"])
            raise Exception(" | ".join(error_msg))

        parsed_results = resp_data.get("ParsedResults", [])
        if not parsed_results:
            return result

        full_text = parsed_results[0].get("ParsedText", "")
        result["raw_text"] = full_text

        # 1. Municipal Anchor Check
        lgu_markers = ["CEBU CITY", "OFFICE OF THE MAYOR", "BUSINESS PERMIT"]
        if sum(1 for m in lgu_markers if re.search(m, full_text, re.IGNORECASE)) >= 2:
            result["lgu_anchor"] = "Cebu City Government (Verified)"

        # 2. Permit Number
        permit_match = re.search(r'PERMIT\s*(?:NO\.?|NUMBER)?\s*[:.]?\s*([A-Z0-9\-\.\/]+)', full_text, re.IGNORECASE)
        if permit_match:
            clean_pno = re.split(r'[\r\n\s]', permit_match.group(1).strip())[0]
            result["permit_number"] = clean_pno

        # 3. Business Name 
        bname_match = re.search(r'Business\s*Name\s*[:\-]?(.*?)(?=Business\s*Add?ress|Line/Nature|Taxpayer|$)', full_text, re.DOTALL | re.IGNORECASE)
        if bname_match:
            lines = [l.strip() for l in bname_match.group(1).splitlines() if l.strip()]
            if lines:
                result["business_name"] = " ".join(lines)

        # 4. Business Address 
        baddr_match = re.search(r'Business\s*Add?ress\s*[:\-]?(.*?)(?=Line/Nature|For\s*[A-Z]|Gross|\d{4}|$)', full_text, re.DOTALL | re.IGNORECASE)
        if baddr_match:
            lines = [l.strip() for l in baddr_match.group(1).splitlines() if l.strip() and not l.strip().isdigit()]
            if lines:
                address = " ".join(lines)
                result["business_address"] = re.sub(r'\s+\d+$', '', address)

        # 5. Nature of Business
        nature_match = re.search(r'Sales/Receipts\s*:\s*\n([^\n]+)', full_text, re.IGNORECASE)
        if nature_match:
            result["nature_of_business"] = nature_match.group(1).strip()

        # 6. Calendar Validity & Expiry 
        year_match = re.search(r'For\s*[A-Za-z]*\s*(20\d{2}.*?)\n', full_text, re.IGNORECASE)
        if year_match:
            years = re.findall(r'20\d{2}', year_match.group(1))
            if years:
                latest_year = max(years)
                result["calendar_year"] = f"{min(years)}-{max(years)}" if len(years) > 1 else years[0]
                result["expiry_date"] = f"{latest_year}-12-31"

        # 7. Date Issued (Tolerant of 'ñ' like 'Jañuary')
        issued_match = re.search(r'Date\s*([A-Za-zñÑ]+\s+\d{1,2},?\s+\d{4})', full_text, re.IGNORECASE)
        if issued_match:
            result["date_issued"] = issued_match.group(1).strip()

        # 8. Taxpayer / Representative 
        tax_rep_match = re.search(r'Authorized\s*Representative\s*[:\-]?(.*?)(?=TIN\s*:|Form\s*of|Capital)', full_text, re.DOTALL | re.IGNORECASE)
        if tax_rep_match:
            lines = [l.strip() for l in tax_rep_match.group(1).splitlines() if l.strip()]
            if len(lines) >= 1: 
                result["taxpayer_name"] = lines[0]
            if len(lines) >= 2: 
                result["representative"] = lines[1]

        # 9. Form of Ownership 
        owner_match = re.search(r'Capital\s*[:\-]?(.*?)(?=\d{2,}|DALID|VALID|NOT|WITHOUT)', full_text, re.DOTALL | re.IGNORECASE)
        if owner_match:
            lines = [l.strip() for l in owner_match.group(1).splitlines() if l.strip()]
            if lines: 
                result["ownership_type"] = lines[0]

        # 10. Dynamic Confidence Score
        anchors_detected = sum(1 for k in ["permit_number", "business_name", "business_address", "date_issued", "representative", "ownership_type"] if result[k] != "Not Detected")
        result["confidence_score"] = round(min(98.5, 60.0 + (anchors_detected * 6.5)), 1)

        return result

    except Exception as e:
        print(f"OCR.space API Error: {e}")
        return result

# Backward compatibility alias
simulate_ocr_extraction = extract_cebu_permit_data