import frappe
from frappe.utils import flt

def _get_company(company: str | None) -> str | None:
    return company or frappe.defaults.get_user_default("Company")

def _get_company_warehouses(company: str | None):
    company = _get_company(company)

    meta = frappe.get_meta("Warehouse")
    filters = {"disabled": 0}

    # If Warehouse has a company field, filter by it
    if company and meta.has_field("company"):
        filters["company"] = company

    return frappe.get_all("Warehouse", filters=filters, pluck="name")

def _available(actual_qty, reserved_qty):
    return flt(actual_qty) - flt(reserved_qty)

@frappe.whitelist()
def get_item_availability_all_warehouses(item_code, company=None, hide_zero=1):
    """
    Returns availability for ONE item across ALL warehouses:
    available = actual_qty - reserved_qty
    hide_zero: if 1, hide warehouses where available == 0 (keep negative)
    """
    if not item_code:
        return {"item_code": item_code, "company": _get_company(company), "rows": []}

    whs = set(_get_company_warehouses(company))
    if not whs:
        return {"item_code": item_code, "company": _get_company(company), "rows": []}

    bins = frappe.db.sql(
        """
        select warehouse, actual_qty, reserved_qty
        from `tabBin`
        where item_code = %s
        """,
        (item_code,),
        as_dict=True,
    )

    out = []
    for b in bins:
        wh = b.get("warehouse")
        if wh not in whs:
            continue
        av = _available(b.get("actual_qty"), b.get("reserved_qty"))
        if flt(hide_zero) and av == 0:
            continue
        out.append({"warehouse": wh, "available_qty": av})

    out.sort(key=lambda x: x["available_qty"], reverse=True)
    return {"item_code": item_code, "company": _get_company(company), "rows": out}


@frappe.whitelist()
def get_items_availability_all_warehouses(item_codes, company=None, hide_zero=1):
    """
    Returns availability for MANY items across ALL warehouses (hide zeros).
    item_codes: JSON list of item codes
    """
    item_codes = frappe.parse_json(item_codes) or []
    item_codes = [c for c in item_codes if c]
    item_codes = list(dict.fromkeys(item_codes))  # unique, keep order

    whs = set(_get_company_warehouses(company))
    if not item_codes or not whs:
        return {"company": _get_company(company), "rows": []}

    bins = frappe.db.sql(
        """
        select item_code, warehouse, actual_qty, reserved_qty
        from `tabBin`
        where item_code in %(items)s
        """,
        {"items": tuple(item_codes)},
        as_dict=True,
    )

    out = []
    for b in bins:
        wh = b.get("warehouse")
        if wh not in whs:
            continue
        av = _available(b.get("actual_qty"), b.get("reserved_qty"))
        if flt(hide_zero) and av == 0:
            continue
        out.append({
            "item_code": b.get("item_code"),
            "warehouse": wh,
            "available_qty": av
        })

    # stable grouping: sort by item_code order, then available desc
    order = {code: i for i, code in enumerate(item_codes)}
    out.sort(key=lambda x: (order.get(x["item_code"], 10**9), -x["available_qty"]))
    return {"company": _get_company(company), "rows": out}


@frappe.whitelist()
def get_item_metrics(items):
    """
    Existing popup helper (gross profit preview per row warehouse).
    items: JSON list [{item_code, warehouse, qty, rate, base_net_rate}]
    """
    rows = frappe.parse_json(items) or []
    keys = [(r.get("item_code"), r.get("warehouse")) for r in rows if r.get("item_code") and r.get("warehouse")]
    keys = list({k for k in keys})

    metrics = {}
    if keys:
        for item_code, warehouse in keys:
            b = frappe.db.get_value(
                "Bin",
                {"item_code": item_code, "warehouse": warehouse},
                ["actual_qty", "valuation_rate"],
                as_dict=True,
            ) or {}
            metrics[(item_code, warehouse)] = {
                "available_qty": flt(b.get("actual_qty")),
                "cost_rate": flt(b.get("valuation_rate")),
            }

    out_lines = []
    total_profit = 0.0

    for r in rows:
        item_code = r.get("item_code")
        warehouse = r.get("warehouse")
        qty = flt(r.get("qty"))
        sell_rate = flt(r.get("base_net_rate") or r.get("rate") or 0)

        m = metrics.get((item_code, warehouse), {"available_qty": 0.0, "cost_rate": 0.0})
        cost_rate = flt(m["cost_rate"])

        profit = flt((sell_rate - cost_rate) * qty)
        total_profit += profit

        out_lines.append({
            "item_code": item_code,
            "warehouse": warehouse,
            "qty": qty,
            "sell_rate": sell_rate,
            "available_qty": flt(m["available_qty"]),
            "cost_rate": cost_rate,
            "profit": profit,
        })

    return {"lines": out_lines, "total_profit": flt(total_profit)}
