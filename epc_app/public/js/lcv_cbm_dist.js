(() => {
    // ===== keep it simple: safe number helpers (no frappe flt dependency) =====
    const flt = (v) => {
      const n = parseFloat(v);
      return Number.isFinite(n) ? n : 0;
    };
    const cint = (v) => {
      const n = parseInt(v, 10);
      return Number.isFinite(n) ? n : 0;
    };
  
    const MANUAL = "Distribute Manually";
  
    // IMPORTANT: confirm these 2 fieldnames
    const ITEM_CBM_FIELD = "custom_cbm"; // on Item
    const LCV_CBM_FIELD = "custom_cbm";  // on Landed Cost Item row
  
    const currencyPrecision = () => cint(frappe?.boot?.sysdefaults?.currency_precision || 2);
    const r2 = (v) => {
      const p = currencyPrecision();
      return parseFloat((flt(v)).toFixed(p));
    };
  
    function get_total_extra(frm) {
      // LCV charges table is usually fieldname "taxes"
      const taxes = frm.doc.taxes || frm.doc.taxes_and_charges || [];
      return taxes.reduce((sum, t) => sum + flt(t.amount), 0);
    }
  
    function get_items(frm) {
      return frm.doc.items || [];
    }
  
    function get_item_weight(row) {
      const cbm = flt(row[LCV_CBM_FIELD] || 0);
      const qty = flt(row.qty || 0);
      return cbm * qty;
    }
  
    async function fill_cbm_from_item(frm) {
      frm.__cbm_cache = frm.__cbm_cache || {};
  
      const rows = get_items(frm);
      const promises = rows.map((r) => {
        if (!r.item_code) return Promise.resolve();
        if (flt(r[LCV_CBM_FIELD] || 0) > 0) return Promise.resolve();
  
        if (frm.__cbm_cache[r.item_code] !== undefined) {
          return frappe.model.set_value(r.doctype, r.name, LCV_CBM_FIELD, frm.__cbm_cache[r.item_code] || 0);
        }
  
        return frappe.db.get_value("Item", r.item_code, ITEM_CBM_FIELD).then((res) => {
          const v = flt(res?.message?.[ITEM_CBM_FIELD] || 0);
          frm.__cbm_cache[r.item_code] = v;
          return frappe.model.set_value(r.doctype, r.name, LCV_CBM_FIELD, v);
        });
      });
  
      await Promise.all(promises);
      frm.refresh_field("items");
    }
  
    function distribute_by_cbm(frm) {
      if (frm.__cbm_dist_running) return;
      if ((frm.doc.distribute_charges_based_on || "") !== MANUAL) return;
  
      const items = get_items(frm);
      if (!items.length) return;
  
      const total = flt(get_total_extra(frm));
  
      // If no extra charges, clear allocations
      if (!total) {
        frm.__cbm_dist_running = true;
        try {
          items.forEach((row) => {
            frappe.model.set_value(row.doctype, row.name, "applicable_charges", 0);
          });
          frm.refresh_field("items");
        } finally {
          frm.__cbm_dist_running = false;
        }
        return;
      }
  
      const weights = items.map(get_item_weight);
      const sumW = weights.reduce((s, w) => s + w, 0);
  
      if (!sumW) {
        if (!frm.__cbm_warned) {
          frm.__cbm_warned = true;
          frappe.msgprint({
            title: __("CBM Distribution"),
            indicator: "orange",
            message: __("Can't distribute because all (CBM × Qty) weights are zero. Fill CBM and Qty first."),
          });
        }
        return;
      } else {
        frm.__cbm_warned = false;
      }
  
      // Put rounding adjustment on last row with weight>0
      let lastIdx = -1;
      for (let i = weights.length - 1; i >= 0; i--) {
        if (weights[i] > 0) { lastIdx = i; break; }
      }
      if (lastIdx === -1) lastIdx = weights.length - 1;
  
      frm.__cbm_dist_running = true;
      try {
        let allocated = 0;
  
        for (let i = 0; i < items.length; i++) {
          const row = items[i];
          let val = 0;
  
          if (i === lastIdx) {
            val = r2(total - allocated);
          } else {
            val = weights[i] > 0 ? r2(total * (weights[i] / sumW)) : 0;
            allocated += val;
          }
  
          frappe.model.set_value(row.doctype, row.name, "applicable_charges", val);
        }
  
        frm.refresh_field("items");
      } finally {
        frm.__cbm_dist_running = false;
      }
    }
  
    async function fill_then_distribute(frm) {
      await fill_cbm_from_item(frm);
      distribute_by_cbm(frm);
    }
  
    // ===== Parent triggers =====
    frappe.ui.form.on("Landed Cost Voucher", {
      distribute_charges_based_on(frm) {
        // user just chose Distribute Manually -> allocate now
        setTimeout(() => distribute_by_cbm(frm), 50);
      },
  
      get_items_from_purchase_receipts(frm) {
        setTimeout(() => fill_then_distribute(frm), 900);
      },
  
      // some setups use this method name
      get_items_from_purchase_invoices(frm) {
        setTimeout(() => fill_then_distribute(frm), 900);
      },
  
      refresh(frm) {
        // if items already exist, make sure cbm is filled and allocations updated
        if ((frm.doc.items || []).length) {
          setTimeout(() => fill_then_distribute(frm), 300);
        }
      },
    });
  
    // ===== Child triggers =====
    const item_triggers = {
      qty(frm) { distribute_by_cbm(frm); },
      item_code(frm) { setTimeout(() => fill_then_distribute(frm), 200); },
    };
    item_triggers[LCV_CBM_FIELD] = function(frm) { distribute_by_cbm(frm); };
    frappe.ui.form.on("Landed Cost Item", item_triggers);
  
    frappe.ui.form.on("Landed Cost Taxes and Charges", {
      amount(frm) { distribute_by_cbm(frm); },
    });
  })();
  