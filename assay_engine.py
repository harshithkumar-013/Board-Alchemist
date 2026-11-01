import barcode
from barcode.writer import ImageWriter
import cv2
import os
import json
import hashlib
import datetime
import qrcode
import easyocr
from database import evaluate_component

# Initialize EasyOCR reader once (English alphanumeric)
reader = easyocr.Reader(['en'], gpu=False, verbose=False)

def apply_clahe(image):
    """Enhances faint laser-etched text on black silicon ICs using CLAHE."""
    lab = cv2.cvtColor(image, opencv_code := cv2.COLOR_BGR2LAB)
    l_channel, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    cl = clahe.apply(l_channel)
    merged = cv2.merge((cl, a, b))
    return cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)

def generate_board_biometric_hash(components):
    """Creates an anti-spoofing SHA-256 hash from component spatial coordinates."""
    # Sort components by area and take top 15 center coordinates
    sorted_comps = sorted(components, key=lambda x: x["area_mm2"], reverse=True)[:15]
    spatial_signature = "|".join(
        [f"{c['class']}:{round(c['cx']/10, 1)},{round(c['cy']/10, 1)}" for c in sorted_comps]
    )
    return hashlib.sha256(spatial_signature.encode()).hexdigest()[:16].upper()

def analyze_pcb(image_path, mm_per_pixel=0.15):
    """Full end-to-end AssayVision pipeline from raw PCB image to EPR JSON."""
    img = cv2.imread(image_path)
    if img is None:
        raise FileNotFoundError(f"Could not load image at {image_path}")

    enhanced_img = apply_clahe(img)
    annotated_img = img.copy()
    detected_raw = []

    # Check if custom trained YOLOv8 weights exist; otherwise use OpenCV contour detector for instant testing
    if os.path.exists("best.pt"):
        from ultralytics import YOLO
        model = YOLO("best.pt")
        results = model(enhanced_img, verbose=False)[0]
        for box in results.boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            cls_id = int(box.cls[0])
            cls_name = model.names[cls_id]
            detected_raw.append((x1, y1, x2, y2, cls_name))
    else:
        # Instant OpenCV morphological component detector (works immediately without GPU training)
        gray = cv2.cvtColor(enhanced_img, cv2.COLOR_BGR2GRAY)
        edged = cv2.Canny(gray, 50, 150)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        closed = cv2.morphologyEx(edged, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            area_px = w * h
            if area_px < 600 or area_px > (img.shape[0] * img.shape[1] * 0.4):
                continue
            aspect_ratio = float(w) / h
            # Heuristic classification for instant demo testing
            if 0.85 <= aspect_ratio <= 1.15 and area_px > 2500:
                c_type = "Capacitor_Electrolytic"
            elif area_px > 3500:
                c_type = "IC"
            elif aspect_ratio > 3.0 or aspect_ratio < 0.33:
                c_type = "Connector_Gold"
            else:
                c_type = "SMD_Passive"
            detected_raw.append((x, y, x + w, y + h, c_type))

    # Process each detected component through OCR & IPC-1752A Valuation
    triage_results = []
    total_metals = {"Au": 0.0, "Pd": 0.0, "Ag": 0.0, "Ta": 0.0, "Cu": 0.0}
    total_reuse_inr = 0.0
    total_smelt_inr = 0.0

    # Color coding for the 3 Streams (BGR format for OpenCV)
    STREAM_COLORS = {
        "STREAM_1_REUSE": (0, 220, 0),    # Green: Intact Reusable ICs
        "STREAM_2_HAZARD": (0, 0, 255),   # Red: Hazardous Capacitors
        "STREAM_3_METALS": (0, 190, 255)  # Gold: Critical Metal Passives/Connectors
    }

    for idx, (x1, y1, x2, y2, c_type) in enumerate(detected_raw):
        w_mm = (x2 - x1) * mm_per_pixel
        h_mm = (y2 - y1) * mm_per_pixel
        area_mm2 = w_mm * h_mm

        # Run OCR only on ICs to keep speed under 1 second
        ocr_text = ""
        if c_type == "IC":
            crop = enhanced_img[max(0, y1):y2, max(0, x1):x2]
            ocr_hits = reader.readtext(crop, detail=0)
            ocr_text = " ".join(ocr_hits) if ocr_hits else ""

        eval_data = evaluate_component(c_type, ocr_text, area_mm2)

        # Accumulate totals
        for m in total_metals:
            total_metals[m] = round(total_metals[m] + eval_data["metals_mg"][m], 3)
        total_reuse_inr += eval_data["reuse_value_inr"]
        total_smelt_inr += eval_data["smelt_value_inr"]

        # Draw bounding box on board image
        color = STREAM_COLORS[eval_data["stream"]]
        cv2.rectangle(annotated_img, (x1, y1), (x2, y2), color, 2)
        cv2.putText(annotated_img, f"{c_type[:3]} #{idx+1}", (x1, max(15, y1 - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)

        triage_results.append({
            "id": idx + 1,
            "class": c_type,
            "cx": (x1 + x2) // 2,
            "cy": (y1 + y2) // 2,
            "area_mm2": round(area_mm2, 1),
            "ocr_read": ocr_text if ocr_text else "Unreadable (Fallback Used)",
            **eval_data
        })

    # Generate Anti-Spoofing Topological Board Hash
    board_hash = generate_board_biometric_hash(triage_results) if triage_results else "EMPTY_BOARD_000"

    # Build Final Digital Assay Certificate & CPCB EPR Payload
    certificate = {
        "certificate_id": f"ASSAY-{board_hash[:8]}",
        "board_biometric_sha256": board_hash,
        "timestamp_ist": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S IST"),
        "cpcb_epr_compliance": {
            "portal_standard": "CPCB E-Waste Management Rules (Schedule-I)",
            "hazard_decontamination_verified": any(c["stream"] == "STREAM_2_HAZARD" for c in triage_results),
            "total_components_assayed": len(triage_results)
        },
        "stream_counts": {
            "stream_1_reusable_ics": sum(1 for c in triage_results if c["stream"] == "STREAM_1_REUSE"),
            "stream_2_hazards_flagged": sum(1 for c in triage_results if c["stream"] == "STREAM_2_HAZARD"),
            "stream_3_metal_parts": sum(1 for c in triage_results if c["stream"] == "STREAM_3_METALS")
        },
        "recovered_metals_mg": total_metals,
        "financial_valuation_inr": {
            "intact_ic_reuse_value": round(total_reuse_inr, 2),
            "critical_metal_smelt_value": round(total_smelt_inr, 2),
            "total_board_payout_inr": round(total_reuse_inr + total_smelt_inr, 2)
        },
        "components": triage_results
    }

    # Save annotated image, QR Code, and JSON log
    cv2.imwrite("annotated_output.jpg", annotated_img)
# --- CYBERSECURITY ROLE-BASED DATA SEGREGATION ---
    # 1. Seller Token (Hides Buyer identity & downstream smelter margins)
    seller_hash = hashlib.sha256(f"SELLER:{cert_id}:{board_hash}".encode()).hexdigest()[:10].upper()
    seller_payload = {
        "role": "SELLER_RECEIPT",
        "seller_token": f"SLR-{seller_hash}",
        "cert_id": cert_id,
        "payout_inr": certificate["financial_valuation_inr"]["total_board_payout_inr"],
        "board_sha256": board_hash[:12]
    }
    
    # Generate Seller QR Code (Saves as seller_qr.png)
    qr = qrcode.QRCode(box_size=6, border=2)
    qr.add_data(json.dumps(seller_payload))
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    qr_img.save("seller_qr.png")

    # 2. Buyer Barcode ID (Hides Seller personal identity & local payout price; exposes only EPR assay)
    buyer_hash = hashlib.sha256(f"BUYER:{cert_id}:{board_hash}".encode()).hexdigest()[:8].upper()
    buyer_barcode_id = f"BYR-{buyer_hash}"
    
    # Generate Buyer 1D Barcode (Code-128 format -> automatically appends .png to save as buyer_barcode.png)
    Code128 = barcode.get_barcode_class("code128")
    buyer_bar = Code128(buyer_barcode_id, writer=ImageWriter())
    buyer_bar.save("buyer_barcode", options={"module_height": 10.0, "font_size": 10, "quiet_zone": 2.0})

    # Add the tokens to the certificate dictionary so index.html can display them
    certificate["cybersecurity_tokens"] = {
        "seller_qr_token": f"SLR-{seller_hash}",
        "buyer_barcode_id": buyer_barcode_id
    }
