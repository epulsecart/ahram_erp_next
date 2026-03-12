// Copyright (c) 2026, yahya basalama and contributors
// For license information, please see license.txt

function formatNoonPipelineResult(result) {
	const lines = [];
	const results = result?.results || {};
	const analyze = results.analyze_batch || {};
	const files = analyze.files || {};
	const validation = results.validate_batch_ready || {};
	const blockingIssues = validation.blocking_issues || [];
	const warnings = validation.warnings || [];
	const mappingReport = results.missing_item_mapping_report || null;
	const unresolvedFromReport = Array.isArray(mappingReport?.item_mappings_needed)
		? mappingReport.item_mappings_needed.filter((row) => !row?.mapped_item_code)
		: [];
	const unresolvedPreviewFromBackend = Array.isArray(results.unresolved_item_mappings_preview)
		? results.unresolved_item_mappings_preview
		: [];
	const unresolvedPreviewRows = unresolvedPreviewFromBackend.length
		? unresolvedPreviewFromBackend
		: unresolvedFromReport.slice(0, 20);
	const unresolvedCountValue = Number(results.unresolved_item_mappings_count);
	const unresolvedItemMappingsCount = Number.isFinite(unresolvedCountValue) && unresolvedCountValue >= 0
		? unresolvedCountValue
		: unresolvedFromReport.length;
	const hasUnresolvedItemMappings =
		unresolvedItemMappingsCount > 0 || Boolean(mappingReport);

	const getReadablePartnerSku = (row) => {
		if (!row || typeof row !== "object") return "";
		return row.partner_sku || row.partnerSku || row.sku || "";
	};
	const hasBlockingIssues = blockingIssues.length > 0;

	const fileLabels = {
		invoices_file: "ملف الفواتير والإشعارات الدائنة",
		transactions_file: "ملف الحركات",
		consolidated_file: "ملف الرسوم المجمعة",
		statement_detail_file: "ملف تفاصيل كشف نون",
	};

	const draftCounts = [
		["فواتير مبيعات", results.build_sales_invoice_drafts?.created_count || 0],
		["مرتجعات مبيعات", results.build_sales_return_drafts?.created_count || 0],
		["فواتير شراء رسوم", results.build_fee_purchase_invoice_drafts?.created_count || 0],
		["فواتير مبيعات رسوم مستحقة", results.build_fee_receivable_sales_invoice_drafts?.created_count || 0],
		["مرتجعات تعديلات تجارية", results.build_commercial_adjustment_returns?.created_count || 0],
		["فواتير شراء تعديلات لوجستية", results.build_logistics_adjustment_purchase_invoices?.created_count || 0],
		["سندات قبض", results.build_payment_entry_drafts?.created_count || 0],
	];

	lines.push("نتيجة تشغيل دفعة نون");
	lines.push("");

	if (hasBlockingIssues) {
		lines.push("تعذر إنشاء المسودات");
		lines.push("");

		if (hasUnresolvedItemMappings) {
			lines.push("المشكلة:");
			lines.push("- يوجد أصناف من نون غير مربوطة بأصناف ERPNext بعد محاولة الربط التلقائي.");
			lines.push("");
			lines.push("العدد:");
			lines.push(`- عدد الأصناف غير المربوطة: ${unresolvedItemMappingsCount}`);

			if (unresolvedPreviewRows.length) {
				lines.push("");
				lines.push("أول الأصناف التي ما زالت تحتاج ربطًا:");
				unresolvedPreviewRows.forEach((row) => {
					const sku = getReadablePartnerSku(row) || "غير معروف";
					const rowsCount = Number(row?.rows_count || 0);

					if (rowsCount > 0) {
						lines.push(`- ${sku} (عدد الصفوف: ${rowsCount})`);
					} else {
						lines.push(`- ${sku}`);
					}
				});
			}

			lines.push("");
			lines.push("ماذا يجب على المستخدم أن يفعل؟");
			lines.push("- استكمال الربط في شاشة Noon Item Mapping");
			lines.push("- ثم إعادة تشغيل المعالجة");
		}

		lines.push("المشاكل المانعة:");
		blockingIssues.forEach((issue) => {
			lines.push(`- ${issue.message}`);
		});
	} else {
		lines.push("الحالة:");
		lines.push("- الدفعة جاهزة وتم إنشاء المسودات بنجاح");
	}

	lines.push("");
	lines.push("ملخص الملفات:");

	Object.keys(fileLabels).forEach((key) => {
		const rowCount = files[key]?.rows || 0;
		lines.push(`- ${fileLabels[key]}: ${rowCount} صف`);
	});

	lines.push("");
	lines.push("التحقق:");

	if (hasBlockingIssues) {
		blockingIssues.forEach((issue) => {
			lines.push(`- ${issue.message}`);
		});
	} else {
		lines.push("- لا توجد مشاكل مانعة");
	}

	if (warnings.length) {
		const stockWarning = warnings.find((warning) => warning.type === "missing_stock_in_warehouse");
		if (stockWarning) {
			lines.push(`- يوجد ${stockWarning.count} تحذير متعلق بالمخزون، لكنه لا يمنع إنشاء المسودات المالية`);
		} else {
			lines.push(`- يوجد ${warnings.length} تحذير يحتاج إلى مراجعة`);
		}
	} else {
		lines.push("- لا توجد تحذيرات");
	}

	if (warnings.length) {
		lines.push("");
		lines.push("التحذيرات:");
		warnings.forEach((warning) => {
			lines.push(`- ${warning.message}`);
		});
	}

	if (!hasBlockingIssues) {
		lines.push("");
		lines.push("المستندات التي تم إنشاؤها:");
		draftCounts.forEach(([label, count]) => {
			lines.push(`- ${label}: ${count}`);
		});

		lines.push("");
		lines.push("ملاحظات:");
		lines.push("- يمكن للمستخدم الآن مراجعة المسودات يدويًا قبل الاعتماد");
		lines.push("- لم يتم ترحيل أي مستند تلقائيًا");
	}

	return lines.join("\n");
}

frappe.ui.form.on("Noon Import Batch", {
	refresh(frm) {
		if (!frm.doc.__islocal) {
			frm.add_custom_button("انشاء المستندات اللازمة", () => {
				frappe.call({
					method: "epc_app.noon_integration.api.noon_import.run_full_draft_pipeline",
					args: {
						batch_name: frm.doc.name,
						include_payments: 0,
					},
					freeze: true,
					freeze_message: "جاري انشاء المستندات اللازمة...",
					callback(r) {
						if (!r.message) return;

						console.log("Noon draft pipeline result", r.message);
						frm.set_value("last_run_result", formatNoonPipelineResult(r.message));
						frm.save();
						frappe.msgprint("تم انشاء المستندات اللازمة. يمكنك مراجعة النتائج أدناه.");
					},
				});
			});

			frm.add_custom_button("مراجعة فواتير المبيعات", () => {
				const route = `/app/sales-invoice?custom_noon_import_batch=${frm.doc.name}`;
				window.open(route, "_blank");
			});

			frm.add_custom_button("مراجعة فواتير الشراء", () => {
				const route = `/app/purchase-invoice?custom_noon_import_batch=${frm.doc.name}`;
				window.open(route, "_blank");
			});

			frm.add_custom_button("مراجعة سندات القبض", () => {
				const route = `/app/payment-entry?custom_noon_import_batch=${frm.doc.name}`;
				window.open(route, "_blank");
			});
		}
	},
});
