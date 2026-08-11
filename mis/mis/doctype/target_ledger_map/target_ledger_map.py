# Copyright (c) 2026, mantra and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

MONTH_ORDER = ["Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"]


class TargetLedgerMap(Document):
	def validate(self):
		self.validate_uniqueness()
		self.populate_targets()

	def validate_uniqueness(self):
		if not (self.bu and self.target and self.fiscal_year):
			return

		existing = frappe.db.exists("Target Ledger Map", {
			"bu": self.bu,
			"target": self.target,
			"fiscal_year": self.fiscal_year,
			"name": ("!=", self.name)
		})

		if existing:
			frappe.throw(
				_("A Target Ledger Map record already exists for BU '{0}', Particular '{1}', and Fiscal Year '{2}' ({3}).")
				.format(self.bu, self.target, self.fiscal_year, existing)
			)

	def populate_targets(self):
		# Ensure all 12 months (Apr to Mar) exist in targets table
		existing_map = {d.month: d.amount for d in (self.targets or []) if d.month}
		self.targets = []
		for m in MONTH_ORDER:
			self.append("targets", {
				"month": m,
				"amount": existing_map.get(m, 0)
			})
