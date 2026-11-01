# database.py - Component-to-Element & IPC-1752A Fallback Valuation Engine

# Live Market Metal Prices (INR per Milligram - approx LME rates)
METAL_RATES_INR_PER_MG = {
    "Au": 7.50,    # Gold (~₹7,500 per gram)
    "Pd": 2.80,    # Palladium (~₹2,800 per gram)
    "Ag": 0.09,    # Silver (~₹90 per gram)
    "Ta": 0.03,    # Tantalum (~₹30 per gram)
    "Cu": 0.00085  # Copper (~₹850 per kg)
}

# 1. Exact Part Number Database (When EasyOCR reads the chip text clearly)
KNOWN_IC_DATABASE = {
    "STM32F405": {"name": "ARM Cortex-M4 MCU", "reuse_inr": 320.0, "pins": 64, "Au_mg": 1.8, "Pd_mg": 0.4, "Ag_mg": 3.2, "Cu_mg": 180.0},
    "ATMEGA328P": {"name": "AVR 8-Bit Microcontroller", "reuse_inr": 140.0, "pins": 28, "Au_mg": 0.9, "Pd_mg": 0.2, "Ag_mg": 1.5, "Cu_mg": 95.0},
    "ESP32": {"name": "Wi-Fi/BLE SoC Module", "reuse_inr": 180.0, "pins": 38, "Au_mg": 1.2, "Pd_mg": 0.3, "Ag_mg": 2.1, "Cu_mg": 140.0},
    "NE555": {"name": "Precision Timer IC", "reuse_inr": 15.0, "pins": 8, "Au_mg": 0.2, "Pd_mg": 0.05, "Ag_mg": 0.4, "Cu_mg": 35.0},
    "CH340G": {"name": "USB-to-Serial Bridge IC", "reuse_inr": 45.0, "pins": 16, "Au_mg": 0.5, "Pd_mg": 0.1, "Ag_mg": 0.8, "Cu_mg": 55.0}
}

# 2. IPC-1752A Geometric Fallback Coefficients (mg of metal per mm^2 of component area)
# Used when OCR fails due to dust, scratches, or thermal paste
IPC_GEOMETRIC_COEFFS = {
    "IC": {"stream": "STREAM_1_REUSE", "Au_per_mm2": 0.012, "Pd_per_mm2": 0.003, "Ag_per_mm2": 0.025, "Cu_per_mm2": 1.4, "Ta_per_mm2": 0.0},
    "Capacitor_Electrolytic": {"stream": "STREAM_2_HAZARD", "Au_per_mm2": 0.0, "Pd_per_mm2": 0.0, "Ag_per_mm2": 0.0, "Cu_per_mm2": 0.5, "Ta_per_mm2": 0.0},
    "Connector_Gold": {"stream": "STREAM_3_METALS", "Au_per_mm2": 0.028, "Pd_per_mm2": 0.005, "Ag_per_mm2": 0.010, "Cu_per_mm2": 2.8, "Ta_per_mm2": 0.0},
    "SMD_Passive": {"stream": "STREAM_3_METALS", "Au_per_mm2": 0.001, "Pd_per_mm2": 0.015, "Ag_per_mm2": 0.040, "Cu_per_mm2": 0.8, "Ta_per_mm2": 0.08}
}

def evaluate_component(comp_class, ocr_text, area_mm2):
    """Returns Stream Triage, Elemental Mass (mg), and Valuation (INR)."""
    ocr_clean = ocr_text.upper().replace(" ", "")
    
    # Path A: Check if OCR text matches any known IC in our database
    for part_code, info in KNOWN_IC_DATABASE.items():
        if part_code in ocr_clean:
            metals = {"Au": info["Au_mg"], "Pd": info["Pd_mg"], "Ag": info["Ag_mg"], "Ta": 0.0, "Cu": info["Cu_mg"]}
            smelt_val = sum(metals[m] * METAL_RATES_INR_PER_MG[m] for m in metals)
            return {
                "method": f"Exact OCR Match ({part_code})",
                "stream": "STREAM_1_REUSE",
                "action": "Desolder at 220°C via Vacuum Pickup",
                "metals_mg": metals,
                "reuse_value_inr": round(info["reuse_inr"], 2),
                "smelt_value_inr": round(smelt_val, 2)
            }

    # Path B: IPC-1752A Geometric Fallback (Based on component class & area in mm^2)
    coeffs = IPC_GEOMETRIC_COEFFS.get(comp_class, IPC_GEOMETRIC_COEFFS["SMD_Passive"])
    metals = {
        "Au": round(area_mm2 * coeffs["Au_per_mm2"], 3),
        "Pd": round(area_mm2 * coeffs["Pd_per_mm2"], 3),
        "Ag": round(area_mm2 * coeffs["Ag_per_mm2"], 3),
        "Ta": round(area_mm2 * coeffs["Ta_per_mm2"], 3),
        "Cu": round(area_mm2 * coeffs["Cu_per_mm2"], 3)
    }
    smelt_val = sum(metals[m] * METAL_RATES_INR_PER_MG[m] for m in metals)
    
    # Estimate generic reuse value if it's an intact large IC (>50 mm^2)
    reuse_val = round(area_mm2 * 0.45, 2) if (comp_class == "IC" and area_mm2 > 50) else 0.0
    
    action_map = {
        "STREAM_1_REUSE": "Desolder at 220°C (Geometric Fallback IC)",
        "STREAM_2_HAZARD": "DANGER: Mechanical Cold-Clip Before Shredding!",
        "STREAM_3_METALS": "Leave on Board — Log to Digital Assay Certificate"
    }

    return {
        "method": f"IPC-1752A Geometric Fallback ({round(area_mm2, 1)} mm²)",
        "stream": coeffs["stream"],
        "action": action_map[coeffs["stream"]],
        "metals_mg": metals,
        "reuse_value_inr": reuse_val,
        "smelt_value_inr": round(smelt_val, 2)
    }
