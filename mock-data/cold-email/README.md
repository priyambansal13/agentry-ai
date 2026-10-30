# Cold email sample: 50 dental clinics in Pune

`places-sample.jsonl` is what the mock providers return (`backend/src/agentry/automations/cold_email/providers.py`): one
Places-style business per line, plus the pages the site reader sees, the people the email finder knows and the
verifier's verdicts. Regenerate with `python3 generate.py` (deterministic).

| Case | Count | Ends at |
|---|---|---|
| no website | 1 | dropped: no website |
| low rating / few reviews | 3 | dropped by the campaign's filters (4.0+, 20+ reviews) |
| SmileCraft (an existing Agentry client) | 1 | dropped as already known (or as generic inbox if not known) |
| owner's email on the site: valid / catch-all / invalid | 4 / 1 / 1 | 4 verified |
| owner named, email from the finder: valid / catch-all / invalid / unknown | 3 / 1 / 2 / 1 | 3 verified |
| owner named, guessed first@domain: valid / invalid | 1 / 1 | 1 verified |
| owner on the do-not-contact list | 1 | dropped (fails verification if the list doesn't have them) |
| website can't be read | 3 | dropped |
| only info@ / front desk | 26 | dropped: generic inbox |

Result: **50 found → 49 with a website → 8 verified** (the reference funnel). All addresses are `.example`, so nothing
here can ever receive mail.
