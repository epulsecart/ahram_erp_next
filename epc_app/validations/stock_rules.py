import frappe
from frappe import _

def enforce_update_stock_and_warehouse(doc, method=None):
    # Force update_stock always (Sales Invoice + Purchase Invoice)
    if doc.meta.has_field("update_stock"):
        doc.update_stock = 1

    # Sales Invoice: require set_warehouse + ensure item warehouses
    if doc.doctype == "Sales Invoice":
        if not doc.get("set_warehouse"):
            frappe.throw(_("Set Warehouse is mandatory."))

        for row in (doc.get("items") or []):
            # if row has is_stock_item and it's false, skip
            if row.meta.has_field("is_stock_item") and not row.get("is_stock_item"):
                continue

            if not row.get("warehouse"):
                row.warehouse = doc.set_warehouse

        missing = [
            str(r.idx) for r in (doc.get("items") or [])
            if (not r.get("warehouse"))
            and (not (r.meta.has_field("is_stock_item") and not r.get("is_stock_item")))
        ]
        if missing:
            frappe.throw(_("Warehouse missing in item rows: {0}").format(", ".join(missing)))
