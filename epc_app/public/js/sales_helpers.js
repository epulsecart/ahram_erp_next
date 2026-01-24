(() => {
    const SEQ_MS = 700;
    const TARGET_DOCTYPES = new Set(["Sales Invoice", "Sales Order", "Quotation"]);
  
    function get_company(frm) {
      return frm.doc.company || frappe.defaults.get_user_default("Company");
    }
  
    function uniq(arr) {
      return [...new Set(arr.filter(Boolean))];
    }
  
    // ===== Static Panel =====
    function ensure_panel(frm) {
      if (frm.__epc_qty_panel) return;
  
      const field = frm.get_field("items");
      if (!field || !field.grid || !field.grid.wrapper) return;
  
      const $grid = $(field.grid.wrapper);
      const $panel = $(`
        <div class="epc-qty-panel" dir="rtl" style="text-align:right;margin-top:10px;border:1px solid var(--border-color);border-radius:8px;padding:10px;">
          <div style="display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap;">
            <div style="font-weight:700;">المتوفر في جميع المستودعات</div>
            <div style="opacity:.8;font-size:12px;" class="epc-qty-subtitle">اختر سطر صنف لعرض الكميات</div>
          </div>
          <div class="epc-qty-body" style="margin-top:8px;">
            <div style="opacity:.7;">لا يوجد صنف محدد.</div>
          </div>
        </div>
      `);
  
      $grid.after($panel);
  
      frm.__epc_qty_panel = $panel;
      frm.__epc_qty_body = $panel.find(".epc-qty-body");
      frm.__epc_qty_subtitle = $panel.find(".epc-qty-subtitle");
    }
  
    function panel_table(item_code, rows) {
      const body = rows.map(r => `
        <tr>
          <td>${frappe.utils.escape_html(r.warehouse || "")}</td>
          <td style="text-align:left">${frappe.format(r.available_qty, {fieldtype:"Float"})}</td>
        </tr>
      `).join("");
  
      return `
        <div style="margin-bottom:6px;">
          <span style="font-weight:700;">الصنف:</span>
          <span>${frappe.utils.escape_html(item_code || "")}</span>
        </div>
        <div style="max-height:240px;overflow:auto;">
          <table class="table table-bordered">
            <tr><th>المستودع</th><th style="text-align:left">المتوفر</th></tr>
            ${body}
          </table>
        </div>
      `;
    }
  
    async function load_item_all_wh(frm, item_code) {
      ensure_panel(frm);
      if (!frm.__epc_qty_body) return;
  
      if (!item_code) {
        frm.__epc_qty_body.html(`<div style="opacity:.7;">لا يوجد صنف محدد.</div>`);
        return;
      }
  
      frm.__epc_qty_subtitle.text(`يتم التحميل...`);
      frm.__epc_qty_body.html(`<div style="opacity:.7;">جاري جلب الكميات...</div>`);
  
      const company = get_company(frm);
  
      const r = await frappe.call({
        method: "epc_app.api.item_metrics.get_item_availability_all_warehouses",
        args: { item_code, company, hide_zero: 1 }
      });
  
      const rows = (r.message && r.message.rows) || [];
      frm.__epc_qty_subtitle.text(`عرض (المتوفر = الفعلي - المحجوز) | إخفاء الصفر`);
  
      if (!rows.length) {
        frm.__epc_qty_body.html(`<div style="opacity:.7;">لا يوجد رصيد متاح لهذا الصنف في أي مستودع.</div>`);
        return;
      }
  
      frm.__epc_qty_body.html(panel_table(item_code, rows));
    }
  
    function bind_row_click(frm) {
      if (frm.__epc_qty_click_bound) return;
      const field = frm.get_field("items");
      if (!field || !field.grid || !field.grid.wrapper) return;
  
      frm.__epc_qty_click_bound = true;
  
      $(field.grid.wrapper).on("click", ".grid-row[data-name]", function () {
        const cdn = $(this).attr("data-name");
        const cdt = field.grid.doctype;
        const row = (locals[cdt] && locals[cdt][cdn]) || null;
        if (row && row.item_code) {
          frm.__epc_selected_item_code = row.item_code;
          load_item_all_wh(frm, row.item_code);
        }
      });
    }
  
    // Refresh panel if user changes item_code on the selected row
    function bind_child_triggers() {
      ["Sales Invoice Item", "Sales Order Item", "Quotation Item"].forEach((cdt) => {
        frappe.ui.form.on(cdt, {
          item_code(frm, cdt, cdn) {
            if (!frm.__epc_selected_item_code) return;
            const row = locals[cdt] && locals[cdt][cdn];
            if (!row) return;
            // if the user is editing the selected row, refresh
            // (best-effort: refresh when item_code changes anywhere)
            frm.__epc_selected_item_code = row.item_code;
            load_item_all_wh(frm, row.item_code);
          },
        });
      });
    }
  
    // ===== C+V popup (all items in doc -> all warehouses) =====
    function rows_item_codes(frm) {
      return uniq((frm.doc.items || []).map(r => r.item_code));
    }
  
    function html_doc_qty_table(rows) {
      const body = rows.map(r => `
        <tr>
          <td>${frappe.utils.escape_html(r.item_code || "")}</td>
          <td>${frappe.utils.escape_html(r.warehouse || "")}</td>
          <td style="text-align:left">${frappe.format(r.available_qty, {fieldtype:"Float"})}</td>
        </tr>
      `).join("");
  
      return `
        <div dir="rtl" style="text-align:right;max-height:60vh;overflow:auto">
          <table class="table table-bordered">
            <tr><th>الصنف</th><th>المستودع</th><th style="text-align:left">المتوفر</th></tr>
            ${body}
          </table>
        </div>
      `;
    }
  
    async function show_doc_quantities(frm) {
      const company = get_company(frm);
      const item_codes = rows_item_codes(frm);
  
      if (!item_codes.length) {
        frappe.msgprint("لا توجد أصناف داخل المستند.");
        return;
      }
  
      const r = await frappe.call({
        method: "epc_app.api.item_metrics.get_items_availability_all_warehouses",
        args: { item_codes, company, hide_zero: 1 }
      });
  
      const rows = (r.message && r.message.rows) || [];
      if (!rows.length) {
        frappe.msgprint("لا يوجد رصيد متاح لأي صنف في أي مستودع.");
        return;
      }
  
      frappe.msgprint({
        title: "الكميات المتوفرة (كل الأصناف / كل المستودعات)",
        message: html_doc_qty_table(rows),
        indicator: "blue",
        wide: true,
      });
    }
  
    // ===== Existing Z+X gross profit popup stays as-is (per row warehouse) =====
    function rows_payload_for_profit(frm) {
      const set_wh = frm.doc.set_warehouse;
      return (frm.doc.items || [])
        .map((r) => ({
          item_code: r.item_code,
          warehouse: r.warehouse || set_wh,
          qty: r.qty,
          rate: r.rate,
          base_net_rate: r.base_net_rate,
        }))
        .filter((r) => r.item_code && r.warehouse);
    }
  
    function html_profit_table(lines) {
      const header = `<tr>
        <th>الصنف</th><th>المستودع</th><th>الكمية</th><th>سعر البيع</th><th>التكلفة</th><th>الربح</th>
      </tr>`;
  
      const body = lines.map(l => `
        <tr>
          <td>${frappe.utils.escape_html(l.item_code || "")}</td>
          <td>${frappe.utils.escape_html(l.warehouse || "")}</td>
          <td>${frappe.format(l.qty, {fieldtype:"Float"})}</td>
          <td>${frappe.format(l.sell_rate, {fieldtype:"Currency"})}</td>
          <td>${frappe.format(l.cost_rate, {fieldtype:"Currency"})}</td>
          <td>${frappe.format(l.profit, {fieldtype:"Currency"})}</td>
        </tr>
      `).join("");
  
      return `
        <div dir="rtl" style="text-align:right;max-height:55vh;overflow:auto">
          <table class="table table-bordered">${header}${body}</table>
        </div>
      `;
    }
  
    async function fetch_profit(frm) {
      const items = rows_payload_for_profit(frm);
      if (!items.length) {
        frappe.msgprint("لا توجد أصناف مع مستودع لحساب الربح. حدّد (تحديد المستودع) أو مستودع السطر.");
        return null;
      }
  
      const r = await frappe.call({
        method: "epc_app.api.item_metrics.get_item_metrics",
        args: { items },
      });
  
      return r.message;
    }
  
    async function show_gross_profit(frm) {
      const data = await fetch_profit(frm);
      if (!data) return;
  
      frappe.msgprint({
        title: `معاينة الربح الإجمالي (الإجمالي: ${frappe.format(data.total_profit, { fieldtype: "Currency" })})`,
        message: html_profit_table(data.lines || []),
        indicator: "green",
        wide: true,
      });
    }
  
    // ===== Global shortcut binding =====
    function bind_global() {
      if (window.__epc_sales_helpers_bound) return;
      window.__epc_sales_helpers_bound = true;
  
      let prevKey = null;
      let prevTs = 0;
  
      document.addEventListener(
        "keydown",
        (e) => {
          const frm = window.cur_frm;
          if (!frm || !TARGET_DOCTYPES.has(frm.doctype)) return;
  
          const k = (e.key || "").toLowerCase();
          const now = Date.now();
  
          const dt = now - prevTs;
          const pk = prevKey;
  
          prevKey = k;
          prevTs = now;
  
          if (dt > SEQ_MS) return;
  
          // c ثم v => كل الأصناف / كل المستودعات
          if (pk === "c" && k === "v") {
            e.preventDefault();
            show_doc_quantities(frm);
          }
  
          // z ثم x => الربح الإجمالي
          if (pk === "z" && k === "x") {
            e.preventDefault();
            show_gross_profit(frm);
          }
        },
        true
      );
    }
  
    function init_form(frm) {
      ensure_panel(frm);
      bind_row_click(frm);
  
      // auto-refresh panel if we already have a selected item
      if (frm.__epc_selected_item_code) {
        load_item_all_wh(frm, frm.__epc_selected_item_code);
      }
    }
  
    // bind once
    bind_global();
    bind_child_triggers();
  
    ["Sales Invoice", "Sales Order", "Quotation"].forEach((dt) => {
      frappe.ui.form.on(dt, {
        refresh(frm) {
          init_form(frm);
        },
        company(frm) {
          // company changed -> refresh selected item panel
          if (frm.__epc_selected_item_code) {
            load_item_all_wh(frm, frm.__epc_selected_item_code);
          }
        }
      });
    });
    
  })();
  