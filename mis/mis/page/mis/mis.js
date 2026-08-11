// Copyright (c) 2026, mantra and contributors
// For license information, please see license.txt

frappe.pages['mis'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: 'Financial Snapshot',
		single_column: true
	});
	frappe.breadcrumbs.add("MIS", "Financial Snapshot");

	let fiscal_year = page.add_field({
		label: 'Fiscal Year',
		fieldtype: 'Link',
		fieldname: 'fiscal_year',
		options: 'Fiscal Year',
		reqd: 1,
		default: frappe.sys_defaults.fiscal_year
	});

	let show_monthly = page.add_field({
		label: 'Show Monthly',
		fieldtype: 'Check',
		fieldname: 'show_monthly',
		default: 0
	});

	let show_quarterly = page.add_field({
		label: 'Show Quarterly',
		fieldtype: 'Check',
		fieldname: 'show_quarterly',
		default: 0
	});

	let get_data_btn = page.add_field({
		label: 'Get Data',
		fieldtype: 'Button',
		click: () => load_data()
	});

	let export_btn = page.add_field({
		label: 'Export to Excel',
		fieldtype: 'Button',
		click: () => export_excel(),
		hidden: 1
	});

	// Style filter row
	$(page.page_form).css({
		display: "flex",
		"align-items": "flex-end",
		"flex-wrap": "wrap",
		gap: "12px",
		background: "var(--card-bg, #ffffff)",
		padding: "16px 20px",
		"border-radius": "10px",
		border: "1px solid var(--border-color, #f0f0f0)",
		"box-shadow": "var(--shadow-sm, 0 4px 6px -1px rgba(0,0,0,0.05))",
		"margin-bottom": "20px",
		position: "relative",
		"z-index": "100"
	});
	$(page.page_form).find('.frappe-control').css({ margin: "0px" });

	get_data_btn.$input.addClass("btn btn-primary").css({
		padding: "6px 16px",
		"font-weight": "600",
		"border-radius": "6px",
		"margin-top": "22px"
	});
	get_data_btn.$wrapper.find('.control-label').remove();

	export_btn.$input.addClass("btn btn-default").css({
		padding: "6px 16px",
		"font-weight": "600",
		"border-radius": "6px",
		"margin-top": "22px"
	});
	export_btn.$wrapper.find('.control-label').remove();

	let container = $('<div>').appendTo(page.body);

	function load_data() {
		if (!fiscal_year.get_value()) {
			frappe.msgprint(__("Please select a Fiscal Year"));
			return;
		}
		frappe.dom.freeze("Loading MIS Data...");
		frappe.call({
			method: "mis.mis.page.mis.mis.get_mis_data",
			args: {
				fiscal_year: fiscal_year.get_value(),
				show_monthly: show_monthly.get_value() ? 1 : 0,
				show_quarterly: show_quarterly.get_value() ? 1 : 0
			},
			callback: function (r) {
				frappe.dom.unfreeze();
				if (!r.message || !r.message.particulars || !r.message.particulars.length) {
					export_btn.toggle(false);
					container.html('<div class="mis-no-data"><div class="icon">📊</div><p>No data found. Configure Particulars and Target Ledger Maps.</p></div>');
					return;
				}
				// export_btn.toggle(true);
				render(r.message);
			}
		});
	}

	// Initial load
	setTimeout(() => {
		if (fiscal_year.get_value()) {
			load_data();
		}
	}, 200);

	// Export to Excel function preserving full matrix header & cell structure
	function export_excel() {
		let table = container.find('.mis-table')[0];
		if (!table) {
			frappe.msgprint(__("Please click 'Get Data' to load the report before exporting."));
			return;
		}

		let fy = fiscal_year.get_value() || 'FY';
		let fileName = `MIS_Report_${fy}_${frappe.datetime.get_today()}.xls`;

		let html = `
			<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel" xmlns="http://www.w3.org/TR/REC-html40">
			<head>
				<meta charset="utf-8">
				<!--[if gte mso 9]><xml><x:ExcelWorkbook><x:ExcelWorksheets><x:ExcelWorksheet>
				<x:Name>MIS Report</x:Name>
				<x:WorksheetOptions><x:DisplayGridlines/></x:WorksheetOptions>
				</x:ExcelWorksheet></x:ExcelWorksheets></x:ExcelWorkbook></xml><![endif]-->
				<style>
					table { border-collapse: collapse; font-family: Arial, sans-serif; font-size: 11px; }
					th { background-color: #3b5998; color: #ffffff; border: 1px solid #2d4373; text-align: left; font-weight: bold; padding: 6px; }
					td { border: 1px solid #cbd5e1; text-align: right; padding: 4px 8px; }
					td.particular-cell { text-align: left; font-weight: bold; }
					.variance-positive { color: #166534; font-weight: bold; }
					.variance-negative { color: #991b1b; font-weight: bold; }
					.variance-zero { color: #475569; }
				</style>
			</head>
			<body>
				<h2>Management Information System — ${fy}</h2>
				${table.outerHTML}
			</body>
			</html>
		`;

		let blob = new Blob([html], { type: 'application/vnd.ms-excel;charset=utf-8' });
		let link = document.createElement('a');
		link.href = URL.createObjectURL(blob);
		link.download = fileName;
		document.body.appendChild(link);
		link.click();
		document.body.removeChild(link);
	}

	// Format helpers
	function fmt(val) {
		return format_currency(val || 0, frappe.boot.sysdefaults.currency || "INR").replace(/\s+,/g, ',');
	}
	function fmtv(val) {
		val = parseFloat(val) || 0;
		let c = val > 0 ? 'variance-positive' : val < 0 ? 'variance-negative' : 'variance-zero';
		return `<span class="${c}">${val.toFixed(2)}%</span>`;
	}

	// Render a 3-cell Act/Plan/Var block
	function apv_cells(d, cls) {
		d = d || { actual: 0, planned: 0, variance: 0 };
		cls = cls || '';
		return `<td class="${cls}">${fmt(d.actual)}</td><td class="${cls}">${fmt(d.planned)}</td><td class="${cls}">${fmtv(d.variance)}</td>`;
	}

	// Render sub-header row for Act/Plan/Var
	function apv_sub(row, cls) {
		cls = cls || '';
		row.append(`<th class="sub-header ${cls}">Actual</th><th class="sub-header ${cls}">Planned</th><th class="sub-header ${cls}">Var (%)</th>`);
	}

	function render(res) {
		container.empty();
		if (res.view === "yearly") {
			render_bu_yearly(res);
		} else {
			render_temporal(res);
		}
	}

	function make_card(title, badge) {
		let card = $(`
			<div class="mis-container"><div class="mis-table-card">
				<div class="mis-table-title">${title} <span class="fy-badge">${badge}</span></div>
				<div class="mis-table-wrapper"><table class="mis-table"></table></div>
			</div></div>
		`).appendTo(container);
		return card;
	}

	function get_bu_columns(bus) {
		let cols = bus.map(b => ({ id: b.name, title: b.bu_name || b.name, is_gt: false }));
		cols.push({ id: 'Grand Total', title: 'Grand Total', is_gt: true });
		return cols;
	}

	// ═══════════════════════════════════════════
	// Case 1: Both unchecked — BU-wise yearly
	// ═══════════════════════════════════════════
	function render_bu_yearly(res) {
		let { bus, particulars, data } = res;
		let bu_cols = get_bu_columns(bus);
		let card = make_card('Management Information System', fiscal_year.get_value());
		let table = card.find('.mis-table');
		let thead = $('<thead>').appendTo(table);

		// Row 1: Particulars | BU1 (3) | BU2 (3) | ... | Grand Total (3)
		let h1 = $('<tr>').appendTo(thead);
		h1.append('<th class="particulars-header" rowspan="2">Particulars</th>');
		bu_cols.forEach((b, i) => {
			let cls = b.is_gt ? 'grand-total-header' : (i === 0 ? 'bu-group-header bu-separator-header' : 'bu-group-header');
			let title = b.is_gt ? 'Grand Total (FY)' : b.title;
			h1.append(`<th colspan="3" class="${cls}"><span class="sticky-header-label">${title}</span></th>`);
		});

		// Row 2: sub-headers
		let h2 = $('<tr>').appendTo(thead);
		bu_cols.forEach((b, i) => {
			let cls = b.is_gt ? 'grand-total-sub' : (i === 0 ? 'bu-separator-header' : '');
			apv_sub(h2, cls);
		});

		let tbody = $('<tbody>').appendTo(table);
		particulars.forEach(p => {
			let row = $('<tr>').appendTo(tbody);
			row.append(`<td class="particular-cell">${p}</td>`);
			let pd = data[p] || {};
			bu_cols.forEach((b, i) => {
				let d = pd[b.id] || { actual: 0, planned: 0, variance: 0 };
				let cls = b.is_gt ? 'grand-total-cell' : (i === 0 ? 'bu-separator' : '');
				row.append(apv_cells(d, cls));
			});
		});
	}

	// ═══════════════════════════════════════════
	// Cases 2,3,4: Temporal views (Period at top)
	// ═══════════════════════════════════════════
	function render_temporal(res) {
		let { bus, particulars, months, quarters, data } = res;
		let sm = res.show_monthly, sq = res.show_quarterly;
		let bu_cols = get_bu_columns(bus);

		let badge = sm && sq ? 'Monthly + Quarterly' : sm ? 'Monthly' : 'Quarterly';
		let card = make_card('Management Information System', `${fiscal_year.get_value()} — ${badge}`);
		let table = card.find('.mis-table');
		let thead = $('<thead>').appendTo(table);
		let tbody = $('<tbody>').appendTo(table);

		if (sm && sq) {
			build_both_period(thead, tbody, bu_cols, months, quarters, particulars, data);
		} else if (sq) {
			build_qonly_period(thead, tbody, bu_cols, quarters, particulars, data);
		} else {
			build_monly_period(thead, tbody, bu_cols, months, particulars, data);
		}
	}

	// Helper for short period tag
	function get_short_label(lbl) {
		if (!lbl) return '';
		return lbl.split(' ')[0]; // e.g. "Apr 2025" -> "Apr", "Q1" -> "Q1"
	}

	// ═══════════════════════════════════════════
	// Case 2: Monthly only — Month at top
	// ═══════════════════════════════════════════
	function build_monly_period(thead, tbody, bu_cols, months, particulars, data) {
		let per_colspan = bu_cols.length * 3;

		// Row 1: Month labels
		let h1 = $('<tr>').appendTo(thead);
		h1.append('<th class="particulars-header" rowspan="3">Particulars</th>');
		months.forEach(m => {
			h1.append(`<th colspan="${per_colspan}" class="month-group-header"><span class="sticky-header-label">${m.label}</span></th>`);
		});
		h1.append(`<th colspan="${per_colspan}" class="grand-total-header"><span class="sticky-header-label">Full Year</span></th>`);

		// Row 2: BU headers under each Month
		let h2 = $('<tr>').appendTo(thead);
		let period_info = months.map(m => ({ key: m.key, tag: get_short_label(m.label) })).concat([{ key: "FY", tag: "FY" }]);

		period_info.forEach(pinfo => {
			bu_cols.forEach((b, i) => {
				let cls = b.is_gt ? 'grand-total-sub' : (i === 0 ? 'bu-group-header bu-separator-header' : 'bu-group-header');
				let title = b.is_gt ? `Grand Total (${pinfo.tag})` : b.title;
				h2.append(`<th colspan="3" class="${cls}"><span class="sticky-header-label">${title}</span></th>`);
			});
		});

		// Row 3: Act/Plan/Var sub-headers
		let h3 = $('<tr>').appendTo(thead);
		let period_keys = period_info.map(p => p.key);
		period_keys.forEach(() => {
			bu_cols.forEach((b, i) => {
				let cls = b.is_gt ? 'grand-total-sub' : (i === 0 ? 'bu-separator-header' : '');
				apv_sub(h3, cls);
			});
		});

		// Body
		particulars.forEach(p => {
			let pd = data[p] || {};
			let row = $('<tr>').appendTo(tbody);
			row.append(`<td class="particular-cell">${p}</td>`);
			period_keys.forEach(pk => {
				bu_cols.forEach((b, i) => {
					let bu_d = (pd[b.id] || {})[pk] || { actual: 0, planned: 0, variance: 0 };
					let cls = b.is_gt ? 'grand-total-cell' : (i === 0 ? 'bu-separator' : '');
					row.append(apv_cells(bu_d, cls));
				});
			});
		});
	}

	// ═══════════════════════════════════════════
	// Case 3: Quarterly only — Quarter at top
	// ═══════════════════════════════════════════
	function build_qonly_period(thead, tbody, bu_cols, quarters, particulars, data) {
		let per_colspan = bu_cols.length * 3;
		let period_info = quarters.map(q => ({ key: q.key, tag: q.label })).concat([{ key: "FY", tag: "FY" }]);

		// Row 1: Quarter labels
		let h1 = $('<tr>').appendTo(thead);
		h1.append('<th class="particulars-header" rowspan="3">Particulars</th>');
		quarters.forEach(q => {
			h1.append(`<th colspan="${per_colspan}" class="quarter-header"><span class="sticky-header-label">${q.label}</span></th>`);
		});
		h1.append(`<th colspan="${per_colspan}" class="grand-total-header"><span class="sticky-header-label">Full Year</span></th>`);

		// Row 2: BU headers under each Quarter
		let h2 = $('<tr>').appendTo(thead);
		period_info.forEach(pinfo => {
			bu_cols.forEach((b, i) => {
				let cls = b.is_gt ? 'grand-total-sub' : (i === 0 ? 'bu-group-header bu-separator-header' : 'bu-group-header');
				let title = b.is_gt ? `Grand Total (${pinfo.tag})` : b.title;
				h2.append(`<th colspan="3" class="${cls}"><span class="sticky-header-label">${title}</span></th>`);
			});
		});

		// Row 3: Act/Plan/Var sub-headers
		let h3 = $('<tr>').appendTo(thead);
		let period_keys = period_info.map(p => p.key);
		period_keys.forEach(() => {
			bu_cols.forEach((b, i) => {
				let cls = b.is_gt ? 'grand-total-sub' : (i === 0 ? 'bu-separator-header' : '');
				apv_sub(h3, cls);
			});
		});

		// Body
		particulars.forEach(p => {
			let pd = data[p] || {};
			let row = $('<tr>').appendTo(tbody);
			row.append(`<td class="particular-cell">${p}</td>`);
			period_keys.forEach(pk => {
				bu_cols.forEach((b, i) => {
					let bu_d = (pd[b.id] || {})[pk] || { actual: 0, planned: 0, variance: 0 };
					let cls = b.is_gt ? 'grand-total-cell' : (i === 0 ? 'bu-separator' : '');
					row.append(apv_cells(bu_d, cls));
				});
			});
		});
	}

	// ═══════════════════════════════════════════
	// Case 4: Both checked — Quarter -> Month -> BU
	// ═══════════════════════════════════════════
	function build_both_period(thead, tbody, bu_cols, months, quarters, particulars, data) {
		let bu_per_colspan = bu_cols.length * 3;

		let all_items = [];
		quarters.forEach(q => {
			q.month_keys.forEach(mk => {
				let m = months.find(x => x.key === mk);
				all_items.push({ key: mk, label: m ? m.label : mk, tag: get_short_label(m ? m.label : mk), q_key: q.key });
			});
			all_items.push({ key: q.key, label: `Total (${q.label})`, tag: q.label, q_key: q.key, is_q_total: true });
		});

		// Row 1: Top Quarter headers + Full Year
		let h1 = $('<tr>').appendTo(thead);
		h1.append('<th class="particulars-header" rowspan="4">Particulars</th>');
		quarters.forEach(q => {
			let q_cols_count = (q.month_keys.length + 1) * bu_per_colspan;
			h1.append(`<th colspan="${q_cols_count}" class="quarter-header"><span class="sticky-header-label">${q.label}</span></th>`);
		});
		h1.append(`<th colspan="${bu_per_colspan}" class="grand-total-header" rowspan="2"><span class="sticky-header-label">Full Year</span></th>`);

		// Row 2: Month / Q Total headers
		let h2 = $('<tr>').appendTo(thead);
		quarters.forEach(q => {
			q.month_keys.forEach(mk => {
				let m = months.find(x => x.key === mk);
				h2.append(`<th colspan="${bu_per_colspan}" class="month-group-header"><span class="sticky-header-label">${m ? m.label : mk}</span></th>`);
			});
			h2.append(`<th colspan="${bu_per_colspan}" class="sub-header quarter-total-label"><span class="sticky-header-label">Total (${q.label})</span></th>`);
		});

		// Row 3: BU headers under each column group
		let h3 = $('<tr>').appendTo(thead);
		let all_period_info = all_items.map(x => ({ key: x.key, tag: x.tag })).concat([{ key: "FY", tag: "FY" }]);
		all_period_info.forEach(pinfo => {
			bu_cols.forEach((b, i) => {
				let cls = b.is_gt ? 'grand-total-sub' : (i === 0 ? 'bu-group-header bu-separator-header' : 'bu-group-header');
				let title = b.is_gt ? `Grand Total (${pinfo.tag})` : b.title;
				h3.append(`<th colspan="3" class="${cls}"><span class="sticky-header-label">${title}</span></th>`);
			});
		});

		// Row 4: Act/Plan/Var sub-headers
		let h4 = $('<tr>').appendTo(thead);
		let all_period_keys = all_period_info.map(x => x.key);
		all_period_keys.forEach(() => {
			bu_cols.forEach((b, i) => {
				let cls = b.is_gt ? 'grand-total-sub' : (i === 0 ? 'bu-separator-header' : '');
				apv_sub(h4, cls);
			});
		});

		// Body
		particulars.forEach(p => {
			let pd = data[p] || {};
			let row = $('<tr>').appendTo(tbody);
			row.append(`<td class="particular-cell">${p}</td>`);
			all_period_keys.forEach(pk => {
				bu_cols.forEach((b, i) => {
					let bu_d = (pd[b.id] || {})[pk] || { actual: 0, planned: 0, variance: 0 };
					let cls = b.is_gt ? 'grand-total-cell' : (i === 0 ? 'bu-separator' : '');
					row.append(apv_cells(bu_d, cls));
				});
			});
		});
	}
};