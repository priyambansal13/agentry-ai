"""Writes places-sample.jsonl: 50 dental clinics in Pune whose outcomes reproduce the reference funnel
(50 found -> 49 with a website -> 8 verified decision-maker emails). Deterministic; re-run to regenerate.

Each line is one Places-style result plus what the mock providers return for it:
  pages   -> what the site reader returns (url, title, text)
  finder  -> people the email finder knows at that domain
  verify  -> verifier verdicts for addresses at that domain (anything else is "unknown")
  expect  -> the case it exercises (documentation only)
"""
import json
import random
from pathlib import Path

rnd = random.Random(42)
FIRST = ["Asha", "Rohan", "Meera", "Vikram", "Sneha", "Arjun", "Kavya", "Nikhil", "Pooja", "Siddharth", "Ananya", "Rahul",
         "Ishita", "Kunal", "Neha", "Aditya", "Riya", "Varun", "Tanvi", "Harsh", "Divya", "Omkar", "Shruti", "Yash", "Gauri"]
LAST = ["Rao", "Kulkarni", "Deshpande", "Joshi", "Patil", "Shah", "Mehta", "Iyer", "Kapoor", "Gokhale", "Bhide", "Nair",
        "Pawar", "Sathe", "Apte", "Chitale", "Ranade", "Bapat", "Karve", "Phadke"]
AREAS = ["Kothrud", "Baner", "Aundh", "Viman Nagar", "Koregaon Park", "Hadapsar", "Wakad", "Kalyani Nagar", "Shivajinagar",
         "Magarpatta", "Pashan", "Bavdhan", "Kharadi", "Sinhagad Road", "Camp"]
STYLE = ["Dental Care", "Dental Clinic", "Smile Studio", "Dental Studio", "Family Dentistry", "Dental Centre", "Tooth Clinic"]
SERVICES = ["root canal treatment", "invisible aligners", "dental implants", "teeth whitening", "kids' dentistry",
            "smile makeovers", "gum treatment", "wisdom tooth removal", "ceramic crowns", "laser dentistry"]
TECH = ["digital X-rays", "intraoral scanners", "a 3D CBCT scanner", "laser-assisted root canals", "same-day ceramic crowns"]
ROLES = ["Founder & Lead Dentist", "Owner and Chief Dentist", "Clinic Director", "Managing Partner", "Principal Dentist"]
STAFF = ["Front desk", "Practice coordinator", "Dental hygienist"]

# (count, case) in order; see README for the funnel each one produces
PLAN = [(1, "no_website"), (3, "filtered_out"), (1, "duplicate"),
        (4, "site_email_valid"), (1, "site_email_catch_all"), (1, "site_email_invalid"),
        (3, "finder_valid"), (1, "finder_catch_all"), (2, "finder_invalid"), (1, "finder_unknown"),
        (1, "pattern_valid"), (1, "pattern_invalid"), (1, "suppressed"),
        (3, "site_unreadable"), (26, "generic_only")]
assert sum(n for n, _ in PLAN) == 50


def clinic(i: int, case: str) -> dict:
    first, last = FIRST[i % len(FIRST)], LAST[(i * 7) % len(LAST)]
    area = AREAS[i % len(AREAS)]
    name = f"{last} {STYLE[i % len(STYLE)]}" if i % 3 else f"{area} {STYLE[i % len(STYLE)]}"
    if case == "duplicate":
        name, domain = "SmileCraft Dental", "smilecraft.example"
    else:
        domain = name.lower().replace("'", "").replace("&", "and").replace(" ", "") + ".example"
    year = 1998 + (i * 3) % 24
    families = (i % 9 + 2) * 1000
    s1, s2, s3 = rnd.sample(SERVICES, 3)
    tech = TECH[i % len(TECH)]
    person = f"Dr. {first} {last}"
    role = ROLES[i % len(ROLES)]
    personal = f"{first.lower()}@{domain}"
    staff_line = f"{FIRST[(i + 5) % len(FIRST)]} {LAST[(i + 3) % len(LAST)]}, {STAFF[i % 3]} — frontdesk@{domain}"
    home = (f"{name}\n\nGentle, modern dentistry in {area}, Pune.\n\nWe offer {s1}, {s2} and {s3}.\n\n"
            f"Book a check-up: call {9810000000 + i * 137} or email info@{domain}.")
    about = (f"About us\n\nFounded in {year}, {name} has looked after more than {families:,} families in {area}.\n\n"
             f"We were one of the first clinics in {area} to use {tech}.\n\n"
             f"Every patient gets a written treatment plan with prices before we start.")
    team_lines = {"site": f"{person}, {role} — {personal}", "name_only": f"{person}, {role}"}
    rec = {"place_id": f"mock-place-{i:03d}", "name": name, "category": "Dentist", "city": "Pune",
           "address": f"{10 + i}, {area}, Pune", "phone": f"+91 98{i:02d} 5{i:03d}0", "rating": round(4.1 + (i % 9) / 10, 1),
           "reviews": 25 + (i * 17) % 400, "website": f"https://{domain}", "pages": [], "finder": [], "verify": {}, "expect": case}
    pages = [{"url": f"https://{domain}/", "title": name, "text": home}, {"url": f"https://{domain}/about", "title": "About us", "text": about}]
    team = None
    if case == "no_website":
        rec["website"] = None
        pages = []
    elif case == "filtered_out":
        rec["rating"], rec["reviews"] = (3.4, 120) if i % 2 else (4.6, 6)
        team = team_lines["site"]
    elif case == "duplicate":
        pass  # an existing client: only a generic inbox, so it drops out either way
    elif case.startswith("site_email"):
        team = team_lines["site"]
        rec["verify"][personal] = {"site_email_valid": "valid", "site_email_catch_all": "catch_all", "site_email_invalid": "invalid"}[case]
    elif case.startswith("finder"):
        team = team_lines["name_only"]
        found = f"{first.lower()}.{last.lower()}@{domain}"
        rec["finder"] = [{"email": found, "name": f"{first} {last}", "role": role, "confidence": 91}]
        rec["verify"][found] = {"finder_valid": "valid", "finder_catch_all": "catch_all", "finder_invalid": "invalid", "finder_unknown": "unknown"}[case]
    elif case.startswith("pattern"):
        team = team_lines["name_only"]
        rec["verify"][personal] = "valid" if case == "pattern_valid" else "invalid"
    elif case == "suppressed":
        team = team_lines["site"]
        rec["verify"][personal] = "invalid"  # never reached when the suppression list has it; dropped anyway otherwise
        rec["suppress"] = personal
    elif case == "site_unreadable":
        pages = []
    if team:
        pages.append({"url": f"https://{domain}/team", "title": "Our team", "text": f"Our team\n\n{team}\n\n{staff_line}"})
    else:
        pages.append({"url": f"https://{domain}/contact", "title": "Contact", "text": f"Contact\n\n{staff_line}\n\nEmail: info@{domain}"})
    if case == "site_unreadable":
        pages = []
    rec["pages"] = pages
    return rec


out, i = [], 0
for n, case in PLAN:
    for _ in range(n):
        out.append(clinic(i, case))
        i += 1
rnd.shuffle(out)  # the order a search returns them in
Path(__file__).with_name("places-sample.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out))
print(len(out), "clinics")
