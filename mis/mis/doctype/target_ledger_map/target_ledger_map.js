// Copyright (c) 2026, mantra and contributors
// For license information, please see license.txt

const MONTH_ORDER = [
	"Apr", "May", "Jun", "Jul", "Aug", "Sep",
	"Oct", "Nov", "Dec", "Jan", "Feb", "Mar"
];

frappe.ui.form.on("Target Ledger Map", {
	onload: function (frm) {
		frm.set_df_property("targets", "cannot_add_rows", true);
		frm.set_df_property("targets", "cannot_delete_rows", true);
	},
	refresh: function (frm) {
		frm.set_df_property("targets", "cannot_add_rows", true);
		frm.set_df_property("targets", "cannot_delete_rows", true);

		// If targets table is empty, populate default 12 months (Apr to Mar)
		if (!frm.doc.targets || frm.doc.targets.length === 0) {
			MONTH_ORDER.forEach(m => {
				let row = frm.add_child("targets");
				row.month = m;
				row.amount = 0;
			});
			frm.refresh_field("targets");
		}
	}
});
