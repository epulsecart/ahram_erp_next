import frappe
from frappe.utils import get_first_day, get_last_day, add_months, getdate


def elog(title, message):
    d = frappe.new_doc("Error Log")
    d.title = title
    d.method = title
    d.error = message
    d.insert(ignore_permissions=True)


def slab_rate(total, thresholds):
    for limit, rate in thresholds:
        if total < limit:
            return rate
    return 0.0


def add_total(totals, sales_person, amount):
    if not sales_person:
        return
    cur = float(totals.get(sales_person) or 0)
    totals[sales_person] = cur + float(amount or 0)


def upsert_additional_salary_draft(employee, amount, payroll_date, run_key, component, trace):
    if not employee:
        trace.append("SKIP employee empty")
        return False

    if float(amount or 0) <= 0:
        trace.append("SKIP amount <= 0")
        return False

    existing = frappe.db.get_value(
        "Additional Salary",
        {
            "employee": employee,
            "salary_component": component,
            "payroll_date": payroll_date,
            "docstatus": 0,
        },
        "name",
    )

    if existing:
        doc = frappe.get_doc("Additional Salary", existing)
        doc.amount = float(amount)
        doc.remarks = run_key
        doc.overwrite_salary_structure_amount = 1
        doc.save(ignore_permissions=True)
        trace.append("UPDATED DRAFT Additional Salary " + doc.name + " amount=" + str(float(amount)))
        return True

    doc = frappe.get_doc({
        "doctype": "Additional Salary",
        "employee": employee,
        "salary_component": component,
        "amount": float(amount),
        "payroll_date": payroll_date,
        "overwrite_salary_structure_amount": 1,
        "remarks": run_key,
    })

    doc.insert(ignore_permissions=True)
    trace.append("CREATED DRAFT Additional Salary " + doc.name + " amount=" + str(float(amount)))
    return True


def _load_settings():
    s = frappe.get_single("EPC App Settings")
    return s


def _build_thresholds(settings):
    rows = list(settings.get("commission_slabs") or [])
    if not rows:
        return [
            (70000, 0.00),
            (100000, 0.01),
            (150000, 0.015),
            (10**18, 0.02),
        ]

    rows.sort(key=lambda r: float(r.limit_amount or 0))

    thresholds = []
    for r in rows:
        if not r.limit_amount:
            continue

        limit = float(r.limit_amount)
        rate = float(r.rate or 0)

        # if user entered 10 / 20 / 50 meaning 10% / 20% / 50%
        if rate >= 1:
            rate = rate / 100.0

        thresholds.append((limit, rate))

    if not thresholds or thresholds[-1][0] < 10**18:
        thresholds.append((10**18, thresholds[-1][1] if thresholds else 0.0))

    return thresholds


def _period_dates(period_label: str):
    today = getdate()
    base = today
    if (period_label or "Last Month") == "Last Month":
        base = add_months(today, -1)

    start = get_first_day(base)
    end = get_last_day(base)
    return str(start), str(end), str(end)  # payroll_date = end


def run():
    settings = _load_settings()

    if not int(settings.enable_auto_commission or 0):
        return

    force_run = int(settings.force_run or 0)
    component = settings.commission_component or "العمولات"
    suffix = settings.run_key_suffix or "MONTHLY"
    thresholds = _build_thresholds(settings)

    start, end, payroll_date = _period_dates(settings.commission_period)

    run_key = "AUTO_COMM_FULLPAID_" + start[:7] + "_" + suffix

    trace = []
    trace.append(f"PING start={start} end={end} run_key={run_key} FORCE_RUN={force_run}")

    if not force_run:
        trace.append("STOP FORCE_RUN=0")
        elog("AUTO COMMISSION (SKIPPED)", "\n".join(trace[-300:]))
        return

    totals = {}

    # ===== STEP 1: POS-like =====
    trace.append("STEP 1 POS-like START")

    pos_rows = frappe.db.sql("""
        SELECT st.sales_person AS sales_person,
               SUM(si.net_total * IFNULL(st.allocated_percentage,100)/100) AS total
        FROM `tabSales Invoice` si
        JOIN `tabSales Team` st
          ON st.parent = si.name
        WHERE si.docstatus = 1
          AND IFNULL(si.is_return,0)=0
          AND IFNULL(si.outstanding_amount,0)<=0
          AND si.posting_date BETWEEN %s AND %s
          AND (
                IFNULL(si.is_pos,0)=1
                OR EXISTS (
                    SELECT 1 FROM `tabSales Invoice Payment` sip
                    WHERE sip.parent = si.name
                )
          )
        GROUP BY st.sales_person
    """, (start, end), as_dict=True)

    trace.append("STEP 1 rows=" + str(len(pos_rows)))
    for r in pos_rows:
        add_total(totals, r.get("sales_person"), r.get("total"))

    # ===== STEP 2: NON-POS =====
    trace.append("STEP 2 NON-POS START")

    nonpos_rows = frappe.db.sql("""
        SELECT st.sales_person AS sales_person,
               SUM(si.net_total * IFNULL(st.allocated_percentage,100)/100) AS total
        FROM `tabSales Invoice` si
        JOIN (
            SELECT per.reference_name AS invoice,
                   MAX(pe.posting_date) AS last_payment_date
            FROM `tabPayment Entry Reference` per
            JOIN `tabPayment Entry` pe ON pe.name = per.parent
            WHERE pe.docstatus = 1
              AND per.reference_doctype = 'Sales Invoice'
            GROUP BY per.reference_name
        ) p ON p.invoice = si.name
        JOIN `tabSales Team` st
          ON st.parent = si.name
        WHERE si.docstatus = 1
          AND IFNULL(si.is_return,0)=0
          AND IFNULL(si.outstanding_amount,0)<=0
          AND p.last_payment_date BETWEEN %s AND %s
          AND NOT EXISTS (
                SELECT 1 FROM `tabSales Invoice Payment` sip
                WHERE sip.parent = si.name
          )
        GROUP BY st.sales_person
    """, (start, end), as_dict=True)

    trace.append("STEP 2 rows=" + str(len(nonpos_rows)))
    for r in nonpos_rows:
        add_total(totals, r.get("sales_person"), r.get("total"))

    # ===== STEP 3: COMMISSION =====
    trace.append("STEP 3 CALC START SP=" + str(len(totals)) + " payroll_date=" + str(payroll_date))

    done = 0
    errors = 0

    for sp in totals:
        try:
            total = float(totals.get(sp) or 0)
            rate = slab_rate(total, thresholds)
            commission = round(total * rate, 2)

            trace.append(f"SP={sp} total={round(total,2)} rate={rate} commission={commission}")

            if commission <= 0:
                continue

            employee = frappe.db.get_value("Sales Person", sp, "employee")
            if not employee:
                continue

            ok = upsert_additional_salary_draft(employee, commission, payroll_date, run_key, component, trace)
            if ok:
                done += 1

        except Exception as e:
            errors += 1
            trace.append("ERROR sp=" + str(sp) + " msg=" + str(e))

    trace.append(f"DONE updated_or_created_draft={done} errors={errors} run_key={run_key}")
    elog("AUTO COMMISSION (RESULT)", "\n".join(trace[-350:]))


def execute():
    run()
