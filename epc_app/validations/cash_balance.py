import frappe
from frappe import _
from frappe.utils import flt
from erpnext.accounts.utils import get_balance_on


def _is_cash_account(account: str) -> bool:
    while account:
        row = frappe.db.get_value("Account", account, ["account_type", "parent_account"], as_dict=1)
        if not row:
            return False
        if row.account_type == "Cash":
            return True
        account = row.parent_account
    return False


def _amount_in_base(doc):
    # safest generic amount for “cash out”
    for f in ("base_paid_amount", "paid_amount", "base_grand_total", "grand_total"):
        if doc.meta.has_field(f) and doc.get(f) is not None:
            return flt(doc.get(f))
    return 0.0


def validate_cash_balance_before_submit(doc, method=None):
    if not doc.get("company"):
        return

    # Payment Entry: only when paying FROM cash
    if doc.doctype == "Payment Entry":
        if doc.get("payment_type") != "Pay":
            return
        cash_account = doc.get("paid_from")
        if not _is_cash_account(cash_account):
            return

        amount = flt(doc.get("paid_amount") or 0)
        bal = flt(get_balance_on(account=cash_account, date=doc.get("posting_date"), company=doc.company))
        if bal <= 0 or bal < amount:
            frappe.throw(
                _("Cash account balance is insufficient. Account: {0}, Balance: {1}, Required: {2}")
                .format(cash_account, bal, amount),
                title=_("Insufficient Cash Balance"),
            )

    # Purchase Invoice: only when paid + cash_bank_account is Cash
    if doc.doctype == "Purchase Invoice":
        if not doc.get("is_paid"):
            return
        cash_account = doc.get("cash_bank_account")
        if not _is_cash_account(cash_account):
            return

        amount = _amount_in_base(doc)
        bal = flt(get_balance_on(account=cash_account, date=doc.get("posting_date"), company=doc.company))
        if bal <= 0 or bal < amount:
            frappe.throw(
                _("Cash account balance is insufficient. Account: {0}, Balance: {1}, Required: {2}")
                .format(cash_account, bal, amount),
                title=_("Insufficient Cash Balance"),
            )
