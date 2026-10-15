import os
import re
import requests
from django.conf import settings

OCR_SPACE_API_KEY = "K83141179188957"  # Your active free key

def extract_cebu_permit_data(file_path):
    """
    Real OCR extraction via OCR.space Free API calibrated for both 
    new (2025-2026 columnar) and old (2020-2021 inline) Cebu City Business Permits.
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
        permit_match = re.search(r'PERMIT\s*(?:NO\.?|NUMBER|#)\s*[:.]?\s*([0-9A-Z\-]+)', full_text, re.IGNORECASE)
        if permit_match:
            result["permit_number"] = permit_match.group(1).strip()

        # 3 & 4. Business Name & Business Address
        # First check 2025 Columnar Layout (where OCR stacks labels above 'CAPITAL', then outputs values before Calendar Year)
        col_val_block = re.search(
            r'\bCAPITAL\b\s*\n(.*?)(?=20\d{2}\s*[\-–—3\/]\s*20\d{2})',
            full_text,
            re.DOTALL | re.IGNORECASE
        )
        if col_val_block:
            val_lines = []
            for line in col_val_block.group(1).splitlines():
                cleaned = re.sub(r'PERMIT\s*(?:NO\.?|NUMBER|#)?\s*[:.]?\s*\d+', '', line, flags=re.IGNORECASE).strip()
                if cleaned and not cleaned.isdigit():
                    val_lines.append(cleaned)
            if len(val_lines) >= 1:
                result["business_name"] = val_lines[0]
            if len(val_lines) >= 2:
                result["business_address"] = " ".join(val_lines[1:])

        # Fallback to 2020 Inline Layout if not found via columnar block
        if result["business_name"] == "Not Detected":
            bname_match = re.search(r'Business\s*Name\s*[:\-]\s*(.*?)(?=Business\s*Add?ress|Line/Nature|$)', full_text, re.DOTALL | re.IGNORECASE)
            if bname_match:
                lines = [l.strip() for l in bname_match.group(1).splitlines() if l.strip()]
                if lines:
                    result["business_name"] = " ".join(lines)

        if result["business_address"] == "Not Detected":
            baddr_match = re.search(r'Business\s*Add?ress\s*[:\-]?\s*\n(.*?)(?=Line/Nature|For\s*[A-Z]|CALENDAR|\d{4}\s*\n|$)', full_text, re.DOTALL | re.IGNORECASE)
            if baddr_match:
                lines = [l.strip() for l in baddr_match.group(1).splitlines() if l.strip() and not l.strip().isdigit()]
                if lines:
                    address = " ".join(lines)
                    result["business_address"] = re.sub(r'\s+\d+$', '', address)

        # 5. Calendar Validity & Expiry Date
        year_range_match = re.search(r'(20\d{2})\s*[\-–—3\/]\s*(20\d{2})', full_text)
        if year_range_match:
            y1, y2 = int(year_range_match.group(1)), int(year_range_match.group(2))
            latest_year = max(y1, y2)
            result["calendar_year"] = f"{min(y1, y2)}-{latest_year}"
            result["expiry_date"] = f"{latest_year}-12-31"

        # 6. Date Issued
        months_pattern = r'(?:Jan(?:uary)?|Jañuary|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
        issued_match = re.search(rf'\b({months_pattern}\s+\d{{1,2}},?\s+20\d{{2}})\b', full_text, re.IGNORECASE)
        if issued_match:
            result["date_issued"] = issued_match.group(1).replace('ñ', 'n').replace('Ñ', 'N').strip()

        # 7. Nature / Line of Business
        nature_block = re.search(
            r'(?:LINE\s*OF\s*BUSINESS|Sales/Receipts\s*:)\s*\n([^\n]+)',
            full_text,
            re.IGNORECASE
        )
        if nature_block:
            result["nature_of_business"] = nature_block.group(1).strip()

        # 8. Form of Ownership
        ownership_match = re.search(
            r'^\s*(COOPERATIVE|CORPORATION|SINGLE\s+PROPRIETORSHIP|SOLE\s+PROPRIETORSHIP|PARTNERSHIP)\s*$',
            full_text,
            re.MULTILINE | re.IGNORECASE
        )
        if ownership_match:
            result["ownership_type"] = ownership_match.group(1).upper().strip()

        # 9. Taxpayer / Authorized Representative
        # Check 2025 layout: sits directly between 'NEW - FINAL' (or 'RENEWAL') and Form of Ownership
        rep_2025_match = re.search(
            r'(?:NEW\s*[\-–]\s*FINAL|RENEWAL)\s*\n(.*?)(?=\n\s*(?:COOPERATIVE|CORPORATION|SINGLE\s+PROPRIETORSHIP|SOLE\s+PROPRIETORSHIP|PARTNERSHIP|LINE\s+OF\s+BUSINESS|Taxpayer))',
            full_text,
            re.DOTALL | re.IGNORECASE
        )
        if rep_2025_match:
            lines = [l.strip() for l in rep_2025_match.group(1).splitlines() if l.strip()]
            if lines:
                result["taxpayer_name"] = lines[0]
                result["representative"] = lines[-1]

        # Fallback to 2020 layout: sits after 'Authorized Representative:'
        if result["representative"] == "Not Detected":
            tax_rep_match = re.search(r'Authorized\s*Representative\s*[:\-]?\s*\n(.*?)(?=TIN\s*:|Form\s*of|Capital)', full_text, re.DOTALL | re.IGNORECASE)
            if tax_rep_match:
                lines = [l.strip() for l in tax_rep_match.group(1).splitlines() if l.strip()]
                if len(lines) >= 1:
                    result["taxpayer_name"] = lines[0]
                if len(lines) >= 2:
                    result["representative"] = lines[1]

        # 10. Dynamic Confidence Score
        anchors_detected = sum(
            1 for k in ["permit_number", "business_name", "business_address", "nature_of_business", "calendar_year", "date_issued", "representative"]
            if result[k] != "Not Detected"
        )
        result["confidence_score"] = round(min(98.5, 56.5 + (anchors_detected * 6.0)), 1)

        return result

    except Exception as e:
        print(f"OCR.space API Error: {e}")
        return result

# Backward compatibility alias
simulate_ocr_extraction = extract_cebu_permit_data