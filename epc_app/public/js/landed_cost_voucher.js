(() => {
  const flt = (typeof window.flt === "function")
    ? window.flt
    : (v) => {
        const n = parseFloat(v);
        return Number.isFinite(n) ? n : 0;
      };

  async function fill_cbm_from_item(frm) {
    frm.__cbm_cache = frm.__cbm_cache || {};

    const rows = frm.doc.items || [];
    const promises = rows.map((r) => {
      if (!r.item_code) return Promise.resolve();
      if (flt(r.custom_cbm || 0) > 0) return Promise.resolve();

      if (frm.__cbm_cache[r.item_code] !== undefined) {
        return frappe.model.set_value(r.doctype, r.name, "custom_cbm", frm.__cbm_cache[r.item_code] || 0);
      }

      return frappe.db.get_value("Item", r.item_code, "custom_cbm").then((res) => {
        const v = flt(res?.message?.custom_cbm || 0);
        frm.__cbm_cache[r.item_code] = v;
        return frappe.model.set_value(r.doctype, r.name, "custom_cbm", v);
      });
    });

    await Promise.all(promises);
  }

  frappe.ui.form.on("Landed Cost Voucher", {
    get_items_from_purchase_receipts(frm) {
      setTimeout(() => fill_cbm_from_item(frm), 600);
    },
    get_items_from_purchase_invoices(frm) {
      setTimeout(() => fill_cbm_from_item(frm), 600);
    },
  });
})();
