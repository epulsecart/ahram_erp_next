import hashlib
import csv
import io
import re
from typing import List, Dict, Any

import frappe
from frappe.utils import cint, getdate, flt
from frappe.utils.file_manager import get_file


SOURCE_LABELS = {
    "invoices_file": "Invoices & Credit Notes Report",
    "transactions_file": "Transaction View Report",
    "consolidated_file": "Consolidated Item Level Fees Report",
    "statement_detail_file": "Noon Finance Web Statement Detail Report Noon",
}

DATE_CANDIDATES = [
    "Document Date",
    "Transaction Date",
    "Order Date",
    "statement_date",
    "last_statement_date",
    "ordered_date",
    "shipped_date",
    "delivered_date",
    "returned_date",
]


def _read_attach_csv(file_url: str) -> List[Dict[str, Any]]:
    if not file_url:
        return []

    _file_name, content = get_file(file_url)

    if isinstance(content, bytes):
        text = content.decode("utf-8-sig")
    else:
        text = content

    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


def _collect_dates(rows: List[Dict[str, Any]]) -> List:
    out = []

    for row in rows:
        for key in DATE_CANDIDATES:
            val = row.get(key)
            if not val:
                continue
            try:
                out.append(getdate(val))
            except Exception:
                pass

    return out


def _to_float(val) -> float:
    if val in (None, "", "None"):
        return 0.0
    try:
        return flt(val)
    except Exception:
        return 0.0


def _normalize_fee_key(value) -> str | None:
    if not value:
        return None

    text = str(value).strip()

    if text.startswith("PS-") and ":" in text:
        text = text.split(":", 1)[1].strip()

    text = re.sub(r"\s+", " ", text).strip()
    return text[:140] or None


def _extract_statement_nr(*values) -> str | None:
    for value in values:
        if not value:
            continue
        match = re.search(r"(PS-[A-Za-z0-9\-]+)", str(value))
        if match:
            return match.group(1)
    return None


def _build_statement_map_from_consolidated(rows: List[Dict[str, Any]]) -> Dict[str, str]:
    out = {}

    for row in rows:
        statement_nr = row.get("statement_nr")
        invoice_nr = row.get("invoice_nr")
        creditnote_nr = row.get("creditnote_nr")

        if statement_nr and invoice_nr and invoice_nr not in out:
            out[invoice_nr] = statement_nr

        if statement_nr and creditnote_nr and creditnote_nr not in out:
            out[creditnote_nr] = statement_nr

    return out


def _build_statement_map_from_transactions(rows: List[Dict[str, Any]]) -> Dict[str, str]:
    out = {}

    for row in rows:
        statement_nr = _extract_statement_nr(row.get("Reference Nr"))
        order_nr = row.get("Order Nr")

        if statement_nr and order_nr and order_nr not in out:
            out[order_nr] = statement_nr

    return out


def _make_source_row_key(*values) -> str:
    normalized = []

    for value in values:
        if value is None:
            normalized.append("")
        else:
            normalized.append(str(value).strip())

    return hashlib.sha256("\x1f".join(normalized).encode("utf-8")).hexdigest()


@frappe.whitelist()
def analyze_batch(batch_name: str):
    doc = frappe.get_doc("Noon Import Batch", batch_name)

    files = {
        "invoices_file": doc.invoices_file,
        "transactions_file": doc.transactions_file,
        "consolidated_file": doc.consolidated_file,
        "statement_detail_file": doc.statement_detail_file,
    }

    summary = {}
    all_dates = []

    for fieldname, file_url in files.items():
        rows = _read_attach_csv(file_url)
        row_dates = _collect_dates(rows)
        all_dates.extend(row_dates)

        summary[fieldname] = {
            "label": SOURCE_LABELS[fieldname],
            "rows": len(rows),
            "attached": bool(file_url),
            "min_date": str(min(row_dates)) if row_dates else None,
            "max_date": str(max(row_dates)) if row_dates else None,
        }

    if all_dates:
        doc.from_date = min(all_dates)
        doc.to_date = max(all_dates)

    doc.status = "Analyzed"
    doc.save(ignore_permissions=True)

    return {
        "batch": doc.name,
        "status": doc.status,
        "from_date": str(doc.from_date) if doc.from_date else None,
        "to_date": str(doc.to_date) if doc.to_date else None,
        "files": summary,
    }


def _insert_row(payload: Dict[str, Any]) -> bool:
    exists = frappe.db.exists(
        "Noon Import Row",
        {
            "source_file": payload.get("source_file"),
            "source_row_key": payload.get("source_row_key"),
        },
    )
    if exists:
        return False

    doc = frappe.get_doc({
        "doctype": "Noon Import Row",
        **payload,
    })
    doc.insert(ignore_permissions=True)
    return True


def _stage_invoices_rows(
    batch_name: str,
    rows: List[Dict[str, Any]],
    statement_map: Dict[str, str],
    order_statement_map: Dict[str, str],
) -> int:
    count = 0

    for idx, row in enumerate(rows, start=1):
        source_doc_nr = row.get("Source Doc Nr")
        source_doc_line_nr = row.get("Source Doc Line Nr")
        source_row_key = _make_source_row_key(
            row.get("Document Type"),
            row.get("Transaction Type"),
            row.get("Invoice Nr"),
            row.get("Credit Note Nr"),
            source_doc_nr,
            source_doc_line_nr,
            row.get("Partner SKU"),
            _normalize_fee_key(row.get("Description")),
            row.get("Price Excluding VAT (Document Currency)"),
            row.get("VAT Amount (Document Currency)"),
            row.get("Price Including VAT (Document Currency)"),
        )

        inserted = _insert_row({
            "batch": batch_name,
            "source_file": "Invoices & Credit Notes Report",
            "source_row_key": source_row_key,
            "source_row_no": idx,
            "statement_nr": (
                statement_map.get(row.get("Invoice Nr"))
                or statement_map.get(row.get("Credit Note Nr"))
                or order_statement_map.get(source_doc_nr)
                or _extract_statement_nr(
                    source_doc_line_nr,
                    source_doc_nr,
                    row.get("Description"),
                    row.get("Misc"),
                )
            ),
            "invoice_nr": row.get("Invoice Nr"),
            "creditnote_nr": row.get("Credit Note Nr"),
            "reference_nr": source_doc_nr,
            "order_nr": source_doc_nr,
            "item_nr": source_doc_line_nr,
            "transaction_type": row.get("Transaction Type"),
            "document_type": row.get("Document Type"),
            "partner_sku": row.get("Partner SKU"),
            "fee_key": _normalize_fee_key(row.get("Description")) if row.get("Transaction Type") == "Statement Fee" else None,
            "amount": _to_float(row.get("Price Excluding VAT (Document Currency)")),
            "vat_amount": _to_float(row.get("VAT Amount (Document Currency)")),
            "gross_amount": _to_float(row.get("Price Including VAT (Document Currency)")),
            "status": "Pending",
        })
        if inserted:
            count += 1

    return count


def _stage_transactions_rows(batch_name: str, rows: List[Dict[str, Any]]) -> int:
    count = 0

    for idx, row in enumerate(rows, start=1):
        reference_nr = row.get("Reference Nr")
        source_row_key = _make_source_row_key(
            reference_nr,
            row.get("Order Nr"),
            row.get("Transaction Type"),
            row.get("Partner SKUs"),
            _normalize_fee_key(row.get("Title")),
            row.get("Total"),
        )

        inserted = _insert_row({
            "batch": batch_name,
            "source_file": "Transaction View Report",
            "source_row_key": source_row_key,
            "source_row_no": idx,
            "statement_nr": _extract_statement_nr(reference_nr),
            "reference_nr": reference_nr,
            "order_nr": row.get("Order Nr"),
            "transaction_type": row.get("Transaction Type"),
            "document_type": "Transaction View",
            "partner_sku": row.get("Partner SKUs"),
            "fee_key": _normalize_fee_key(row.get("Title")) if row.get("Transaction Type") == "statement_fee" else None,
            "amount": _to_float(row.get("Total")),
            "vat_amount": 0.0,
            "gross_amount": _to_float(row.get("Total")),
            "status": "Pending",
        })
        if inserted:
            count += 1

    return count


def _stage_consolidated_rows(batch_name: str, rows: List[Dict[str, Any]]) -> int:
    count = 0

    for idx, row in enumerate(rows, start=1):
        source_row_key = _make_source_row_key(
            row.get("statement_nr"),
            row.get("invoice_nr"),
            row.get("creditnote_nr"),
            row.get("order_nr"),
            row.get("item_nr"),
            row.get("item_status"),
            row.get("partner_sku"),
            row.get("total_payment"),
        )

        inserted = _insert_row({
            "batch": batch_name,
            "source_file": "Consolidated Item Level Fees Report",
            "source_row_key": source_row_key,
            "source_row_no": idx,
            "statement_nr": row.get("statement_nr"),
            "invoice_nr": row.get("invoice_nr"),
            "creditnote_nr": row.get("creditnote_nr"),
            "order_nr": row.get("order_nr"),
            "item_nr": row.get("item_nr"),
            "transaction_type": row.get("item_status"),
            "document_type": "Consolidated",
            "partner_sku": row.get("partner_sku"),
            "amount": _to_float(row.get("total_payment")),
            "vat_amount": 0.0,
            "gross_amount": _to_float(row.get("total_payment")),
            "status": "Pending",
        })
        if inserted:
            count += 1

    return count


def _stage_statement_detail_rows(batch_name: str, rows: List[Dict[str, Any]]) -> int:
    count = 0

    for idx, row in enumerate(rows, start=1):
        source_row_key = _make_source_row_key(
            row.get("statement_nr"),
            row.get("reference_nr"),
            row.get("order_nr"),
            row.get("item_nr"),
            row.get("fee_name"),
            row.get("partner_sku"),
            row.get("total_payment"),
        )

        inserted = _insert_row({
            "batch": batch_name,
            "source_file": "Noon Finance Web Statement Detail Report Noon",
            "source_row_key": source_row_key,
            "source_row_no": idx,
            "statement_nr": row.get("statement_nr"),
            "reference_nr": row.get("reference_nr"),
            "order_nr": row.get("order_nr"),
            "item_nr": row.get("item_nr"),
            "transaction_type": row.get("fee_name"),
            "document_type": "Statement Detail",
            "partner_sku": row.get("partner_sku"),
            "fee_key": _normalize_fee_key(row.get("fee_name")),
            "amount": _to_float(row.get("total_payment")),
            "vat_amount": 0.0,
            "gross_amount": _to_float(row.get("total_payment")),
            "status": "Pending",
        })
        if inserted:
            count += 1

    return count


@frappe.whitelist()
def stage_batch_rows(batch_name: str):
    batch = frappe.get_doc("Noon Import Batch", batch_name)

    frappe.db.delete("Noon Import Row", {"batch": batch_name})

    counts = {}

    invoices_rows = _read_attach_csv(batch.invoices_file)
    transactions_rows = _read_attach_csv(batch.transactions_file)
    consolidated_rows = _read_attach_csv(batch.consolidated_file)
    statement_detail_rows = _read_attach_csv(batch.statement_detail_file)

    statement_map = _build_statement_map_from_consolidated(consolidated_rows)
    order_statement_map = _build_statement_map_from_transactions(transactions_rows)

    counts["invoices_file"] = _stage_invoices_rows(batch_name, invoices_rows, statement_map, order_statement_map)
    counts["transactions_file"] = _stage_transactions_rows(batch_name, transactions_rows)
    counts["consolidated_file"] = _stage_consolidated_rows(batch_name, consolidated_rows)
    counts["statement_detail_file"] = _stage_statement_detail_rows(batch_name, statement_detail_rows)

    total_rows = sum(counts.values())

    frappe.db.commit()

    return {
        "batch": batch_name,
        "inserted_rows": total_rows,
        "breakdown": counts,
    }


@frappe.whitelist()
def summarize_staged_batch(batch_name: str):
    by_source = frappe.db.sql("""
        select source_file, count(*) as rows_count
        from `tabNoon Import Row`
        where batch = %s
        group by source_file
        order by source_file
    """, (batch_name,), as_dict=True)

    by_txn = frappe.db.sql("""
        select ifnull(transaction_type, '') as transaction_type, count(*) as rows_count
        from `tabNoon Import Row`
        where batch = %s
        group by transaction_type
        order by rows_count desc, transaction_type asc
    """, (batch_name,), as_dict=True)

    by_doc = frappe.db.sql("""
        select ifnull(document_type, '') as document_type, count(*) as rows_count
        from `tabNoon Import Row`
        where batch = %s
        group by document_type
        order by rows_count desc, document_type asc
    """, (batch_name,), as_dict=True)

    fee_keys = frappe.db.sql("""
        select fee_key, count(*) as rows_count
        from `tabNoon Import Row`
        where batch = %s and ifnull(fee_key, '') != ''
        group by fee_key
        order by rows_count desc, fee_key asc
    """, (batch_name,), as_dict=True)

    statements = frappe.db.sql("""
        select statement_nr, count(*) as rows_count
        from `tabNoon Import Row`
        where batch = %s and ifnull(statement_nr, '') != ''
        group by statement_nr
        order by statement_nr asc
    """, (batch_name,), as_dict=True)

    return {
        "batch": batch_name,
        "by_source": by_source,
        "by_transaction_type": by_txn,
        "by_document_type": by_doc,
        "fee_keys": fee_keys,
        "statements": statements,
    }


@frappe.whitelist()
def get_required_mappings(batch_name: str):
    item_rows = frappe.db.sql("""
        select
            partner_sku,
            count(*) as rows_count
        from `tabNoon Import Row`
        where batch = %s
          and source_file = 'Invoices & Credit Notes Report'
          and transaction_type = 'Customer'
          and ifnull(partner_sku, '') != ''
        group by partner_sku
        order by rows_count desc, partner_sku asc
    """, (batch_name,), as_dict=True)

    fee_rows = frappe.db.sql("""
        select
            fee_key,
            count(*) as rows_count
        from `tabNoon Import Row`
        where batch = %s
          and source_file = 'Invoices & Credit Notes Report'
          and transaction_type = 'Statement Fee'
          and ifnull(fee_key, '') != ''
        group by fee_key
        order by rows_count desc, fee_key asc
    """, (batch_name,), as_dict=True)

    company = frappe.db.get_value(
        "Noon Marketplace Profile",
        frappe.db.get_value("Noon Import Batch", batch_name, "profile"),
        "company",
    )

    item_map = {
        d.partner_sku: d.item_code
        for d in frappe.get_all(
            "Noon Item Mapping",
            filters={"company": company, "is_active": 1},
            fields=["partner_sku", "item_code"],
            limit_page_length=0,
        )
    }

    fee_map = {
        d.fee_key: {
            "item_code": d.item_code,
            "expense_account": d.expense_account,
            "income_account": d.income_account,
        }
        for d in frappe.get_all(
            "Noon Fee Mapping",
            filters={"company": company, "is_active": 1},
            fields=["fee_key", "item_code", "expense_account", "income_account"],
            limit_page_length=0,
        )
    }

    for row in item_rows:
        row["mapped_item_code"] = item_map.get(row["partner_sku"])

    for row in fee_rows:
        row["mapping"] = fee_map.get(row["fee_key"])

    return {
        "batch": batch_name,
        "company": company,
        "item_mappings_needed": item_rows,
        "fee_mappings_needed": fee_rows,
    }


def _column_exists(doctype: str, column: str) -> bool:
    rows = frappe.db.sql(
        f"show columns from `tab{doctype}` like %s",
        (column,),
    )
    return bool(rows)


def _sql_find_item_by_column(column: str, value: str):
    if not _column_exists("Item", column):
        return None

    rows = frappe.db.sql(
        f"""
        select `name`, `item_name`
        from `tabItem`
        where `{column}` = %s
        limit 1
        """,
        (value,),
        as_dict=True,
    )
    return rows[0] if rows else None


def _find_item_for_partner_sku(partner_sku: str):
    if not partner_sku:
        return None

    for column in (
        "item_code",
        "custom_item_code_old",
    ):
        try:
            item = _sql_find_item_by_column(column, partner_sku)
        except Exception:
            item = None

        if item:
            return item

    return None


@frappe.whitelist()
def auto_create_exact_item_mappings(batch_name: str):
    profile = frappe.db.get_value("Noon Import Batch", batch_name, "profile")
    company = frappe.db.get_value("Noon Marketplace Profile", profile, "company")

    partner_skus = frappe.db.sql("""
        select distinct partner_sku
        from `tabNoon Import Row`
        where batch = %s
          and source_file = 'Invoices & Credit Notes Report'
          and transaction_type = 'Customer'
          and ifnull(partner_sku, '') != ''
    """, (batch_name,), as_dict=True)

    created = []
    skipped = []

    for row in partner_skus:
        partner_sku = row["partner_sku"]

        if frappe.db.exists("Noon Item Mapping", {
            "company": company,
            "partner_sku": partner_sku,
        }):
            skipped.append({"partner_sku": partner_sku, "reason": "mapping_exists"})
            continue

        item = _find_item_for_partner_sku(partner_sku)
        if not item:
            skipped.append({"partner_sku": partner_sku, "reason": "item_not_found"})
            continue

        doc = frappe.get_doc({
            "doctype": "Noon Item Mapping",
            "company": company,
            "partner_sku": partner_sku,
            "item_code": item["name"],
            "item_name": item["item_name"],
            "is_active": 1,
        })
        doc.insert(ignore_permissions=True)

        created.append({
            "partner_sku": partner_sku,
            "item_code": item["name"],
        })

    frappe.db.commit()

    return {
        "batch": batch_name,
        "company": company,
        "created_count": len(created),
        "skipped_count": len(skipped),
        "created": created,
        "skipped": skipped,
    }


@frappe.whitelist()
def validate_batch_ready(batch_name: str):
    profile = frappe.db.get_value("Noon Import Batch", batch_name, "profile")
    company = frappe.db.get_value("Noon Marketplace Profile", profile, "company")

    missing_item = frappe.db.sql("""
        select distinct r.partner_sku
        from `tabNoon Import Row` r
        left join `tabNoon Item Mapping` m
          on m.company = %s
         and m.partner_sku = r.partner_sku
         and ifnull(m.is_active, 0) = 1
        where r.batch = %s
          and r.source_file = 'Invoices & Credit Notes Report'
          and r.transaction_type = 'Customer'
          and ifnull(r.partner_sku, '') != ''
          and m.name is null
        order by r.partner_sku asc
    """, (company, batch_name), as_dict=True)

    missing_fee = frappe.db.sql("""
        select distinct r.fee_key
        from `tabNoon Import Row` r
        left join `tabNoon Fee Mapping` m
          on m.company = %s
         and m.fee_key = r.fee_key
         and ifnull(m.is_active, 0) = 1
        where r.batch = %s
          and r.source_file = 'Invoices & Credit Notes Report'
          and r.transaction_type = 'Statement Fee'
          and ifnull(r.fee_key, '') != ''
          and (
                m.name is null
                or (
                    ifnull(m.item_code, '') = ''
                    and ifnull(m.expense_account, '') = ''
                    and ifnull(m.income_account, '') = ''
                )
              )
        order by r.fee_key asc
    """, (company, batch_name), as_dict=True)

    warehouse = frappe.db.get_value("Noon Marketplace Profile", profile, "warehouse")

    missing_stock = []
    if warehouse:
        item_codes = [
            d.item_code
            for d in frappe.get_all(
                "Noon Item Mapping",
                filters={"company": company, "is_active": 1},
                fields=["item_code"],
                limit_page_length=0,
            )
        ]

        item_codes = list(set([x for x in item_codes if x]))

        for item_code in item_codes:
            qty = frappe.db.get_value(
                "Bin",
                {"item_code": item_code, "warehouse": warehouse},
                "actual_qty",
            ) or 0

            if qty <= 0:
                missing_stock.append({
                    "item_code": item_code,
                    "warehouse": warehouse,
                    "actual_qty": qty,
                })

    blocking_issues = []
    warnings = []

    if missing_item:
        blocking_issues.append({
            "type": "missing_item_mappings",
            "message": "يوجد أصناف من نون غير مربوطة بأصناف ERPNext، ويجب إكمال الربط قبل إنشاء المسودات.",
            "count": len(missing_item),
            "rows": missing_item,
        })

    if missing_fee:
        blocking_issues.append({
            "type": "missing_fee_mappings",
            "message": "يوجد رسوم من نون غير مربوطة بعناصر/حسابات النظام، ويجب إكمال الربط قبل إنشاء المسودات.",
            "count": len(missing_fee),
            "rows": missing_fee,
        })

    if missing_stock:
        warnings.append({
            "type": "missing_stock_in_warehouse",
            "message": "بعض الأصناف المربوطة لا تملك رصيدًا متاحًا في مستودع نون، لكن هذا لا يمنع إنشاء المسودات المالية.",
            "count": len(missing_stock),
            "rows": missing_stock,
        })

    summary = {
        "missing_item_mappings": len(missing_item),
        "missing_fee_mappings": len(missing_fee),
        "missing_stock_in_warehouse": len(missing_stock),
    }

    return {
        "batch": batch_name,
        "company": company,
        "warehouse": warehouse,
        "ready": not missing_item and not missing_fee,
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "summary": summary,
        "missing_item_mappings": missing_item,
        "missing_fee_mappings": missing_fee,
        "missing_stock_in_warehouse": missing_stock,
    }


@frappe.whitelist()
def build_sales_invoice_drafts(batch_name: str):
    profile_name = frappe.db.get_value("Noon Import Batch", batch_name, "profile")
    profile = frappe.get_doc("Noon Marketplace Profile", profile_name)

    invoice_rows = frappe.db.sql("""
        select
            r.invoice_nr,
            r.reference_nr,
            r.partner_sku,
            r.amount,
            r.vat_amount,
            r.gross_amount
        from `tabNoon Import Row` r
        where r.batch = %s
          and r.source_file = 'Invoices & Credit Notes Report'
          and r.transaction_type = 'Customer'
          and r.document_type = 'Invoice'
          and ifnull(r.invoice_nr, '') != ''
        order by r.invoice_nr, r.partner_sku, r.amount
    """, (batch_name,), as_dict=True)

    item_map = {
        d.partner_sku: d.item_code
        for d in frappe.get_all(
            "Noon Item Mapping",
            filters={"company": profile.company, "is_active": 1},
            fields=["partner_sku", "item_code"],
            limit_page_length=0,
        )
    }

    grouped = {}
    for row in invoice_rows:
        inv = row.invoice_nr
        grouped.setdefault(inv, [])
        grouped[inv].append(row)

    created = []
    skipped = []

    for invoice_nr, rows in grouped.items():
        existing = frappe.db.exists("Sales Invoice", {"custom_noon_invoice_nr": invoice_nr})
        if existing:
            skipped.append({"invoice_nr": invoice_nr, "reason": "already_exists", "sales_invoice": existing})
            continue

        item_groups = {}
        for row in rows:
            item_code = item_map.get(row.partner_sku)
            key = (item_code, flt(row.amount))
            item_groups.setdefault(key, {"qty": 0, "rate": flt(row.amount), "item_code": item_code})
            item_groups[key]["qty"] += 1

        si = frappe.get_doc({
            "doctype": "Sales Invoice",
            "customer": profile.customer,
            "company": profile.company,
            "posting_date": frappe.utils.today(),
            "due_date": frappe.utils.today(),
            "currency": profile.currency or frappe.defaults.get_global_default("currency"),
            "debit_to": profile.settlement_clearing_account,
            "custom_noon_import_batch": batch_name,
            "custom_noon_invoice_nr": invoice_nr,
            "custom_noon_reference_nr": rows[0].reference_nr,
            "items": [],
        })
        si.update_stock = 1

        for _, item in item_groups.items():
            si.append("items", {
                "item_code": item["item_code"],
                "qty": item["qty"],
                "rate": item["rate"],
                "warehouse": profile.warehouse,
                "income_account": None,
                "cost_center": profile.cost_center,
            })

        si.insert(ignore_permissions=True)
        created.append({"invoice_nr": invoice_nr, "sales_invoice": si.name})

    frappe.db.commit()

    return {
        "batch": batch_name,
        "created_count": len(created),
        "skipped_count": len(skipped),
        "created": created,
        "skipped": skipped,
    }


@frappe.whitelist()
def build_fee_receivable_sales_invoice_drafts(batch_name: str):
    profile_name = frappe.db.get_value("Noon Import Batch", batch_name, "profile")
    profile = frappe.get_doc("Noon Marketplace Profile", profile_name)

    fee_rows = frappe.db.sql("""
        select
            r.invoice_nr,
            r.reference_nr,
            r.fee_key,
            r.amount,
            r.vat_amount,
            r.gross_amount,
            r.statement_nr
        from `tabNoon Import Row` r
        left join `tabNoon Fee Mapping` m
          on m.company = %s
         and m.fee_key = r.fee_key
         and ifnull(m.is_active, 0) = 1
        where r.batch = %s
          and r.source_file = 'Invoices & Credit Notes Report'
          and r.transaction_type = 'Statement Fee'
          and r.document_type = 'Invoice'
          and ifnull(r.invoice_nr, '') != ''
          and m.direction = 'Receivable from Noon'
        order by r.invoice_nr, r.fee_key, r.amount
    """, (profile.company, batch_name), as_dict=True)

    fee_map = {
        d.fee_key: {
            "item_code": d.item_code,
            "income_account": d.income_account,
        }
        for d in frappe.get_all(
            "Noon Fee Mapping",
            filters={"company": profile.company, "is_active": 1},
            fields=["fee_key", "item_code", "income_account"],
            limit_page_length=0,
        )
    }

    grouped = {}
    for row in fee_rows:
        grouped.setdefault(row.invoice_nr, []).append(row)

    created = []
    skipped = []

    for invoice_nr, rows in grouped.items():
        existing = frappe.db.exists("Sales Invoice", {"custom_noon_fee_invoice_nr": invoice_nr})
        if existing:
            skipped.append({"invoice_nr": invoice_nr, "reason": "already_exists", "sales_invoice": existing})
            continue

        si = frappe.get_doc({
            "doctype": "Sales Invoice",
            "customer": profile.customer,
            "company": profile.company,
            "posting_date": frappe.utils.today(),
            "due_date": frappe.utils.today(),
            "currency": profile.currency or frappe.defaults.get_global_default("currency"),
            "debit_to": profile.settlement_clearing_account,
            "custom_noon_import_batch": batch_name,
            "custom_noon_fee_invoice_nr": invoice_nr,
            "custom_noon_reference_nr": rows[0].reference_nr,
            "remarks": f"Noon receivable fee invoice: {invoice_nr} | Ref: {rows[0].reference_nr or ''}",
            "items": [],
        })

        for row in rows:
            mapping = fee_map.get(row.fee_key) or {}
            si.append("items", {
                "item_code": mapping.get("item_code"),
                "qty": 1,
                "rate": flt(row.amount),
                "income_account": mapping.get("income_account"),
                "cost_center": profile.cost_center,
                "description": f"{row.fee_key} | Statement: {row.statement_nr or ''}",
            })

        si.insert(ignore_permissions=True)
        created.append({"invoice_nr": invoice_nr, "sales_invoice": si.name})

    frappe.db.commit()

    return {
        "batch": batch_name,
        "created_count": len(created),
        "skipped_count": len(skipped),
        "created": created,
        "skipped": skipped,
    }


@frappe.whitelist()
def summarize_batch_financials(batch_name: str):

    sales = frappe.db.sql("""
        select sum(base_grand_total)
        from `tabSales Invoice`
        where custom_noon_import_batch = %s
        and is_return = 0
        and docstatus = 0
    """, batch_name)[0][0] or 0

    returns = frappe.db.sql("""
        select sum(base_grand_total)
        from `tabSales Invoice`
        where custom_noon_import_batch = %s
        and is_return = 1
        and docstatus = 0
    """, batch_name)[0][0] or 0

    fees = frappe.db.sql("""
        select sum(base_grand_total)
        from `tabPurchase Invoice`
        where custom_noon_import_batch = %s
        and docstatus = 0
    """, batch_name)[0][0] or 0

    receivable_adjustments = frappe.db.sql("""
        select sum(base_grand_total)
        from `tabSales Invoice`
        where custom_noon_import_batch = %s
        and custom_noon_fee_invoice_nr is not null
        and is_return = 0
        and docstatus = 0
    """, batch_name)[0][0] or 0

    expected_settlement = sales - abs(returns) - fees + receivable_adjustments

    return {
        "batch": batch_name,
        "sales": sales,
        "returns": returns,
        "fees": fees,
        "receivable_adjustments": receivable_adjustments,
        "expected_settlement": expected_settlement,
    }


@frappe.whitelist()
def summarize_transaction_view_financials(batch_name: str):
    rows = frappe.db.sql("""
        select
            transaction_type,
            sum(amount) as total
        from `tabNoon Import Row`
        where batch = %s
          and source_file = 'Transaction View Report'
        group by transaction_type
    """, (batch_name,), as_dict=True)

    out = {
        "order": 0,
        "order_update": 0,
        "payment": 0,
        "statement_fee": 0,
        "balance_transfer": 0,
    }

    for row in rows:
        key = (row.transaction_type or "").strip()
        if key in out:
            out[key] = row.total or 0

    out["expected_from_transactions"] = (
        (out["order"] or 0)
        + (out["order_update"] or 0)
        + (out["statement_fee"] or 0)
        + (out["balance_transfer"] or 0)
    )

    return {
        "batch": batch_name,
        **out,
    }


@frappe.whitelist()
def reconcile_batch_by_statement(batch_name: str):
    sales_rows = frappe.db.sql("""
        select statement_nr, sum(gross_amount) as total
        from `tabNoon Import Row`
        where batch = %s
          and source_file = 'Invoices & Credit Notes Report'
          and transaction_type = 'Customer'
          and document_type = 'Invoice'
          and ifnull(statement_nr, '') != ''
        group by statement_nr
    """, (batch_name,), as_dict=True)

    return_rows = frappe.db.sql("""
        select statement_nr, sum(gross_amount) as total
        from `tabNoon Import Row`
        where batch = %s
          and source_file = 'Invoices & Credit Notes Report'
          and transaction_type = 'Customer'
          and document_type = 'Creditnote'
          and ifnull(statement_nr, '') != ''
        group by statement_nr
    """, (batch_name,), as_dict=True)

    fee_payable_rows = frappe.db.sql("""
        select r.statement_nr, sum(r.gross_amount) as total
        from `tabNoon Import Row` r
        inner join `tabNoon Fee Mapping` m
          on m.company = %s
         and m.fee_key = r.fee_key
         and ifnull(m.is_active, 0) = 1
         and m.direction = 'Payable to Noon'
        where r.batch = %s
          and r.source_file = 'Invoices & Credit Notes Report'
          and r.transaction_type = 'Statement Fee'
          and r.document_type = 'Invoice'
          and ifnull(r.statement_nr, '') != ''
        group by r.statement_nr
    """, (
        frappe.db.get_value(
            "Noon Marketplace Profile",
            frappe.db.get_value("Noon Import Batch", batch_name, "profile"),
            "company",
        ),
        batch_name,
    ), as_dict=True)

    fee_receivable_rows = frappe.db.sql("""
        select r.statement_nr, sum(r.gross_amount) as total
        from `tabNoon Import Row` r
        inner join `tabNoon Fee Mapping` m
          on m.company = %s
         and m.fee_key = r.fee_key
         and ifnull(m.is_active, 0) = 1
         and m.direction = 'Receivable from Noon'
        where r.batch = %s
          and r.source_file = 'Invoices & Credit Notes Report'
          and r.transaction_type = 'Statement Fee'
          and r.document_type = 'Invoice'
          and ifnull(r.statement_nr, '') != ''
        group by r.statement_nr
    """, (
        frappe.db.get_value(
            "Noon Marketplace Profile",
            frappe.db.get_value("Noon Import Batch", batch_name, "profile"),
            "company",
        ),
        batch_name,
    ), as_dict=True)

    tx_rows = frappe.db.sql("""
        select
            statement_nr,
            sum(case when transaction_type = 'order' then amount else 0 end) as order_total,
            sum(case when transaction_type = 'order_update' then amount else 0 end) as order_update_total,
            sum(case when transaction_type = 'statement_fee' then amount else 0 end) as statement_fee_total,
            sum(case when transaction_type = 'balance_transfer' then amount else 0 end) as balance_transfer_total
        from `tabNoon Import Row`
        where batch = %s
          and source_file = 'Transaction View Report'
          and ifnull(statement_nr, '') != ''
        group by statement_nr
    """, (batch_name,), as_dict=True)

    sales_map = {d.statement_nr: d.total or 0 for d in sales_rows}
    return_map = {d.statement_nr: d.total or 0 for d in return_rows}
    fee_payable_map = {d.statement_nr: d.total or 0 for d in fee_payable_rows}
    fee_receivable_map = {d.statement_nr: d.total or 0 for d in fee_receivable_rows}
    tx_map = {d.statement_nr: d for d in tx_rows}

    all_keys = sorted(set(sales_map) | set(return_map) | set(fee_payable_map) | set(fee_receivable_map) | set(tx_map))

    out = []
    for key in all_keys:
        tx = tx_map.get(key, {})
        doc_expected = (
            (sales_map.get(key) or 0)
            - abs(return_map.get(key) or 0)
            - (fee_payable_map.get(key) or 0)
            + (fee_receivable_map.get(key) or 0)
        )
        tx_expected = (
            (tx.get("order_total") or 0)
            + (tx.get("order_update_total") or 0)
            + (tx.get("statement_fee_total") or 0)
            + (tx.get("balance_transfer_total") or 0)
        )
        out.append({
            "statement_nr": key,
            "sales": sales_map.get(key) or 0,
            "returns": return_map.get(key) or 0,
            "fee_payable": fee_payable_map.get(key) or 0,
            "fee_receivable": fee_receivable_map.get(key) or 0,
            "doc_expected": doc_expected,
            "tx_expected": tx_expected,
            "difference": doc_expected - tx_expected,
        })

    return {
        "batch": batch_name,
        "rows": out,
    }


@frappe.whitelist()
def list_unmapped_customer_docs(batch_name: str):
    invoice_rows = frappe.db.sql("""
        select
            document_type,
            invoice_nr,
            creditnote_nr,
            reference_nr,
            gross_amount
        from `tabNoon Import Row`
        where batch = %s
          and source_file = 'Invoices & Credit Notes Report'
          and transaction_type = 'Customer'
          and ifnull(statement_nr, '') = ''
        order by document_type, invoice_nr, creditnote_nr
    """, (batch_name,), as_dict=True)

    return {
        "batch": batch_name,
        "count": len(invoice_rows),
        "rows": invoice_rows,
    }


@frappe.whitelist()
def list_order_updates(batch_name: str):
    rows = frappe.db.sql("""
        select
            statement_nr,
            reference_nr,
            order_nr,
            amount,
            partner_sku,
            fee_key
        from `tabNoon Import Row`
        where batch = %s
          and source_file = 'Transaction View Report'
          and transaction_type = 'order_update'
        order by statement_nr, order_nr
    """, (batch_name,), as_dict=True)

    return {
        "batch": batch_name,
        "count": len(rows),
        "rows": rows,
    }


@frappe.whitelist()
def inspect_order_update_components(batch_name: str):
    batch = frappe.get_doc("Noon Import Batch", batch_name)
    rows = _read_attach_csv(batch.transactions_file)

    out = []
    for row in rows:
        if (row.get("Transaction Type") or "").strip() != "order_update":
            continue

        out.append({
            "reference_nr": row.get("Reference Nr"),
            "order_nr": row.get("Order Nr"),
            "transaction_date": row.get("Transaction Date"),
            "partner_sku": row.get("Partner SKUs"),
            "net_proceeds": _to_float(row.get("Net Proceeds")),
            "referral_fee": _to_float(row.get("Referral Fee")),
            "fulfilment_logistics_fees": _to_float(row.get("Fullfilment & Logistics Fees")),
            "shipping_credits": _to_float(row.get("Shipping Credits")),
            "other_order_fees": _to_float(row.get("Other Order Fees")),
            "order_subsidies": _to_float(row.get("Order Subsidies")),
            "non_order_fees": _to_float(row.get("Non-Order Fees")),
            "non_order_subsidies": _to_float(row.get("Non-Order Subsidies")),
            "others": _to_float(row.get("Others")),
            "total": _to_float(row.get("Total")),
        })

    return {
        "batch": batch_name,
        "count": len(out),
        "rows": out,
    }


@frappe.whitelist()
def classify_order_updates(batch_name: str):
    batch = frappe.get_doc("Noon Import Batch", batch_name)
    rows = _read_attach_csv(batch.transactions_file)

    out = []

    for row in rows:
        if (row.get("Transaction Type") or "").strip() != "order_update":
            continue

        net_proceeds = _to_float(row.get("Net Proceeds"))
        referral_fee = _to_float(row.get("Referral Fee"))
        fulfilment = _to_float(row.get("Fullfilment & Logistics Fees"))
        order_subsidies = _to_float(row.get("Order Subsidies"))
        total = _to_float(row.get("Total"))

        if net_proceeds != 0:
            proposed_type = "commercial_adjustment"
        else:
            proposed_type = "logistics_adjustment"

        out.append({
            "reference_nr": row.get("Reference Nr"),
            "order_nr": row.get("Order Nr"),
            "partner_sku": row.get("Partner SKUs"),
            "net_proceeds": net_proceeds,
            "referral_fee": referral_fee,
            "fulfilment_logistics_fees": fulfilment,
            "order_subsidies": order_subsidies,
            "total": total,
            "proposed_type": proposed_type,
        })

    return {
        "batch": batch_name,
        "count": len(out),
        "rows": out,
    }


@frappe.whitelist()
def build_commercial_adjustment_returns(batch_name: str):
    profile_name = frappe.db.get_value("Noon Import Batch", batch_name, "profile")
    profile = frappe.get_doc("Noon Marketplace Profile", profile_name)

    batch = frappe.get_doc("Noon Import Batch", batch_name)
    tx_rows = _read_attach_csv(batch.transactions_file)

    item_map = {
        d.partner_sku: d.item_code
        for d in frappe.get_all(
            "Noon Item Mapping",
            filters={"company": profile.company, "is_active": 1},
            fields=["partner_sku", "item_code"],
            limit_page_length=0,
        )
    }

    created = []
    skipped = []

    for row in tx_rows:
        if (row.get("Transaction Type") or "").strip() != "order_update":
            continue

        net_proceeds = _to_float(row.get("Net Proceeds"))
        if net_proceeds == 0:
            continue

        order_nr = row.get("Order Nr")
        partner_sku = row.get("Partner SKUs")
        reference_nr = row.get("Reference Nr")

        existing = frappe.db.exists("Sales Invoice", {
            "custom_noon_import_batch": batch_name,
            "custom_noon_reference_nr": f"{reference_nr}::{order_nr}::commercial_adjustment",
            "is_return": 1,
        })
        if existing:
            skipped.append({
                "order_nr": order_nr,
                "reason": "already_exists",
                "sales_return": existing,
            })
            continue

        item_code = item_map.get(partner_sku)
        if not item_code:
            skipped.append({
                "order_nr": order_nr,
                "reason": "missing_item_mapping",
                "partner_sku": partner_sku,
            })
            continue

        si = frappe.get_doc({
            "doctype": "Sales Invoice",
            "is_return": 1,
            "update_stock": 0,
            "customer": profile.customer,
            "company": profile.company,
            "posting_date": frappe.utils.today(),
            "due_date": frappe.utils.today(),
            "currency": profile.currency or frappe.defaults.get_global_default("currency"),
            "debit_to": profile.settlement_clearing_account,
            "custom_noon_import_batch": batch_name,
            "custom_noon_reference_nr": f"{reference_nr}::{order_nr}::commercial_adjustment",
            "remarks": f"Noon commercial adjustment | Order: {order_nr} | Ref: {reference_nr}",
            "items": [{
                "item_code": item_code,
                "qty": -1,
                "rate": abs(net_proceeds),
                "cost_center": profile.cost_center,
                "description": f"Commercial adjustment | Order: {order_nr} | Ref: {reference_nr}",
            }],
        })

        si.insert(ignore_permissions=True)
        created.append({
            "order_nr": order_nr,
            "sales_return": si.name,
            "amount": abs(net_proceeds),
        })

    frappe.db.commit()

    return {
        "batch": batch_name,
        "created_count": len(created),
        "skipped_count": len(skipped),
        "created": created,
        "skipped": skipped,
    }


@frappe.whitelist()
def build_logistics_adjustment_purchase_invoices(batch_name: str):
    profile_name = frappe.db.get_value("Noon Import Batch", batch_name, "profile")
    profile = frappe.get_doc("Noon Marketplace Profile", profile_name)

    batch = frappe.get_doc("Noon Import Batch", batch_name)
    tx_rows = _read_attach_csv(batch.transactions_file)

    created = []
    skipped = []

    fee_item_code = "NOON-FEE-PAYABLE"

    for row in tx_rows:
        if (row.get("Transaction Type") or "").strip() != "order_update":
            continue

        net_proceeds = _to_float(row.get("Net Proceeds"))
        if net_proceeds != 0:
            continue

        order_nr = row.get("Order Nr")
        reference_nr = row.get("Reference Nr")

        fulfilment = abs(_to_float(row.get("Fullfilment & Logistics Fees")))
        subsidy = _to_float(row.get("Order Subsidies"))

        existing = frappe.db.exists("Purchase Invoice", {
            "custom_noon_import_batch": batch_name,
            "custom_noon_reference_nr": f"{reference_nr}::{order_nr}::logistics_adjustment",
        })
        if existing:
            skipped.append({
                "order_nr": order_nr,
                "reason": "already_exists",
                "purchase_invoice": existing,
            })
            continue

        pi = frappe.get_doc({
            "doctype": "Purchase Invoice",
            "supplier": profile.supplier,
            "company": profile.company,
            "posting_date": frappe.utils.today(),
            "due_date": frappe.utils.today(),
            "currency": profile.currency or frappe.defaults.get_global_default("currency"),
            "credit_to": profile.payable_account,
            "custom_noon_import_batch": batch_name,
            "custom_noon_reference_nr": f"{reference_nr}::{order_nr}::logistics_adjustment",
            "remarks": f"Noon logistics adjustment | Order: {order_nr} | Ref: {reference_nr}",
            "items": [],
        })

        if fulfilment > 0:
            pi.append("items", {
                "item_code": fee_item_code,
                "qty": 1,
                "rate": fulfilment,
                "expense_account": "5230 - Noon Marketplace Fees - EPC",
                "cost_center": profile.cost_center,
                "description": f"Logistics adjustment fee | Order: {order_nr} | Ref: {reference_nr}",
            })

        if subsidy > 0:
            pi.append("items", {
                "item_code": fee_item_code,
                "qty": 1,
                "rate": -1 * subsidy,
                "expense_account": "5230 - Noon Marketplace Fees - EPC",
                "cost_center": profile.cost_center,
                "description": f"Logistics adjustment subsidy | Order: {order_nr} | Ref: {reference_nr}",
            })

        pi.insert(ignore_permissions=True)
        created.append({
            "order_nr": order_nr,
            "purchase_invoice": pi.name,
            "fee": fulfilment,
            "subsidy": subsidy,
        })

    frappe.db.commit()

    return {
        "batch": batch_name,
        "created_count": len(created),
        "skipped_count": len(skipped),
        "created": created,
        "skipped": skipped,
    }


@frappe.whitelist()
def build_payment_entry_drafts(batch_name: str):
    profile_name = frappe.db.get_value("Noon Import Batch", batch_name, "profile")
    profile = frappe.get_doc("Noon Marketplace Profile", profile_name)

    payment_rows = frappe.get_all(
        "Noon Import Row",
        filters={
            "batch": batch_name,
            "transaction_type": "payment",
        },
        fields=["name", "reference_nr", "gross_amount"],
        order_by="creation asc",
    )

    source_account = profile.settlement_clearing_account
    target_account = profile.bank_ledger_account

    if not source_account:
        frappe.throw(f"Noon profile {profile.name} is missing Settlement Clearing Account")

    if not target_account:
        frappe.throw(f"Noon profile {profile.name} is missing Bank Ledger Account")

    source_currency = frappe.db.get_value("Account", source_account, "account_currency")
    target_currency = frappe.db.get_value("Account", target_account, "account_currency")

    created = []
    skipped = []

    meta = frappe.get_meta("Noon Import Row")
    has_transaction_date = any(df.fieldname == "transaction_date" for df in meta.fields)

    for row in payment_rows:
        reference_nr = row.get("reference_nr")
        amount = abs(flt(row.get("gross_amount")))

        if not reference_nr:
            skipped.append({
                "row": row.get("name"),
                "reason": "missing_reference_nr",
            })
            continue

        if not amount:
            skipped.append({
                "row": row.get("name"),
                "reference_nr": reference_nr,
                "reason": "zero_amount",
            })
            continue

        existing = frappe.db.exists(
            "Payment Entry",
            {
                "company": profile.company,
                "payment_type": "Receive",
                "party_type": "Customer",
                "party": profile.customer,
                "reference_no": reference_nr,
            },
        )
        if existing:
            skipped.append({
                "row": row.get("name"),
                "reference_nr": reference_nr,
                "reason": "already_exists",
                "payment_entry": existing,
            })
            continue

        posting_date = frappe.utils.today()
        if has_transaction_date:
            txn_date = frappe.db.get_value("Noon Import Row", row.get("name"), "transaction_date")
            if txn_date:
                posting_date = txn_date

        pe = frappe.get_doc({
            "doctype": "Payment Entry",
            "payment_type": "Receive",
            "company": profile.company,
            "posting_date": posting_date,
            "party_type": "Customer",
            "party": profile.customer,
            "paid_from": source_account,
            "paid_from_account_currency": source_currency,
            "paid_to": target_account,
            "paid_to_account_currency": target_currency,
            "paid_amount": amount,
            "received_amount": amount,
            "source_exchange_rate": 1,
            "target_exchange_rate": 1,
            "reference_no": reference_nr,
            "custom_noon_import_batch": batch_name,
            "reference_date": posting_date,
            "remarks": f"Noon settlement payment | Batch: {batch_name} | Ref: {reference_nr}",
        })
        pe.insert(ignore_permissions=True)

        created.append({
            "row": row.get("name"),
            "reference_nr": reference_nr,
            "payment_entry": pe.name,
            "amount": amount,
        })

    frappe.db.commit()

    return {
        "batch": batch_name,
        "created_count": len(created),
        "skipped_count": len(skipped),
        "created": created,
        "skipped": skipped,
    }


@frappe.whitelist()
def build_settlement_payment_entry(batch_name: str):
    return build_payment_entry_drafts(batch_name)


@frappe.whitelist()
def auto_create_fee_mappings_stub(batch_name: str):
    profile = frappe.db.get_value("Noon Import Batch", batch_name, "profile")
    company = frappe.db.get_value("Noon Marketplace Profile", profile, "company")

    fee_rows = frappe.db.sql("""
        select distinct fee_key
        from `tabNoon Import Row`
        where batch = %s
          and source_file = 'Invoices & Credit Notes Report'
          and transaction_type = 'Statement Fee'
          and ifnull(fee_key, '') != ''
        order by fee_key asc
    """, (batch_name,), as_dict=True)

    created = []
    skipped = []

    receivable_keys = {
        "Damaged Returns Fee",
        "New Lost/Found Inventory Fee",
    }

    for row in fee_rows:
        fee_key = row["fee_key"]

        if frappe.db.exists("Noon Fee Mapping", {
            "company": company,
            "fee_key": fee_key,
        }):
            skipped.append({"fee_key": fee_key, "reason": "mapping_exists"})
            continue

        direction = "Receivable from Noon" if fee_key in receivable_keys else "Payable to Noon"

        doc = frappe.get_doc({
            "doctype": "Noon Fee Mapping",
            "company": company,
            "fee_key": fee_key,
            "direction": direction,
            "is_active": 1,
        })
        doc.insert(ignore_permissions=True)

        created.append({
            "fee_key": fee_key,
            "direction": direction,
        })

    frappe.db.commit()

    return {
        "batch": batch_name,
        "company": company,
        "created_count": len(created),
        "skipped_count": len(skipped),
        "created": created,
        "skipped": skipped,
    }


@frappe.whitelist()
def build_sales_return_drafts(batch_name: str):
    profile_name = frappe.db.get_value("Noon Import Batch", batch_name, "profile")
    profile = frappe.get_doc("Noon Marketplace Profile", profile_name)

    credit_rows = frappe.db.sql("""
        select
            r.creditnote_nr,
            r.reference_nr,
            r.partner_sku,
            r.amount,
            r.vat_amount,
            r.gross_amount
        from `tabNoon Import Row` r
        where r.batch = %s
          and r.source_file = 'Invoices & Credit Notes Report'
          and r.transaction_type = 'Customer'
          and r.document_type = 'Creditnote'
          and ifnull(r.creditnote_nr, '') != ''
        order by r.creditnote_nr, r.partner_sku, r.amount
    """, (batch_name,), as_dict=True)

    item_map = {
        d.partner_sku: d.item_code
        for d in frappe.get_all(
            "Noon Item Mapping",
            filters={"company": profile.company, "is_active": 1},
            fields=["partner_sku", "item_code"],
            limit_page_length=0,
        )
    }

    grouped = {}
    for row in credit_rows:
        grouped.setdefault(row.creditnote_nr, []).append(row)

    created = []
    skipped = []

    for creditnote_nr, rows in grouped.items():
        existing = frappe.db.exists("Sales Invoice", {"custom_noon_creditnote_nr": creditnote_nr})
        if existing:
            skipped.append({"creditnote_nr": creditnote_nr, "reason": "already_exists", "sales_invoice": existing})
            continue

        item_groups = {}
        for row in rows:
            item_code = item_map.get(row.partner_sku)
            key = (item_code, flt(row.amount))
            item_groups.setdefault(key, {"qty": 0, "rate": flt(row.amount), "item_code": item_code})
            item_groups[key]["qty"] += 1

        si = frappe.get_doc({
            "doctype": "Sales Invoice",
            "is_return": 1,
            "update_stock": 1,
            "customer": profile.customer,
            "company": profile.company,
            "posting_date": frappe.utils.today(),
            "due_date": frappe.utils.today(),
            "currency": profile.currency or frappe.defaults.get_global_default("currency"),
            "debit_to": profile.settlement_clearing_account,
            "custom_noon_import_batch": batch_name,
            "custom_noon_creditnote_nr": creditnote_nr,
            "custom_noon_reference_nr": rows[0].reference_nr,
            "items": [],
        })

        for _, item in item_groups.items():
            si.append("items", {
                "item_code": item["item_code"],
                "qty": -1 * item["qty"],
                "rate": item["rate"],
                "warehouse": profile.warehouse,
                "cost_center": profile.cost_center,
            })

        si.insert(ignore_permissions=True)
        created.append({"creditnote_nr": creditnote_nr, "sales_return": si.name})

    frappe.db.commit()

    return {
        "batch": batch_name,
        "created_count": len(created),
        "skipped_count": len(skipped),
        "created": created,
        "skipped": skipped,
    }


@frappe.whitelist()
def build_fee_purchase_invoice_drafts(batch_name: str):
    profile_name = frappe.db.get_value("Noon Import Batch", batch_name, "profile")
    profile = frappe.get_doc("Noon Marketplace Profile", profile_name)

    fee_rows = frappe.db.sql("""
        select
            r.invoice_nr,
            r.reference_nr,
            r.fee_key,
            r.amount,
            r.vat_amount,
            r.gross_amount
        from `tabNoon Import Row` r
        left join `tabNoon Fee Mapping` m
          on m.company = %s
         and m.fee_key = r.fee_key
         and ifnull(m.is_active, 0) = 1
        where r.batch = %s
          and r.source_file = 'Invoices & Credit Notes Report'
          and r.transaction_type = 'Statement Fee'
          and r.document_type = 'Invoice'
          and ifnull(r.invoice_nr, '') != ''
          and m.direction = 'Payable to Noon'
        order by r.invoice_nr, r.fee_key, r.amount
    """, (profile.company, batch_name), as_dict=True)

    fee_map = {
        d.fee_key: {
            "item_code": d.item_code,
            "expense_account": d.expense_account,
        }
        for d in frappe.get_all(
            "Noon Fee Mapping",
            filters={"company": profile.company, "is_active": 1},
            fields=["fee_key", "item_code", "expense_account"],
            limit_page_length=0,
        )
    }

    grouped = {}
    for row in fee_rows:
        grouped.setdefault(row.invoice_nr, []).append(row)

    created = []
    skipped = []

    for invoice_nr, rows in grouped.items():
        existing = frappe.db.exists("Purchase Invoice", {"custom_noon_fee_invoice_nr": invoice_nr})
        if existing:
            skipped.append({"invoice_nr": invoice_nr, "reason": "already_exists", "purchase_invoice": existing})
            continue

        pi = frappe.get_doc({
            "doctype": "Purchase Invoice",
            "supplier": profile.supplier,
            "company": profile.company,
            "posting_date": frappe.utils.today(),
            "due_date": frappe.utils.today(),
            "currency": profile.currency or frappe.defaults.get_global_default("currency"),
            "credit_to": profile.payable_account,
            "remarks": f"Noon fee invoice: {invoice_nr} | Ref: {rows[0].reference_nr or ''}",
            "custom_noon_import_batch": batch_name,
            "custom_noon_fee_invoice_nr": invoice_nr,
            "custom_noon_reference_nr": rows[0].reference_nr,
            "items": [],
        })

        for row in rows:
            mapping = fee_map.get(row.fee_key) or {}
            pi.append("items", {
                "item_code": mapping.get("item_code"),
                "description": row.fee_key,
                "qty": 1,
                "rate": flt(row.amount),
                "expense_account": mapping.get("expense_account"),
                "cost_center": profile.cost_center,
            })

        pi.insert(ignore_permissions=True)
        created.append({"invoice_nr": invoice_nr, "purchase_invoice": pi.name})

    frappe.db.commit()

    return {
        "batch": batch_name,
        "created_count": len(created),
        "skipped_count": len(skipped),
        "created": created,
        "skipped": skipped,
    }


@frappe.whitelist()
def run_full_draft_pipeline(batch_name: str, include_payments: int = 0):
    include_payments = cint(include_payments)
    results = {}

    results["analyze_batch"] = analyze_batch(batch_name)
    results["stage_batch_rows"] = stage_batch_rows(batch_name)
    results["auto_create_item_mappings"] = auto_create_exact_item_mappings(batch_name)

    validation = validate_batch_ready(batch_name)
    results["validate_batch_ready"] = validation

    if not validation.get("ready"):
        blocking_issues = validation.get("blocking_issues") or []
        has_missing_item_mappings = any(
            issue.get("type") == "missing_item_mappings"
            for issue in blocking_issues
        )

        if has_missing_item_mappings:
            mapping_report = get_required_mappings(batch_name)
            unresolved_item_mappings = [
                row for row in (mapping_report.get("item_mappings_needed") or [])
                if not row.get("mapped_item_code")
            ]
            results["missing_item_mapping_report"] = mapping_report
            results["unresolved_item_mappings_count"] = len(unresolved_item_mappings)
            results["unresolved_item_mappings_preview"] = unresolved_item_mappings[:20]
            return {
                "batch": batch_name,
                "include_payments": include_payments,
                "results": results,
            }

        if blocking_issues:
            frappe.throw(blocking_issues[0].get("message"))
        frappe.throw("الدفعة غير جاهزة لإنشاء المسودات المطلوبة.")

    results["build_sales_invoice_drafts"] = build_sales_invoice_drafts(batch_name)
    results["build_sales_return_drafts"] = build_sales_return_drafts(batch_name)
    results["build_fee_purchase_invoice_drafts"] = build_fee_purchase_invoice_drafts(batch_name)
    results["build_fee_receivable_sales_invoice_drafts"] = build_fee_receivable_sales_invoice_drafts(batch_name)
    results["build_commercial_adjustment_returns"] = build_commercial_adjustment_returns(batch_name)
    results["build_logistics_adjustment_purchase_invoices"] = build_logistics_adjustment_purchase_invoices(batch_name)

    if include_payments:
        results["build_payment_entry_drafts"] = build_payment_entry_drafts(batch_name)

    results["summarize_batch_financials"] = summarize_batch_financials(batch_name)
    results["summarize_transaction_view_financials"] = summarize_transaction_view_financials(batch_name)
    results["reconcile_batch_by_statement"] = reconcile_batch_by_statement(batch_name)

    return {
        "batch": batch_name,
        "include_payments": include_payments,
        "results": results,
    }
