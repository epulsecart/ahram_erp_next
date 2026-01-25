frappe.ui.form.on("EPC Price Sheet", {
    refresh(frm) {
      if (!frm.is_new()) {
        frm.add_custom_button(__("Generate Items"), () => {
          frm.call("generate_items").then(() => {
            frm.refresh_field("lines");
          });
        });
      }
    },
  });
  