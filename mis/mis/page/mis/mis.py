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
   - Direct ledger-mapped particulars (e.g. Employee Expense, Software Expense,
     Travel Expense, Marketing Expense, Other operating expense, Capex, Bad debt,
     Inventory Write off, Receivable Cost) fetch GL balances directly based on
     the Target Ledger Map configuration.

3. TARGET DISBURSAL & PERIOD CALCULATIONS:
   - Amounts defined in `Target Ledger Map` (`lm.amount`) are treated as ANNUAL targets.
   - Monthly Planned Target = Yearly Target / Total Months in FY (usually 12).
   - Quarterly Planned Target = Monthly Planned Target * 3.
   - Full Year Planned Target = Yearly Target sum across mapped BUs.

4. ACCOUNT DEDUPLICATION:
   - Target accounts are expanded into unique leaf accounts to prevent double-counting
     when both a parent group account and its child group accounts are mapped.

5. COMPANY FALLBACK:
   - Primary: frappe.defaults.get_user_default("Company")
   - Fallback: Global Defaults -> default_company

6. BU SELECTION & AGGREGATION:
   - Queries `Bu Master` documents that have a valid `cost_center` assigned.
   - All temporal metrics (Monthly, Quarterly, Both) are computed BU-wise as well as
     aggregated under a "Grand Total" column.
================================================================================
"""

import frappe
import calendar
from frappe.utils import flt, getdate, cint
from collections import OrderedDict

from erpnext.accounts.report.financial_statements import (
	get_data,
	get_period_list,
)


def _get_leaf_accounts(account_list):
	"""Expand mapped group accounts into unique leaf accounts to prevent double counting."""
	leaf_accounts = set()
	for acc in account_list:
		acc_info = frappe.db.get_value("Account", acc, ["is_group", "lft", "rgt"], as_dict=True)
		if not acc_info:
			continue
		if acc_info.is_group:
			children = frappe.db.get_all(
				"Account",
				filters={
					"lft": (">=", acc_info.lft),
					"rgt": ("<=", acc_info.rgt),
					"is_group": 0
				},
				pluck="name"
			)
			leaf_accounts.update(children)
		else:
			leaf_accounts.add(acc)
	return leaf_accounts


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
		opex_names = ["Employee Expense", "Software Expense", "Travel Expense", "Marketing Expense", "Other operating expense"]
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

	company = frappe.defaults.get_user_default("Company")
	if not company:
		company = frappe.db.get_single_value("Global Defaults", "default_company")
	if not company:
		frappe.throw("Please set a default Company")

	# Fetch all BUs (including group BUs if they have a cost center)
	bus = frappe.db.get_all(
		"Bu Master",
		fields=["name", "bu_name", "cost_center"],
		order_by="bu_name asc"
	)
	if not bus:
		return {"bus": [], "particulars": [], "data": {}}

	bu_cc_map = {d.name: d.cost_center for d in bus if d.cost_center}

	# Fetch Target Ledger Maps
	ledger_maps = frappe.db.get_all(
		"Target Ledger Map", fields=["name", "target", "bu", "amount"]
	)

	target_map = {}
	all_accounts = set()
	for lm in ledger_maps:
		accounts = frappe.db.get_all(
			"Target Account",
			filters={"parent": lm.name, "parenttype": "Target Ledger Map"},
			fields=["account"], pluck="account"
		)
		# Expand group accounts to unique leaf accounts
		leaf_accs = _get_leaf_accounts(accounts)
		target_map[(lm.target, lm.bu)] = {
			"target_amount": flt(lm.amount), "accounts": list(leaf_accs)
		}
		all_accounts.update(leaf_accs)

	particulars = frappe.db.get_all(
		"Particulars", fields=["name"], order_by="creation asc", pluck="name"
	)

	if not all_accounts and not particulars:
		return {
			"bus": [{"name": d.name, "bu_name": d.bu_name} for d in bus],
			"particulars": particulars, "data": {}, "view": "yearly"
		}

	need_temporal = show_monthly or show_quarterly

	# ── Build period list using ERPNext's engine ──
	period_list = get_period_list(
		fiscal_year, fiscal_year,
		fy.year_start_date, fy.year_end_date,
		"Fiscal Year", "Monthly" if need_temporal else "Yearly",
		company=company
	)

	# ── Fetch financial data per BU using ERPNext's get_data ──
	bu_financial_data = {}

	for bu in bus:
		cc = bu_cc_map.get(bu.name)
		if not cc:
			continue

		filters = frappe._dict({
			"company": company,
			"period_start_date": fy.year_start_date,
			"period_end_date": fy.year_end_date,
			"filter_based_on": "Fiscal Year",
			"periodicity": "Monthly" if need_temporal else "Yearly",
			"cost_center": cc,
			"accumulated_values": 0,
		})

		income_list = get_data(company, "Income", "Credit", period_list, filters=filters) or []
		expense_list = get_data(company, "Expense", "Debit", period_list, filters=filters) or []

		income_map = {}
		for d in income_list:
			acc_key = d.get("account") or d.get("account_id") or d.get("name")
			if acc_key:
				income_map[acc_key] = d

		expense_map = {}
		for d in expense_list:
			acc_key = d.get("account") or d.get("account_id") or d.get("name")
			if acc_key:
				expense_map[acc_key] = d

		bu_financial_data[bu.name] = {
			"income": income_map,
			"expense": expense_map,
		}

	# ── Map financial data to Particulars ──
	def get_account_total(bu_name, account_name, period_key=None):
		"""Get value for an account from a BU's financial data."""
		fin = bu_financial_data.get(bu_name, {})
		row = fin.get("income", {}).get(account_name) or fin.get("expense", {}).get(account_name)
		if not row:
			return 0
		if period_key:
			return flt(row.get(period_key, 0))
		return flt(row.get("total", 0))

	def get_particular_actual(particular, bu_name, period_key=None):
		"""Sum actuals for all unique leaf accounts mapped to a particular for a given BU."""
		tm = target_map.get((particular, bu_name))
		if not tm:
			return 0
		total = 0
		for acc in tm["accounts"]:
			total += get_account_total(bu_name, acc, period_key)
		return total

	bus_list = [{"name": d.name, "bu_name": d.bu_name} for d in bus]

	# ── Build response data ──
	months_info = []
	for p in period_list:
		months_info.append({"key": p.key, "label": p.label})

	quarters = []
	for qi in range(0, len(months_info), 3):
		q_months = months_info[qi:qi + 3]
		q_num = (qi // 3) + 1
		quarters.append({
			"label": f"Q{q_num}", "key": f"Q{q_num}",
			"month_keys": [mm["key"] for mm in q_months]
		})

	num_months = len(months_info) if months_info else 12

	if not need_temporal:
		# Yearly view
		data = OrderedDict()
		for particular in particulars:
			bu_data = OrderedDict()
			g_act, g_plan = 0, 0
			for bu in bus:
				bu_store = {p_name: { "FY": data[p_name][bu.name] } for p_name in data if bu.name in data[p_name]}
				calc_val = evaluate_calculated_particular(particular, bu_store, "FY")
				if calc_val:
					act, plan = calc_val["actual"], calc_val["planned"]
				else:
					act = get_particular_actual(particular, bu.name)
					plan = flt(target_map.get((particular, bu.name), {}).get("target_amount", 0))

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

	# Temporal view
	data = OrderedDict()
	for particular in particulars:
		particular_bu_data = OrderedDict()

		for bu in bus:
			bu_row = {}
			# Reconstruct existing particulars for this BU to pass to calculated evaluator
			bu_store = {p_name: data[p_name][bu.name] for p_name in data if bu.name in data[p_name]}

			all_keys = [m["key"] for m in months_info] + [q["key"] for q in quarters] + ["FY"]

			# Check if it's a calculated particular
			sample_calc = evaluate_calculated_particular(particular, bu_store, "FY")

			if sample_calc is not None:
				for pk in all_keys:
					bu_row[pk] = evaluate_calculated_particular(particular, bu_store, pk)
			else:
				annual_target = flt(target_map.get((particular, bu.name), {}).get("target_amount", 0))
				monthly_target = flt(annual_target / num_months, 2) if num_months else 0

				# Monthly
				for mi in months_info:
					act = get_particular_actual(particular, bu.name, mi["key"])
					bu_row[mi["key"]] = make_apv(act, monthly_target)

				# Quarterly
				for q in quarters:
					q_act = sum(bu_row[mk]["actual"] for mk in q["month_keys"] if mk in bu_row)
					q_plan = flt(monthly_target * len(q["month_keys"]), 2)
					bu_row[q["key"]] = make_apv(q_act, q_plan)

				# FY
				fy_act = sum(bu_row[mi["key"]]["actual"] for mi in months_info if mi["key"] in bu_row)
				bu_row["FY"] = make_apv(fy_act, annual_target)

			particular_bu_data[bu.name] = bu_row

		# Grand Total
		gt_row = {}
		all_period_keys = [m["key"] for m in months_info] + [q["key"] for q in quarters] + ["FY"]
		for pk in all_period_keys:
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
