"""A worked example for the "try it yourself" form.

An empty textarea is a wall. This pair is realistic — the shapes, labels and
punctuation come from the corpus — and carries ONE planted defect, so a visitor's
first click finds something instead of returning OK and looking broken.

The defect is a discharge-port change, which is the expensive one in practice: a
container that sails to the wrong port is slow and costly to unwind once the vessel
has left. The shipper is spelled with different legal-suffix punctuation on the two
documents (`SDN BHD` / `SDN. BHD.`) so the visitor can also see the system NOT
flagging something that merely looks different.
"""
from __future__ import annotations

SAMPLE = {
    "subject": "DRAFT BL CHECK - 5RFR-88214 - HAMBURG - MEGA RUBBER GLOVE SDN BHD",
    "body": (
        "Hi Ooi,\n\n"
        "Please find attached our shipping instruction and the carrier's draft "
        "bill of lading for booking 5RFR-88214.\n\n"
        "Kindly compare the two and confirm the discrepancies before the vessel "
        "cut-off on Friday.\n\n"
        "Best regards,\nWilly"
    ),
    "si_text": (
        "SHIPPING INSTRUCTION\n"
        "========================================\n"
        "Shipper: MEGA RUBBER GLOVE SDN BHD\n"
        "  LOT 5, JALAN PERUSAHAAN, 81700 PASIR GUDANG, JOHOR, MALAYSIA\n"
        "Consignee: NORDIC HEALTHCARE SERVICES GMBH\n"
        "  HAFENSTRASSE 42, 20457 HAMBURG, GERMANY\n"
        "Notify Party: SAME AS CONSIGNEE\n"
        "Port of Loading: PORT KLANG (MYPKG)\n"
        "Port of Discharge: HAMBURG, GERMANY (DEHAM)\n"
        "No. of Containers: 2 x 40'HC\n"
        "GROSS WEIGHT: 22,450.50 KGS\n"
    ),
    "bl_text": (
        "BILL OF LADING (DRAFT)\n"
        "========================================\n"
        "Shipper: MEGA RUBBER GLOVE SDN. BHD.\n"
        "  LOT 5, JALAN PERUSAHAAN, 81700 PASIR GUDANG, JOHOR, MALAYSIA\n"
        "Consignee: NORDIC HEALTHCARE SERVICES GMBH\n"
        "  HAFENSTRASSE 42, 20457 HAMBURG, GERMANY\n"
        "NOTIFY PARTY: NORDIC HEALTHCARE SERVICES GMBH\n"
        "POL: PORT KLANG (MYPKG)\n"
        "Port of Discharge: ROTTERDAM, NETHERLANDS (DEHAM)\n"
        "Container Count: 2 x 40'HC\n"
        "Gross Weight (KG): 22.450,50 KGS\n"
    ),
    "expect": [
        "port_of_discharge is a DEFECT: HAMBURG vs ROTTERDAM — and note both "
        "documents still carry the same stale code (DEHAM), which is exactly why "
        "port-code resolution is switched off.",
        "shipper MATCHES despite 'SDN BHD' vs 'SDN. BHD.' — the same legal suffix, "
        "differently punctuated.",
        "notify_party MATCHES: the SI says 'SAME AS CONSIGNEE', which is resolved "
        "against that document's own consignee and labelled as inferred.",
        "gross_weight_kg MATCHES: '22,450.50' and '22.450,50' are the same number "
        "written with US and European separators.",
    ],
}
