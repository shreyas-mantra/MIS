"""
================================================================================
MANAGEMENT INFORMATION SYSTEM (MIS) - HARDCODED LOGIC & ASSUMPTIONS
================================================================================

1. CALCULATED PARTICULAR LOGIC:
   - Derived rows are calculated dynamically from dependent Particulars:
     * "Gross Profit" = Revenue - Cost of goods sold
     * "Gross Profit Margin (%)" = (Gross Profit / Revenue) * 100
     * "EBITDA" = Gross Profit - Sum(Operating Expenses)
     * "Profit Before Tax" = EBITDA - (Depreciation + Interest)

2. STANDARD PARTICULAR LOGIC:
   - Direct ledger-mapped particulars fetch GL balances directly based on
     the Target Ledger Map configuration.

3. TARGET DISBURSAL BY FISCAL YEAR & MONTHLY TARGETS TABLE:
   - Targets are defined per Fiscal Year in `Target Ledger Map` via the `Targets` child table.
   - Monthly Planned Target = Exact amount configured for that month (Apr-Mar) in child table.
   - Quarterly Planned Target = Sum of monthly planned targets for that quarter's 3 months.
   - Full Year Planned Target = Sum of all 12 monthly targets in FY.

4. HIGH-PERFORMANCE DIRECT GL AGGREGATION:
   - Filters GL entries directly by (Company, Fiscal Year, Target Accounts, Cost Centers).
   - Eliminates CPU spikes and database lock wait delays.

5. COMPANY FALLBACK:
   - Primary: frappe.defaults.get_user_default("Company")
   - Fallback: Global Defaults -> default_company

6. BU SELECTION & AGGREGATION:
   - Queries `Bu Master` documents that have a valid `cost_center` assigned.
   - Computes BU-wise performance as well as an aggregated "Grand Total" column.
================================================================================
"""

import frappe
from frappe.utils import flt, getdate, cint
from collections import OrderedDict

from erpnext.accounts.report.financial_statements import (
	get_period_list,
)

CALCULATED_KEYS = {
	"gross profit",
	"gross profit margin (%)",
	"ebitda",
	"profit before tax",
}


def make_apv(act, plan):
	"""Format Actual, Planned, and Variance dictionary."""
	var = flt((act - plan) / plan * 100, 2) if plan else 0
	return {"actual": flt(act, 2), "planned": flt(plan, 2), "variance": var}


def evaluate_calculated_particular(particular_name, bu_data_store, period_key="FY"):
	"""
	Evaluates dynamic derived formula rows:
	- Gross Profit
	- Gross Profit Margin (%)
	- EBITDA
	- Profit Before Tax
	"""
	p_lower = particular_name.lower().strip()

	def get_p(name):
		return bu_data_store.get(name, {}).get(period_key, {"actual": 0, "planned": 0})

	if p_lower == "gross profit":
		rev = get_p("Revenue")
		cogs = get_p("Cost of goods sold")
		return make_apv(rev["actual"] - cogs["actual"], rev["planned"] - cogs["planned"])

	elif "gross profit margin" in p_lower:
		rev = get_p("Revenue")
		gp = get_p("Gross Profit")
		act_margin = (gp["actual"] / rev["actual"] * 100) if rev["actual"] else 0
		plan_margin = (gp["planned"] / rev["planned"] * 100) if rev["planned"] else 0
		var = flt(act_margin - plan_margin, 2)
		return {"actual": flt(act_margin, 2), "planned": flt(plan_margin, 2), "variance": var}

	elif p_lower == "ebitda":
		gp = get_p("Gross Profit")
		opex_names = [
			"Employee Expense", "Software Expense", "Travel Expense",
			"Marketing Expense", "Other operating expense"
		]
		opex_act = sum(get_p(k)["actual"] for k in opex_names)
		opex_plan = sum(get_p(k)["planned"] for k in opex_names)
		return make_apv(gp["actual"] - opex_act, gp["planned"] - opex_plan)

	elif p_lower == "profit before tax":
		ebitda = get_p("EBITDA")
		depr_act = get_p("Depreciation")["actual"] + get_p("Depreciation & Amortization")["actual"]
		depr_plan = get_p("Depreciation")["planned"] + get_p("Depreciation & Amortization")["planned"]
		interest_act = get_p("Interest Expense")["actual"]
		interest_plan = get_p("Interest Expense")["planned"]
		return make_apv(ebitda["actual"] - depr_act - interest_act, ebitda["planned"] - depr_plan - interest_plan)

	return None


@frappe.whitelist()
def get_mis_data(fiscal_year, show_monthly=0, show_quarterly=0):
	show_monthly = cint(show_monthly)
	show_quarterly = cint(show_quarterly)

	fy = frappe.db.get_value(
		"Fiscal Year", fiscal_year,
		["year_start_date", "year_end_date"], as_dict=True
	)
	if not fy:
		frappe.throw(f"Fiscal Year {fiscal_year} not found")

	company = frappe.defaults.get_user_default("Company") or frappe.db.get_single_value("Global Defaults", "default_company")
	if not company:
		frappe.throw("Please set a default Company")

	# Fetch all BUs ordered by bu_name asc
	bus = frappe.db.get_all(
		"Bu Master",
		fields=["name", "bu_name", "cost_center"],
		order_by="bu_name asc"
	)
	if not bus:
		return {"bus": [], "particulars": [], "data": {}}

	bu_cc_map = {d.name: d.cost_center for d in bus if d.cost_center}
	cc_bu_map = {d.cost_center: d.name for d in bus if d.cost_center}

	# ── Bulk fetch all accounts and pre-build leaf accounts map ──
	accounts_raw = frappe.db.get_all(
		"Account",
		fields=["name", "is_group", "lft", "rgt", "root_type"]
	)
	accounts_map = {d.name: d for d in accounts_raw}
	leaf_accounts_list = [d for d in accounts_raw if not d.is_group]

	def expand_to_leaf_accounts(acc_list):
		leaf_set = set()
		for acc_name in acc_list:
			acc_info = accounts_map.get(acc_name)
			if not acc_info:
				continue
			if acc_info.is_group:
				lft, rgt = acc_info.lft, acc_info.rgt
				for child in leaf_accounts_list:
					if lft <= child.lft and child.rgt <= rgt:
						leaf_set.add(child.name)
			else:
				leaf_set.add(acc_info.name)
		return leaf_set

	# ── Bulk fetch Target Ledger Maps filtered by Fiscal Year (with fallback) ──
	ledger_maps = frappe.db.sql(
		"""
		SELECT name, target, bu, fiscal_year
		FROM `tabTarget Ledger Map`
		WHERE fiscal_year = %s OR ifnull(fiscal_year, '') = ''
		""",
		(fiscal_year,),
		as_dict=True
	)

	lm_names = [lm.name for lm in ledger_maps] if ledger_maps else []
	ta_grouped = {}
	monthly_targets_grouped = {}

	if lm_names:
		# Bulk fetch Target Account links for matched parent maps
		ta_rows = frappe.db.get_all(
			"Target Account",
			filters={"parenttype": "Target Ledger Map", "parent": ["in", lm_names]},
			fields=["parent", "account"]
		)
		for ta in ta_rows:
			ta_grouped.setdefault(ta.parent, []).append(ta.account)

		# Bulk fetch Targets monthly child table for matched parent maps
		monthly_targets_raw = frappe.db.get_all(
			"Targets",
			filters={"parenttype": "Target Ledger Map", "parent": ["in", lm_names]},
			fields=["parent", "month", "amount"]
		)
		for mt in monthly_targets_raw:
			monthly_targets_grouped.setdefault(mt.parent, {})[mt.month] = flt(mt.amount)

	target_map = {}
	all_accounts = set()
	for lm in ledger_maps:
		accs = ta_grouped.get(lm.name, [])
		leaf_accs = expand_to_leaf_accounts(accs)
		m_amounts = monthly_targets_grouped.get(lm.name, {})
		yearly_target = sum(m_amounts.values())

		target_map[(lm.target, lm.bu)] = {
			"yearly_target": yearly_target,
			"monthly_targets": m_amounts,
			"accounts": list(leaf_accs)
		}
		all_accounts.update(leaf_accs)

	particulars = frappe.db.get_all(
		"Particulars", fields=["name"], order_by="creation asc", pluck="name"
	)

	bus_list = [{"name": d.name, "bu_name": d.bu_name} for d in bus]

	if not all_accounts and not particulars:
		return {
			"bus": bus_list,
			"particulars": particulars,
			"data": {},
			"view": "yearly"
		}

	need_temporal = show_monthly or show_quarterly

	# ── Period list ──
	period_list = get_period_list(
		fiscal_year, fiscal_year,
		fy.year_start_date, fy.year_end_date,
		"Fiscal Year", "Monthly" if need_temporal else "Yearly",
		company=company
	)

	# ── High Performance GL Entry Query ──
	bu_gl_map = {}

	if all_accounts and cc_bu_map:
		valid_ccs = list(cc_bu_map.keys())
		valid_accs = list(all_accounts)

		gl_entries = frappe.db.sql(
			"""
			SELECT 
				account,
				cost_center,
				posting_date,
				debit,
				credit
			FROM `tabGL Entry`
			WHERE company = %s
			  AND is_cancelled = 0
			  AND posting_date >= %s
			  AND posting_date <= %s
			  AND account IN %s
			  AND cost_center IN %s
			""",
			(company, fy.year_start_date, fy.year_end_date, tuple(valid_accs), tuple(valid_ccs)),
			as_dict=True
		)

		for gle in gl_entries:
			p_date = getdate(gle.posting_date)
			matched_period_key = None
			for p in period_list:
				if getdate(p.from_date) <= p_date <= getdate(p.to_date):
					matched_period_key = p.key
					break

			acc_info = accounts_map.get(gle.account)
			root_type = acc_info.root_type if acc_info else ""
			if root_type == "Income":
				net_val = flt(gle.credit) - flt(gle.debit)
			else:
				net_val = flt(gle.debit) - flt(gle.credit)

			bu_name = cc_bu_map.get(gle.cost_center)
			if bu_name:
				if matched_period_key:
					bu_gl_map[(bu_name, gle.account, matched_period_key)] = bu_gl_map.get((bu_name, gle.account, matched_period_key), 0.0) + net_val
				bu_gl_map[(bu_name, gle.account, "total")] = bu_gl_map.get((bu_name, gle.account, "total"), 0.0) + net_val

	def get_account_total(bu_name, account_name, period_key=None):
		key = period_key if period_key else "total"
		return bu_gl_map.get((bu_name, account_name, key), 0.0)

	def get_particular_actual(particular, bu_name, period_key=None):
		tm = target_map.get((particular, bu_name))
		if not tm:
			return 0
		total = 0
		for acc in tm["accounts"]:
			total += get_account_total(bu_name, acc, period_key)
		return total

	months_info = [{"key": p.key, "label": p.label} for p in period_list]
	quarters = []
	for qi in range(0, len(months_info), 3):
		q_months = months_info[qi:qi + 3]
		q_num = (qi // 3) + 1
		quarters.append({
			"label": f"Q{q_num}", "key": f"Q{q_num}",
			"month_keys": [mm["key"] for mm in q_months]
		})

	# Helper to get monthly target from Target Ledger Map
	def get_monthly_target(particular, bu_name, month_key):
		tm = target_map.get((particular, bu_name))
		if not tm:
			return 0.0
		# Extract month code (e.g. apr_2025 -> Apr)
		month_code = month_key.split("_")[0].capitalize()
		return flt(tm.get("monthly_targets", {}).get(month_code, 0.0))

	# ── Response building ──
	if not need_temporal:
		# Yearly View
		data = OrderedDict()
		for particular in particulars:
			bu_data = OrderedDict()
			g_act, g_plan = 0, 0
			is_calc = particular.lower().strip() in CALCULATED_KEYS

			for bu in bus:
				if is_calc:
					bu_store = {p_name: {"FY": data[p_name][bu.name]} for p_name in data if bu.name in data[p_name]}
					calc_val = evaluate_calculated_particular(particular, bu_store, "FY")
					act, plan = calc_val["actual"], calc_val["planned"]
				else:
					act = get_particular_actual(particular, bu.name)
					tm = target_map.get((particular, bu.name))
					plan = flt(tm.get("yearly_target", 0)) if tm else 0.0

				bu_data[bu.name] = make_apv(act, plan)
				g_act += act
				g_plan += plan

			bu_data["Grand Total"] = make_apv(g_act, g_plan)
			data[particular] = bu_data

		return {
			"view": "yearly",
			"bus": bus_list,
			"particulars": particulars,
			"data": data
		}

	# Temporal View (Monthly / Quarterly / Both)
	data = OrderedDict()
	all_keys = [m["key"] for m in months_info] + [q["key"] for q in quarters] + ["FY"]

	for particular in particulars:
		particular_bu_data = OrderedDict()
		is_calc = particular.lower().strip() in CALCULATED_KEYS

		for bu in bus:
			bu_row = {}
			if is_calc:
				bu_store = {p_name: data[p_name][bu.name] for p_name in data if bu.name in data[p_name]}
				for pk in all_keys:
					bu_row[pk] = evaluate_calculated_particular(particular, bu_store, pk)
			else:
				tm = target_map.get((particular, bu.name))
				yearly_target = flt(tm.get("yearly_target", 0)) if tm else 0.0

				# Monthly planned & actuals
				for mi in months_info:
					act = get_particular_actual(particular, bu.name, mi["key"])
					m_plan = get_monthly_target(particular, bu.name, mi["key"])
					bu_row[mi["key"]] = make_apv(act, m_plan)

				# Quarterly planned & actuals
				for q in quarters:
					q_act = sum(bu_row[mk]["actual"] for mk in q["month_keys"] if mk in bu_row)
					q_plan = sum(get_monthly_target(particular, bu.name, mk) for mk in q["month_keys"])
					bu_row[q["key"]] = make_apv(q_act, q_plan)

				# FY planned & actuals
				fy_act = sum(bu_row[mi["key"]]["actual"] for mi in months_info if mi["key"] in bu_row)
				bu_row["FY"] = make_apv(fy_act, yearly_target)

			particular_bu_data[bu.name] = bu_row

		# Grand Total
		gt_row = {}
		for pk in all_keys:
			gt_act = sum(particular_bu_data[b.name].get(pk, {}).get("actual", 0) for b in bus)
			gt_plan = sum(particular_bu_data[b.name].get(pk, {}).get("planned", 0) for b in bus)
			gt_row[pk] = make_apv(gt_act, gt_plan)

		particular_bu_data["Grand Total"] = gt_row
		data[particular] = particular_bu_data

	return {
		"view": "temporal",
		"show_monthly": show_monthly,
		"show_quarterly": show_quarterly,
		"bus": bus_list,
		"particulars": particulars,
		"months": [{"label": m["label"], "key": m["key"]} for m in months_info],
		"quarters": [{"label": q["label"], "key": q["key"], "month_keys": q["month_keys"]} for q in quarters],
		"data": data,
	}
