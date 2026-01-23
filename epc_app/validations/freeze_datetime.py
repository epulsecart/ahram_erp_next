import frappe
from frappe.utils import nowdate, nowtime

FREEZE_FIELDS = {
    "Sales Invoice": ["posting_date", "posting_time"],
    "Purchase Invoice": ["posting_date", "posting_time"],
    "Payment Entry": ["posting_date"],
    "Journal Entry": ["posting_date"],
    "Sales Order": ["transaction_date"],
    "Quotation": ["transaction_date"],
}

def validate_freeze_datetime(doc, method=None):
    meta = frappe.get_meta(doc.doctype)
    fields = [f for f in FREEZE_FIELDS.get(doc.doctype, []) if meta.has_field(f)]
    if not fields:
        return

    # NEW: system sets values
    if doc.is_new():
        for f in fields:
            doc.set(f, nowtime() if f.endswith("_time") else nowdate())
        return

    # EXISTING: enforce DB values (no blocking)
    for f in fields:
        db_val = frappe.db.get_value(doc.doctype, doc.name, f)
        if db_val is not None:
            doc.set(f, db_val)
        else:
            doc.set(f, nowtime() if f.endswith("_time") else nowdate())
