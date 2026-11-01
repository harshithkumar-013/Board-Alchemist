import io
import os
import time
import cv2
import numpy as np
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import streamlit as st
from ultralytics import YOLO

# 1. Page Configuration
st.set_page_config(
    page_title="CHIP-EYE Workstation",
    layout="wide",
)

st.title("CHIP-EYE: Edge-AI Optical Inspection & Harvesting Workstation")
st.write(
    "Automated PCB component detection, hazard flagging, material valuation,"
    " and digital certification."
)

# 2. Smart Component Valuation & Hazard Lookup
# Matches keywords in your best.pt class names automatically
Rules_DB = [
    {
        "keywords": ["ic", "chip", "mcu", "cpu", "processor", "bga", "qfp"],
        "category": "Reusable Silicon",
        "value_inr": 45.0,
        "elements": "Silicon, Gold wire bonds, Copper leadframe",
        "hazardous": False,
        "handling": "Safe for thermal desoldering and IC testing.",
    },
    {
        "keywords": ["bat", "lithium", "cell", "cmos"],
        "category": "Hazardous Component",
        "value_inr": 30.0,
        "elements": "Lithium, Cobalt, Nickel",
        "hazardous": True,
        "handling": (
            "CRITICAL HAZARD: Thermal runaway risk. Depower and isolate"
            " immediately."
        ),
    },
    {
        "keywords": ["tantalum", "tant"],
        "category": "Critical Mineral / Reusable",
        "value_inr": 18.0,
        "elements": "Tantalum, Manganese Dioxide, Silver",
        "hazardous": False,
        "handling": "High critical-element recovery value. Harvest intact.",
    },
    {
        "keywords": ["elec", "cap", "capacitor"],
        "category": "Hazardous / Recyclable",
        "value_inr": 5.0,
        "elements": "Aluminum, Liquid Electrolyte, Dielectric film",
        "hazardous": True,
        "handling": (
            "Contains chemical electrolyte; avoid puncturing during removal."
        ),
    },
    {
        "keywords": ["conn", "pin", "header", "gold", "port", "usb", "slot"],
        "category": "Precious Metal Recovery",
        "value_inr": 25.0,
        "elements": "Gold plating, Brass, Phosphor Bronze",
        "hazardous": False,
        "handling": "Route to precious metal stripping or direct reuse.",
    },
    {
        "keywords": ["inductor", "coil", "transformer", "choke"],
        "category": "Copper Recovery / Reusable",
        "value_inr": 15.0,
        "elements": "High-purity Copper winding, Ferrite core",
        "hazardous": False,
        "handling": "Harvest for reusable power stage or copper smelting.",
    },
    {
        "keywords": ["res", "resistor", "smd", "diode", "led", "transistor"],
        "category": "Standard Reusable / Smeltable",
        "value_inr": 3.0,
        "elements": "Ruthenium, Ceramic, Copper, Tin",
        "hazardous": False,
        "handling": "Bulk selective harvesting or base-metal recovery.",
    },
]

DEFAULT_METADATA = {
    "category": "Reusable / E-Waste Recovery",
    "value_inr": 8.0,
    "elements": "Copper, Tin, Trace Precious Metals",
    "hazardous": False,
    "handling": "Standard mechanical harvesting and sorting.",
}


def get_component_metadata(class_name):
  clean_name = class_name.lower().strip()
  for rule in Rules_DB:
    for kw in rule["keywords"]:
      if kw in clean_name:
        return rule
  return DEFAULT_METADATA


# 3. In-Memory PDF Digital Certificate Generator
def generate_pdf_bytes(manifest_data, total_value, hazard_count, reusable_count):
  buffer = io.BytesIO()
  c = canvas.Canvas(buffer, pagesize=letter)
  width, height = letter

  # Title & Header
  c.setFont("Helvetica-Bold", 16)
  c.drawString(
      40, height - 50, "CHIP-EYE: DIGITAL E-WASTE COMPLIANCE CERTIFICATE"
  )
  c.setFont("Helvetica", 10)
  c.drawString(
      40,
      height - 68,
      f"Certificate ID: CE-{int(time.time())}   |   Timestamp:"
      f" {time.strftime('%Y-%m-%d %H:%M:%S')}",
  )
  c.line(40, height - 78, width - 40, height - 78)

  # Executive Summary
  c.setFont("Helvetica-Bold", 12)
  c.drawString(40, height - 105, "1. Executive Valuation & Safety Summary")
  c.setFont("Helvetica", 10)
  c.drawString(
      55, height - 125, f"Total Components Identified: {len(manifest_data)}"
  )
  c.drawString(
      55, height - 142, f"Reusable / Safe Components: {reusable_count}"
  )
  c.drawString(
      55, height - 159, f"Hazardous Components Flagged: {hazard_count}"
  )
  c.setFont("Helvetica-Bold", 11)
  c.drawString(
      55,
      height - 178,
      f"Estimated Critical Material & Resale Value: Rs. {total_value:.2f}",
  )

  # Component Breakdown Table
  c.setFont("Helvetica-Bold", 12)
  c.drawString(40, height - 210, "2. Itemized Component & Critical Element Log")

  y = height - 232
  c.setFont("Helvetica-Bold", 9)
  c.drawString(40, y, "Component")
  c.drawString(135, y, "Category")
  c.drawString(275, y, "Safety Status")
  c.drawString(365, y, "Critical Elements")
  c.drawString(510, y, "Value (INR)")
  c.line(40, y - 4, width - 40, y - 4)

  y -= 18
  c.setFont("Helvetica", 8)
  for item in manifest_data:
    if y < 60:
      c.showPage()
      y = height - 50
      c.setFont("Helvetica", 8)

    c.drawString(40, y, str(item["Component"])[:18])
    c.drawString(135, y, str(item["Category"])[:24])
    c.drawString(275, y, "HAZARDOUS" if item["Hazardous"] else "SAFE / REUSE")
    c.drawString(365, y, str(item["Critical Elements"])[:26])
    c.drawString(510, y, f"Rs. {item['Value (INR)']:.2f}")
    y -= 14

  # Footer
  c.line(40, 50, width - 40, 50)
  c.setFont("Helvetica-Oblique", 8)
  c.drawString(
      40,
      35,
      "Certified automatically by CHIP-EYE Edge-AI Optical Inspection"
      " Workstation (AssayVision).",
  )

  c.save()
  buffer.seek(0)
  return buffer.getvalue()


# 4. Sidebar & Model Loading
st.sidebar.header("Workstation Controls")
model_path = st.sidebar.text_input("Model Path (.pt file)", value="best.pt")

if not os.path.exists(model_path):
  st.error(
      f"⚠️ Could not find `{model_path}` in `{os.getcwd()}`. Please make sure"
      " `best.pt` is in the exact same folder as `app.py`, or type the full"
      " path in the left sidebar."
  )
  st.stop()


@st.cache_resource
def load_yolo_model(path):
  return YOLO(path)


try:
  model = load_yolo_model(model_path)
  st.sidebar.success(f"Loaded `{model_path}` successfully!")
  with st.sidebar.expander("View Classes in Your Model"):
    st.write(model.names)
except Exception as e:
  st.error(f"Error loading model: {e}")
  st.stop()

confidence_threshold = st.sidebar.slider(
    "Confidence Threshold", 0.05, 1.0, 0.25, 0.05
)
source_mode = st.sidebar.radio(
    "Select Input Source", ("Upload PCB Image", "Live Camera Snapshot")
)


# 5. Core Processing & Dashboard Renderer
def process_and_display(image_pil):
  image_np = np.array(image_pil.convert("RGB"))

  col1, col2 = st.columns(2)
  with col1:
    st.subheader("Raw Scanned PCB")
    st.image(image_pil)

  with col2:
    st.subheader("AI Optical Inspection")
    results = model.predict(image_np, conf=confidence_threshold)
    annotated_bgr = results[0].plot()
    annotated_rgb = cv2.cvtColor(annotated_bgr, cv2.COLOR_BGR2RGB)
    st.image(annotated_rgb)

  boxes = results[0].boxes
  if len(boxes) == 0:
    st.warning(
        "No components detected at the current confidence threshold. Try"
        " lowering the Confidence Threshold slider in the left sidebar!"
    )
    return

  manifest_data = []
  total_valuation = 0.0
  hazard_count = 0
  reusable_count = 0

  for box in boxes:
    cls_id = int(box.cls[0])
    cls_name = model.names[cls_id]
    conf = float(box.conf[0])
    xyxy = [round(float(x), 1) for x in box.xyxy[0].tolist()]

    meta = get_component_metadata(cls_name)
    val = meta["value_inr"]
    is_haz = meta["hazardous"]

    total_valuation += val
    if is_haz:
      hazard_count += 1
    else:
      reusable_count += 1

    manifest_data.append({
        "Component": cls_name,
        "Confidence": f"{conf:.2f}",
        "Category": meta["category"],
        "Hazardous": is_haz,
        "Critical Elements": meta["elements"],
        "Value (INR)": val,
        "Coordinates [x1,y1,x2,y2]": str(xyxy),
        "Handling Protocol": meta["handling"],
    })

  # Metrics Row
  st.markdown("---")
  st.subheader("📊 Valuation, Reusability & Hazard Audit")
  m1, m2, m3, m4 = st.columns(4)
  m1.metric("Total Detected", len(manifest_data))
  m2.metric("Reusable Components", reusable_count)
  m3.metric("Hazardous Components", hazard_count)
  m4.metric("Est. Batch Value", f"₹{total_valuation:.2f}")

  if hazard_count > 0:
    st.error(
        f"⚠️ HAZARD ALERT: {hazard_count} hazardous component(s) identified!"
        " Follow safe depowering and PPE extraction protocols before mechanical"
        " harvesting."
    )
  else:
    st.success(
        "✅ No high-risk hazardous components detected. Safe for standard"
        " selective harvesting."
    )

  # Detailed Audit Table
  st.dataframe(manifest_data, use_container_width=True)

  # Generate & Download PDF Digital Certificate
  pdf_bytes = generate_pdf_bytes(
      manifest_data, total_valuation, hazard_count, reusable_count
  )
  st.download_button(
      label="📥 Download Digital Compliance & Valuation Certificate (PDF)",
      data=pdf_bytes,
      file_name=f"CHIP_EYE_Certificate_{int(time.time())}.pdf",
      mime="application/pdf",
  )


# 6. Input Handling
if source_mode == "Upload PCB Image":
  uploaded_file = st.file_uploader(
      "Upload a waste PCB image (JPG/PNG)", type=["jpg", "jpeg", "png", "webp"]
  )
  if uploaded_file is not None:
    img = Image.open(uploaded_file)
    process_and_display(img)

elif source_mode == "Live Camera Snapshot":
  camera_photo = st.camera_input("Capture PCB frame from Optical Station")
  if camera_photo is not None:
    img = Image.open(camera_photo)
    process_and_display(img)
