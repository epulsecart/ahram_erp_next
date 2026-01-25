import frappe
from frappe.model.document import Document
from frappe.utils import today
from frappe import _

def _descendant_item_groups(root_group: str) -> list[str]:
    if not root_group:
        return []
    lft, rgt = frappe.db.get_value("Item Group", root_group, ["lft", "rgt"]) or (None, None)
    if lft is None:
        return [root_group]
    return frappe.get_all(
        "Item Group",
        filters={"lft": (">=", lft), "rgt": ("<=", rgt)},
        pluck="name",
    )

def _get_item_price_rate(price_list: str, item_code: str) -> float | None:
    t = today()
    rows = frappe.get_all(
        "Item Price",
        filters={"price_list": price_list, "item_code": item_code},
        fields=["price_list_rate", "valid_from", "valid_upto", "modified"],
        order_by="valid_from desc, modified desc",
        limit=50,
    )

    for r in rows:
        vf = r.get("valid_from")
        vu = r.get("valid_upto")
        if vf and str(vf) > t:
            continue
        if vu and str(vu) < t:
            continue
        return float(r.get("price_list_rate") or 0)

    return None

def _rule_applies_to_item(rule_doc, item_doc, price_list: str) -> bool:
    if getattr(rule_doc, "disable", 0):
        return False
    if getattr(rule_doc, "selling", 0) != 1:
        return False

    # If Pricing Rule is tied to a specific price list, it must match
    for_pl = getattr(rule_doc, "for_price_list", None)
    if for_pl and for_pl != price_list:
        return False

    apply_on = (getattr(rule_doc, "apply_on", "") or "").strip()

    if not apply_on:
        return True  # global rule

    if apply_on == "Item Code":
        codes = {d.item_code for d in (rule_doc.get("items") or []) if d.item_code}
        return item_doc.name in codes

    if apply_on == "Item Group":
        groups = {d.item_group for d in (rule_doc.get("item_groups") or []) if d.item_group}
        if not groups:
            return False
        # treat rule groups as “parent allowed”: if item group is within any selected group subtree
        item_group = item_doc.item_group
        if not item_group:
            return False
        for g in groups:
            if item_group in _descendant_item_groups(g):
                return True
        return False

    if apply_on == "Brand":
        brands = {d.brand for d in (rule_doc.get("brands") or []) if d.brand}
        return bool(item_doc.brand and item_doc.brand in brands)

    # other apply_on modes are not item-specific for our sheet
    return False

def _apply_rule(rule_doc, before_rate: float) -> tuple[float, float]:
    before = float(before_rate or 0)

    porpd = (getattr(rule_doc, "price_or_product_discount", "") or "").strip()

    # We only support PRICE rules (rate/discount). PRODUCT rules are for free items/schemes.
    if porpd and porpd != "Price":
        return (0.0, 0.0)

    rod = (getattr(rule_doc, "rate_or_discount", "") or "").strip()

    if rod == "Rate":
        rate = float(getattr(rule_doc, "rate", 0) or 0)
        return (rate if rate > 0 else 0.0, 0.0)

    if rod == "Discount Percentage":
        dp = float(getattr(rule_doc, "discount_percentage", 0) or 0)
        if dp <= 0:
            return (0.0, 0.0)
        return (before * (1 - dp / 100.0), dp)

    if rod == "Discount Amount":
        da = float(getattr(rule_doc, "discount_amount", 0) or 0)
        if da <= 0:
            return (0.0, 0.0)
        after = before - da
        dp = (da / before * 100.0) if before else 0.0
        return (after, dp)

    return (0.0, 0.0)

class EPCPriceSheet(Document):
    @frappe.whitelist()
    def generate_items(self):
        if self.is_new():
            frappe.throw(_("Save the document first."))

        if not self.price_list or not self.pricing_rule:
            frappe.throw(_("Price List and Pricing Rule are required."))

        rule = frappe.get_doc("Pricing Rule", self.pricing_rule)

        group_filter = {}
        if self.item_group:
            group_filter["item_group"] = ("in", _descendant_item_groups(self.item_group))

        # Start with items that have a price in the selected price list
        price_item_codes = frappe.get_all(
            "Item Price",
            filters={"price_list": self.price_list},
            pluck="item_code",
        )
        price_item_codes = sorted(set([x for x in price_item_codes if x]))

        if not price_item_codes:
            self.set("lines", [])
            self.save()
            return

        items = frappe.get_all(
            "Item",
            filters={
                "name": ("in", price_item_codes),
                "disabled": 0,
                "is_sales_item": 1,
                **group_filter,
            },
            fields=["name", "item_name", "image", "item_group", "brand"],
            order_by="item_name asc",
        )

        out = []
        for it in items:
            before = _get_item_price_rate(self.price_list, it["name"])
            if not before or before <= 0:
                continue  # no price in price list => skip

            item_doc = frappe._dict(it)
            if not _rule_applies_to_item(rule, item_doc, self.price_list):
                continue  # not covered by the selected pricing rule => skip

            after, disc_p = _apply_rule(rule, before)
            if not after or after <= 0:
                continue  # rule has no usable per-item effect => skip

            out.append({
                "item_code": it["name"],
                "item_name": it.get("item_name"),
                "image": it.get("image"),
                "before_rate": before,
                "after_rate": after,
                "discount_percent": disc_p,
            })

        self.set("lines", [])
        for row in out:
            self.append("lines", row)

        self.save()
