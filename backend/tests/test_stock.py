"""Stock shelf scanner (ROADMAP-V3 B2): a photo -> counts matched to tracked items -> confirmed -> reorder by supplier."""
import io

from PIL import Image

ITEMS = (b"Item,Unit,Reorder at,Reorder qty,Supplier,Supplier phone\n"
         b"Amul Taaza Milk 500ml,packet,10,24,Sharma Dairy,+919810000081\n"
         b"Parle-G 250g,packet,6,24,Gupta Wholesale,+919810000082\n"
         b"Tata Salt 1kg,packet,4,10,Gupta Wholesale,+919810000082\n")


def photo() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (60, 40), "white").save(b, "JPEG")
    return b.getvalue()


async def test_scan_confirm_and_reorder(client, team_org):
    _oid, h = await team_org(["stock_scanner"])
    r = await client.post("/org/stock/items/import", headers=h["manager"], files={"file": ("items.csv", ITEMS, "text/csv")})
    assert r.json() == {"imported": 3}
    r = await client.post("/org/stock/scan", headers=h["staff"], data={"area": "Front shelf"}, files={"photo": ("shelf_sample.jpg", photo(), "image/jpeg")})
    assert r.status_code == 201, r.text
    lines = {x["read_as"]: x for x in r.json()["items"]}
    milk = lines["Amul Taaza milk 500 ml"]
    assert milk["name"] == "Amul Taaza Milk 500ml" and milk["item_id"] and milk["count"] == 6  # matched to the tracked item
    assert lines["Tata Salt 1 kg"]["confidence"] == 0.65
    counts = [{"name": x["name"], "count": x["count"] if x["read_as"] != "Tata Salt 1 kg" else 3, "item_id": x["item_id"], "unit": x["unit"]}
              for x in r.json()["items"]]
    a = await client.post(f"/org/stock/scans/{r.json()['id']}/apply", headers=h["staff"], json={"counts": counts})
    assert a.json() == {"updated": 3, "added": 0}
    assert (await client.post(f"/org/stock/scans/{r.json()['id']}/apply", headers=h["staff"], json={"counts": counts})).status_code == 409
    d = (await client.get("/org/stock", headers=h["viewer"])).json()
    orders = {o["supplier"]: o for o in d["reorder"]}
    assert set(orders) == {"Sharma Dairy", "Gupta Wholesale"}  # milk 6 <= 10, salt 3 <= 4; biscuits 14 > 6
    assert "Amul Taaza Milk 500ml: 24 packet" in orders["Sharma Dairy"]["message"] and len(orders["Gupta Wholesale"]["items"]) == 1
    bad = await client.post("/org/stock/scan", headers=h["staff"], files={"photo": ("x.pdf", b"%PDF", "application/pdf")})
    assert bad.status_code == 422
    assert (await client.post("/org/stock/scan", headers=h["viewer"], files={"photo": ("s.jpg", photo(), "image/jpeg")})).status_code == 403
