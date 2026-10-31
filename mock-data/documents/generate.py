"""Sample receipts for Document AI / Bookkeeping (mock mode and tests). Run: uv run --project ../../backend python generate.py

Writes three images and samples.json: what a vision model should read from each (with confidences), so mock mode
returns it for these exact files. The GSTINs are made-up but have valid check digits.
"""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).parent


def receipt(name: str, lines: list[str], width: int = 520, blur: float = 0) -> None:
    font = ImageFont.load_default(20)
    h = 40 + 30 * len(lines)
    img = Image.new("RGB", (width, h), "white")
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        d.text((24, 20 + 30 * i), line, fill="black", font=font)
    if blur:
        img = img.filter(ImageFilter.GaussianBlur(blur))
    img.save(HERE / name, quality=85)


receipt("grocery-receipt.jpg", [
    "FRESHMART SUPERMARKET", "Baner Road, Pune", "GSTIN: 27AAPFU0939F1ZV", "Bill No: FM-20931   Date: 28/10/2026", "-" * 34,
    "Toor dal 2kg            420.00", "Basmati rice 5kg        610.00", "Sunflower oil 1L        165.00", "-" * 34,
    "Subtotal               1195.00", "CGST 2.5%                 29.88", "SGST 2.5%                 29.88", "TOTAL Rs               1254.76",
    "Paid by UPI", "Thank you, visit again"])
receipt("supplier-tax-invoice.png", [
    "TAX INVOICE", "Sai Dental Supplies Pvt Ltd", "GSTIN: 27AABCS1429B1ZU", "Invoice: SDS/24-25/1187  Date: 22/10/2026",
    "Bill to: SmileCraft Dental Clinic", "-" * 40, "Composite filling kit x2     6,400.00", "Disposable gloves (box) x10  2,000.00", "-" * 40,
    "Taxable value               8,400.00", "CGST 9%                       756.00", "SGST 9%                       756.00",
    "Invoice total               9,912.00", "Payment due in 15 days"], width=600)
receipt("cafe-receipt-smudged.jpg", [
    "BLUE TOKAI COFFEE", "Koregaon Park", "Date: 2?/10/2026", "2 x Cappuccino    520", "1 x Croissant     240",
    "Total            7?0", "Card"], blur=1.6)

SAMPLES = {
    "grocery-receipt.jpg": {"is_document": True, "kind": "receipt", "fields": {
        "vendor": {"value": "FreshMart Supermarket", "confidence": 0.97}, "vendor_gstin": {"value": "27AAPFU0939F1ZV", "confidence": 0.93},
        "bill_number": {"value": "FM-20931", "confidence": 0.95}, "date": {"value": "2026-10-28", "confidence": 0.96},
        "currency": {"value": "INR", "confidence": 0.99}, "subtotal": {"value": 1195.00, "confidence": 0.95},
        "cgst": {"value": 29.88, "confidence": 0.92}, "sgst": {"value": 29.88, "confidence": 0.92}, "igst": {"value": None, "confidence": 0.9},
        "total": {"value": 1254.76, "confidence": 0.97}, "category": {"value": "Groceries & pantry", "confidence": 0.9},
        "payment_method": {"value": "UPI", "confidence": 0.9}, "description": {"value": "Dal, rice and cooking oil", "confidence": 0.9}},
        "line_items": [{"description": "Toor dal 2kg", "amount": 420}, {"description": "Basmati rice 5kg", "amount": 610},
                       {"description": "Sunflower oil 1L", "amount": 165}], "unclear": []},
    "supplier-tax-invoice.png": {"is_document": True, "kind": "bill", "fields": {
        "vendor": {"value": "Sai Dental Supplies Pvt Ltd", "confidence": 0.98}, "vendor_gstin": {"value": "27AABCS1429B1ZU", "confidence": 0.95},
        "bill_number": {"value": "SDS/24-25/1187", "confidence": 0.96}, "date": {"value": "2026-10-22", "confidence": 0.97},
        "currency": {"value": "INR", "confidence": 0.99}, "subtotal": {"value": 8400.00, "confidence": 0.96},
        "cgst": {"value": 756.00, "confidence": 0.95}, "sgst": {"value": 756.00, "confidence": 0.95}, "igst": {"value": None, "confidence": 0.9},
        "total": {"value": 9912.00, "confidence": 0.97}, "category": {"value": "Supplies & materials", "confidence": 0.92},
        "payment_method": {"value": None, "confidence": 0.5}, "description": {"value": "Composite filling kits and gloves", "confidence": 0.9}},
        "line_items": [{"description": "Composite filling kit x2", "amount": 6400}, {"description": "Disposable gloves (box) x10", "amount": 2000}],
        "unclear": []},
    "cafe-receipt-smudged.jpg": {"is_document": True, "kind": "receipt", "fields": {
        "vendor": {"value": "Blue Tokai Coffee", "confidence": 0.9}, "vendor_gstin": {"value": None, "confidence": 0.6},
        "bill_number": {"value": None, "confidence": 0.5}, "date": {"value": "2026-10-25", "confidence": 0.45},
        "currency": {"value": "INR", "confidence": 0.95}, "subtotal": {"value": None, "confidence": 0.5},
        "cgst": {"value": None, "confidence": 0.5}, "sgst": {"value": None, "confidence": 0.5}, "igst": {"value": None, "confidence": 0.5},
        "total": {"value": 760, "confidence": 0.55}, "category": {"value": "Meals & entertainment", "confidence": 0.85},
        "payment_method": {"value": "Card", "confidence": 0.85}, "description": {"value": "2 cappuccinos and a croissant", "confidence": 0.8}},
        "line_items": [{"description": "2 x Cappuccino", "amount": 520}, {"description": "1 x Croissant", "amount": 240}],
        "unclear": ["date", "total"]},
}
(HERE / "samples.json").write_text(json.dumps(SAMPLES, indent=1) + "\n")
print("wrote", ", ".join(SAMPLES))
