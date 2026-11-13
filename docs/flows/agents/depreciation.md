# Depreciation (CA desk part 2, #6)

A client's fixed asset register becomes the year's depreciation twice over: for the **books** (Companies Act, Schedule II:
straight line over the useful life) and for the **tax return** (Income-tax: written-down value by block of assets), with the
**deferred tax** on the difference. All by rules, no AI: the same register always gives the same answer.

## Where
- Portal, on a **client's page**: Tools → Depreciation (the register and the financial year, or "Try the sample"). Upload
  hub: a fixed asset register goes here automatically. Any CA firm (shown with the filing tracker).
- The result page: summary, checks (most serious first), the Income-tax blocks, **Opening tax WDV by block** (enter last
  year's closing figures from the tax computation: the blocks and deferred tax are worked out again), the books by
  Schedule II class, deferred tax, and every asset. **Download Excel**: Books (Schedule II), Income-tax blocks, Asset-wise,
  Deferred tax, Checks.
- Website: `/agents/ca-depreciation`, an editable 18-asset register (Mehta Steel Pvt Ltd, FY 2025-26).

## Reading the register
Columns found by name: asset, category, IT block (optional, e.g. "Plant & Machinery 15%"), date of purchase, put-to-use
date, cost, opening accumulated depreciation **or** opening book WDV, opening tax WDV (optional), sale date, sale value,
useful life, residual %, payment mode. The year is the one given, else "FY 2025-26" in a title line, else the year of the
latest purchase or sale.

Each asset is classed from its category (else its name): land, goodwill, software, intangibles, servers, computers,
temporary structures, factory / other / residential buildings, electrical installations, furniture, solar / pollution
control, hire vehicles, lorries, two-wheelers, cars, office equipment, plant and machinery. Nothing matched → plant and
machinery (15%, 15 years), marked "assumed" and flagged. An IT block column wins for the block, a life column for the life.

## Books (Schedule II)
- Straight line: (cost − residual value) ÷ useful life, for the days in the year the asset was in use (from the put-to-use
  date, up to the day before it was sold), never below the residual value (5% of cost unless the register gives one).
- Opening carrying amount from the register; without it, worked out by straight line from the put-to-use date (flagged).
- Sold in the year: depreciation to the sale date, then profit or loss on sale. Land isn't depreciated. Goodwill and
  intangibles without a life are flagged (AS 26 / Ind AS 38, not Schedule II; 5 years used for software, 10 for others).
- Bought but put to use after the year end: capital work in progress, no depreciation, kept out of the totals.
- A life different from Schedule II is allowed when justified, and flagged for the notes.

## Tax (written-down value by block)
- Per block: opening WDV + additions − sale money, at the block rate. Additions put to use for **under 180 days** in the year
  get half the rate (sales are taken off the full-rate part first).
- Sale money above the block → short-term capital gain (section 50), no depreciation. Every asset in a block sold with WDV
  left → short-term capital loss (only if the register is the whole block: flagged to check).
- Paid in cash over ₹10,000 → not added to the block (section 43(1)); flagged as serious.
- New plant and machinery → a note that a manufacturer may claim additional depreciation (not under 115BAA / 115BAB);
  not included.
- Opening tax WDV: entered on the result page, else the register's column, else the book WDV (flagged: last year's tax
  computation is the right figure).

## Deferred tax (AS 22)
Book WDV − tax WDV of the depreciable assets (land and cash-paid assets left out: permanent differences), opening and
closing, at the tax rate (company 25.168% under 115BAA; firm / LLP 31.2%). The change is the year's charge (or credit).

## Official figures
Block rates (`dep.bld_res` 5%, `dep.bld` 10%, `dep.bld_temp` 40%, `dep.furniture` 10%, `dep.pm` 15%, `dep.vehicle_hire`
30%, `dep.computer` 40%, `dep.energy` 40%, `dep.intangible` 25%), `dep.half_days` 180, `dep.residual` 5%, `dep.tax_company`,
`dep.tax_firm`: in `official_rules.py`, checked daily, changes approved in HQ. Schedule II lives are in the code.

## Code
`backend/src/agentry/automations/ca/depreciation.py` (`classify`, `read`, `build`, `compute`, `rebuild`, `sheet`); routes
`/org/ca/clients/{cid}/depreciation(/sample)`, `POST /org/ca/work/{wid}/tax-opening`; agent `ca_depreciation`; website kind
`depreciation`; tests `backend/tests/test_ca_depreciation.py`; sample `backend/samples/ca/fixed_asset_register_sample.csv`
(generated so last year's accumulated depreciation and tax WDV follow from each asset's dates).
