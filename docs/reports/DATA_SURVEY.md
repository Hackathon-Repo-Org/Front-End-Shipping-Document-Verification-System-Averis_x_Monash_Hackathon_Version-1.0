# DATA SURVEY

## 1. Directory layout
```
.
├── README.md
├── loader.py
├── sample_submission.json
├── survey.py
├── attachments/      (250 files: .txt, .pdf, .xlsx, .docx)
└── inbox/             (520 files: email_*.json)
```

## 2. File type census
| extension | count | example path |
|---|---|---|
| .json | 521 | .\sample_submission.json (520 of these are inbox/email_*.json) |
| .txt | 192 | .\attachments\email_001_BL.txt |
| .pdf | 28 | .\attachments\email_059_BL.pdf |
| .xlsx | 22 | .\attachments\email_005_BL.xlsx |
| .docx | 8 | .\attachments\email_055_BL.docx |
| .py | 2 | .\loader.py |
| .md | 1 | .\README.md |

## 3. Email record schema
- How many email records: 520
- One record per file, or many records in one file: one JSON file per email (`inbox/email_NNN.json`), one record per file
- Full key list with types: `email_id` (str, 520/520), `from` (str, 520/520), `subject` (str, 520/520), `body` (str, 520/520), `attachments` (list, 520/520)
- A complete example record (verbatim):
```json
{
  "email_id": "email_001",
  "from": "aziztz@safqa.co.ke",
  "subject": "TO CONFIRM DOCS _ 5RSG-00133 _ CALLAO_PERU _ MOORIM SP CO., LTD _ MEDUUD104332",
  "body": "Hi Najiha,\n\nAttached are the SI and draft BL for OC 5RSG-00133 (PAPERONE DIGITAL COPIER PAPER). Please check the details and confirm.\n\nBest Regards,\nWilly Situmorang\nShipping Documentation\nDID : +971 04 4938289\nAPRIL Fine Paper Trading (Middle East) Fze\n#813, 4 EA, Dubai Airport Free Zone\nP.O. Box : 293775, Dubai, United Arab Emirates\nWebsite : www.aprilasia.com | www.paperone.com",
  "attachments": [
    "attachments/email_001_SI.txt",
    "attachments/email_001_BL.txt"
  ]
}
```

## 4. Email categories
- The field that holds the category: no field in the email JSON itself holds a category — category is not present in `inbox/*.json`. The category label only appears as a key inside `sample_submission.json`, under `category`.
- EXACT distinct category strings found: in `sample_submission.json` every one of the 520 entries has `"category": "GENERAL"` — this is a placeholder/sample value, not ground truth (confirmed via `Counter(v['category'] for v in d.values())` → `Counter({'GENERAL': 520})`). The **possible** category names are only documented in `README.md`: `BL_COMPARISON`, `SI_REQUEST`, `INVOICE_QUERY`, `GENERAL`, `SPAM`. These are not attested as distinct values in any data file — UNKNOWN which emails belong to which category from the files alone.

## 5. Attachments
- How an email points at its attachments: field `attachments`, a list of relative path strings, e.g. `"attachments/email_001_SI.txt"`, `"attachments/email_001_BL.txt"`.
- Attachment count distribution: `{0: 394, 1: 2, 2: 124}` (394 emails have 0 attachments, 2 emails have 1 attachment, 124 emails have 2 attachments).
- Any email with a count other than 2 — list its id: 394 emails with 0 attachments (e.g. email_002, email_003, email_006, email_007, email_008, ...); 2 emails with 1 attachment: `email_507` (`attachments/email_507_SI.txt` only) and `email_509` (`attachments/email_509_SI.txt` only).
- Naming convention: `attachments/email_<NNN>_<SI|BL>.<ext>`, where `<NNN>` matches the email's own `email_NNN` id, and ext is one of txt/pdf/xlsx/docx. Verified 0 filenames deviate from the regex `email_(\d+)_(SI|BL)\.(txt|pdf|xlsx|docx)$`.
- How you can tell an SI from a BL from the filename alone: the filename itself contains `_SI.` or `_BL.` immediately before the extension — this is sufficient and reliable (no exceptions found).

## 6. Attachment formats
| extension | count | text-based or scanned | example path |
|---|---|---|---|
| .txt | 192 | text-based (plain text) | attachments/email_001_BL.txt |
| .pdf | 28 | text-based (checked 3 samples with `pdftotext -l 1`: 1069, 1019, 774 chars — all well above the ~200-char scanned/text-based threshold) | attachments/email_059_BL.pdf |
| .xlsx | 22 | UNKNOWN — not opened (binary, outside the 3-sample-per-type text-reading budget and not inspectable via pdftotext) | attachments/email_005_BL.xlsx |
| .docx | 8 | UNKNOWN — not opened (binary) | attachments/email_055_BL.docx |

## 7. sample_submission.json
- Exact top-level shape: a single JSON object (dict) with 520 keys, one per email_id.
- Key used for each entry: the email_id string, e.g. `"email_001"`.
- Full verbatim example of ONE entry:
```json
{
  "category": "GENERAL",
  "status": "OK",
  "review_reason": null,
  "defect_fields": [],
  "has_defect": false
}
```
- Field names inside an entry: `category`, `status`, `review_reason`, `defect_fields`, `has_defect`.
- How a mismatch is represented: not attested in this file — every one of the 520 sample entries is identical (`category=GENERAL, status=OK, review_reason=null, defect_fields=[], has_defect=false`). Per `README.md`'s own worked example (not data, documentation text), a mismatch entry would look like `{"category": "BL_COMPARISON", "status": "MISMATCH", "review_reason": None, "has_defect": True, "defect_fields": ["consignee"]}`.
- How a no-mismatch case is represented: `status: "OK"`, `has_defect: false`, `defect_fields: []` (this is literally every row in the sample file).
- Whether escalation/uncertainty has any representation: yes — the `status` field per README can be `"NEEDS_REVIEW"`, paired with a `review_reason` of `wrong_doc_type | missing_attachment | unreadable | missing_value`; none of these values are attested in `sample_submission.json` itself (all 520 rows are `OK`/`null`).

## 8. Field labels seen in the documents
(from the one SI/BL pair read in full: attachments/email_001_SI.txt and attachments/email_001_BL.txt)

| canonical field | every label spelling seen | which document |
|---|---|---|
| shipper | "Shipper/Exporter:" | SI |
| shipper | "SHIPPER:" | BL |
| consignee | "CONSIGNEE:" | SI |
| consignee | "CONSIGNEE:" | BL |
| notify_party | "NOTIFY PARTY:" | SI |
| notify_party | "Notify:" | BL |
| port_of_loading | "Port of Loading:" | SI |
| port_of_loading | "Port of Loading (POL):" | BL |
| port_of_discharge | "Discharge Port:" | SI |
| port_of_discharge | "POD:" | BL |
| container_count | "No. of Containers or Packages:" | SI |
| container_count | "Container Count:" | BL |
| gross_weight_kg | "Gross Weight (KG):" | SI |
| gross_weight_kg | "Gross Wt (kgs):" | BL |

Other labels present but not in the 7 compared fields: "Kinds of Packages; Description of Goods:" / "Commodity:" (goods description), "HS Code:" (SI only), "Booking Ref:" (both), "OC No.:" (SI only), "Bill of Lading No.:" (BL only), "Vessel Name:" (both), "Voy. No:" / "Voyage:" (both), "Freight:" (both).

## 9. Units and number formats seen
- Weight: exact strings seen: `"21,577 KG"` (both SI and BL in email_001). Only one sample read — UNKNOWN whether other emails use a decimal format like "22,000.000 KGS"; not observed in the files actually opened.
- Container count: exact strings seen: `"1 x 40'HC"` (both SI and BL in email_001). UNKNOWN whether other container-count formats (e.g. "3 x 40'HC") appear elsewhere — not observed in the files actually opened (README rule 5 limits sampling to at most 3 files per type / 2 txt files read here).

## 10. loader.py surface
- class `Inbox(source)`
  - `emails(self)`
  - `__iter__(self)`
  - `get(self, email_id)`
  - `read_bytes(self, att_path)`
  - `read_text(self, att_path, encoding="utf-8")`
  - `submit(self, submission)`
  - `sample_submission(self)`
  - `_get_json(self, path)`
  - `_get_bytes(self, path)`

## 11. UNKNOWNS
1. Whether the `category` field ever takes any value other than `GENERAL` in any actual data file — ran `Counter(v['category'] for v in json.load(open('sample_submission.json')).values())`, result `Counter({'GENERAL': 520})`; the other four category names (`BL_COMPARISON`, `SI_REQUEST`, `INVOICE_QUERY`, `SPAM`) are only mentioned in README.md prose, never attested in data.
2. Whether `status` ever takes `MISMATCH` or `NEEDS_REVIEW` in any actual data file — ran `Counter(v['status'] for v in ...)`, result `Counter({'OK': 520})`.
3. Whether `.xlsx` and `.docx` attachments are text-extractable or scanned/image content — not opened (rule 4 restricts this check to PDFs via `pdftotext`; no equivalent command was in the allowed step list for xlsx/docx).
4. Full range of weight and container-count formats across the dataset — only 1 SI/BL pair (email_001) was read in full per rule 5's 2-file cap; ran `find . -name '*.txt' | head -6` then read 2 files.
5. Whether every email's `from` domain, or any other field, correlates with category — not computed; out of scope for a read-only survey per rule 1 (no analysis/design), and would require reading bodies of many emails beyond the sampling budget.
6. Ground truth / correct category-BL-vs-SI comparison outcomes — README states explicitly "You do NOT have ground truth"; no ground_truth.json file exists in the directory listing from Step 1.

## 12. Surprises
- `sample_submission.json` is not a representative sample of the label space: all 520 entries are byte-identical placeholder values (`GENERAL` / `OK` / `null` / `[]` / `false`), so it demonstrates JSON *shape* only, not category or status variety — that variety exists only as prose in README.md.
- 394 of 520 emails (over 75%) have zero attachments — the BL_COMPARISON workflow described in the README applies to a minority of the inbox; most emails (by attachment count) are presumably GENERAL/SPAM/SI_REQUEST/INVOICE_QUERY correspondence with no SI/BL pair to compare.
- 2 emails (email_507, email_509) have exactly 1 attachment (an SI with no matching BL) rather than the expected pair of 2 — these are natural candidates for a `NEEDS_REVIEW` / `missing_attachment` case per the README's review_reason vocabulary, though this is inference from counts, not something stated in a file.
- Filenames alone perfectly disambiguate SI vs BL and email owner (no naming exceptions found across 250 attachment files), so no content parsing is needed just to route/pair attachments.
