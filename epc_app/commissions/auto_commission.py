import frappe

# ===== إعدادات =====
COMPONENT = "العمولات"

THRESHOLDS = [
    (70000, 0.00),
    (100000, 0.01),
    (150000, 0.015),
    (10**18, 0.02),
]

FORCE_RUN = 1

TEST_START = "2026-01-01"
TEST_END   = "2026-01-31"

RUN_KEY_SUFFIX = "MONTHLY"
# ===================


def slab_rate(total):
    for limit, rate in THRESHOLDS:
        if total < limit:
            return rate
    return 0.0


def elog(title, message):
    d = frappe.new_doc("Error Log")
    d.title = title
    d.method = title
    d.error = message
    d.insert(ignore_permissions=True)


def add_total(totals, sales_person, amount):
    if not sales_person:
        return
    cur = float(totals.get(sales_person) or 0)
    totals[sales_person] = cur + float(amount or 0)


def upsert_additional_salary_draft(employee, amount, payroll_date, run_key, trace):
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
            "salary_component": COMPONENT,
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
        "salary_component": COMPONENT,
        "amount": float(amount),
        "payroll_date": payroll_date,
        "overwrite_salary_structure_amount": 1,
        "remarks": run_key,
    })

    doc.insert(ignore_permissions=True)
    trace.append("CREATED DRAFT Additional Salary " + doc.name + " amount=" + str(float(amount)))
    return True


def run():
    trace = []

    start = TEST_START
    end = TEST_END
    payroll_date = end

    run_key = "AUTO_COMM_FULLPAID_" + start[:7] + "_" + RUN_KEY_SUFFIX

    trace.append(
        "PING start=" + str(start)
        + " end=" + str(end)
        + " run_key=" + str(run_key)
        + " FORCE_RUN=" + str(FORCE_RUN)
    )

    if not FORCE_RUN:
        trace.append("STOP FORCE_RUN=0")
        elog("AUTO COMMISSION (SKIPPED)", "\n".join(trace[-300:]))
        return

    totals = {}

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
    trace.append("STEP 1 sample=" + str(pos_rows[:10]))

    for r in pos_rows:
        add_total(totals, r.get("sales_person"), r.get("total"))

    trace.append("STEP 1 totals=" + str(list(totals.items())[:30]))

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
    trace.append("STEP 2 sample=" + str(nonpos_rows[:10]))

    for r in nonpos_rows:
        add_total(totals, r.get("sales_person"), r.get("total"))

    trace.append("STEP 2 totals=" + str(list(totals.items())[:30]))

    trace.append("STEP 3 CALC START SP=" + str(len(totals)) + " payroll_date=" + str(payroll_date))

    done = 0
    errors = 0

    for sp in totals:
        try:
            total = float(totals.get(sp) or 0)
            rate = slab_rate(total)
            commission = round(total * rate, 2)

            trace.append("SP=" + str(sp) + " total=" + str(round(total,2)) + " rate=" + str(rate) + " commission=" + str(commission))

            if commission <= 0:
                trace.append("SP=" + str(sp) + " SKIP commission<=0")
                continue

            employee = frappe.db.get_value("Sales Person", sp, "employee")
            if not employee:
                trace.append("SP=" + str(sp) + " SKIP no employee linked")
                continue

            ok = upsert_additional_salary_draft(employee, commission, payroll_date, run_key, trace)
            if ok:
                done += 1

        except Exception as e:
            errors += 1
            trace.append("ERROR sp=" + str(sp) + " msg=" + str(e))

    trace.append("DONE updated_or_created_draft=" + str(done) + " errors=" + str(errors) + " run_key=" + str(run_key))
    elog("AUTO COMMISSION (RESULT)", "\n".join(trace[-350:]))


def execute():
    run()
