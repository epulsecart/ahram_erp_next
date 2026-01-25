import frappe
from frappe.model.document import Document
from frappe.utils import flt
from erpnext.accounts.utils import get_balance_on

class EPCAccountConfirmation(Document):
    def validate(self):
        self._apply_account_type_to_party_type()
        self._set_currency()
        self._compute_balance()

    def _apply_account_type_to_party_type(self):
        # party_type is a Link to DocType, so we set it to valid DocType names
        if self.account_type == "Accounts Receivable":
            self.party_type = "Customer"
        elif self.account_type == "Accounts Payable":
            self.party_type = "Supplier"

    def _set_currency(self):
        if self.company:
            self.currency = frappe.db.get_value("Company", self.company, "default_currency") or self.currency

    def _compute_balance(self):
        if not (self.company and self.party_type and self.party and self.as_on_date):
            return

        self.balance = flt(get_balance_on(
            date=self.as_on_date,
            party_type=self.party_type,
            party=self.party,
            company=self.company
        ) or 0)
