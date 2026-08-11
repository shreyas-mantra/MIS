# Financial MIS Dashboard - Technical Architecture & Business Logic

This document describes the technical implementation, data pipeline, financial reporting engine integration, target disbursal calculations, and frontend table rendering matrix for the **Management Information System (MIS)** dashboard.

---

## 📁 File Structure

Location: `/home/jeeluat/apps/mis/mis/mis/page/mis/`

| File | Role | Description |
| :--- | :--- | :--- |
| `mis.py` | Python Backend API | High-performance GL entry aggregation, in-memory account tree expansion, target calculation, formula evaluation, and BU aggregation. |
| `mis.js` | JavaScript Frontend | Manages page UI, handles user filter toggles, builds multi-level dynamic matrix tables, and manages Excel export. |
| `mis.css` | CSS Styling | Provides matrix table styling, sticky column/header layout, variance badges, and print media CSS. |
| `mis.json` | Page Metadata | Frappe DocType page configuration file. |
| `logic.md` | Technical Specs | Comprehensive technical architecture and data dictionary document. |
| `README.md` | Module Documentation | Developer overview and user guide for the MIS reporting module. |

---

## ⚙️ Backend Logic (`mis.py`)

### 1. High-Performance Direct SQL GL Aggregation Engine
* **Problem Solved:** Traditional ERPNext `financial_statements.get_data()` executed 22+ queries per page load using `FORCE INDEX (posting_date_company_index)` across the entire `tabGL Entry` table, causing 100% CPU spikes and 30-60 second page loads.
* **Solution:** Replaced with **1 single indexed SQL query** filtering directly by company, posting date range, target leaf accounts, and BU cost centers:

```python
gl_entries = frappe.db.sql(
    """
    SELECT account, cost_center, posting_date, debit, credit
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
```

### 2. Bulk In-Memory Chart of Accounts & Target Resolution
* **Bulk Account Map:** All accounts are bulk-fetched into an in-memory dictionary.
* **Group Account Expansion:** Group accounts configured in `Target Ledger Map` are expanded into leaf accounts (`is_group = 0`) using left (`lft`) and right (`rgt`) nested set boundaries completely in memory.
* **Parent-Filtered Child Queries:** `Target Account` and `Targets` child rows are filtered by `parent IN (lm_names)` matching the selected `fiscal_year` to eliminate cross-year data pollution and memory overhead.

### 3. Target Ledger Map Schema & Disbursal Logic
Targets are configured in **Target Ledger Map** per Fiscal Year:

* **Field `fiscal_year`:** Links map definition to a specific Fiscal Year.
* **Child Table `Targets`:** Contains month-by-month target amounts for all 12 months (`Apr` to `Mar`).
* **Disbursal Math:**
  * **Monthly Planned Target:** Reads the specific target entered for that month (`Apr`, `May`, ..., `Mar`) in the `Targets` child table.
  * **Quarterly Planned Target:** Sums the 3 monthly planned targets corresponding to that quarter.
  * **Full Year Planned Target:** Sums all 12 monthly targets in the FY.
  * **Variance (%):**
    $$\text{Variance (\%)} = \frac{\text{Actual} - \text{Planned}}{\text{Planned}} \times 100$$

### 4. Record Uniqueness & Client Script Enforcement (`target_ledger_map.py` / `.js`)
* **Uniqueness Rule:** `Target Ledger Map` throws a validation error if a record already exists with the same `(bu, target, fiscal_year)` tuple.
* **12 Months Enforcement:** Client script (`target_ledger_map.js`) and server-side `validate()` automatically pre-populate and enforce all 12 months in financial year order (`Apr` to `Mar`), while setting `cannot_add_rows` and `cannot_delete_rows` on the child table grid.

### 5. Derived & Calculated Particular Formulas (`evaluate_calculated_particular`)
Calculated Particulars are evaluated dynamically using dependency logic:

| Particular | Formula |
| :--- | :--- |
| **Gross Profit** | $\text{Revenue} - \text{Cost of goods sold}$ |
| **Gross Profit Margin (%)** | $(\text{Gross Profit} \div \text{Revenue}) \times 100$ |
| **EBITDA** | $\text{Gross Profit} - (\text{Employee Expense} + \text{Software Expense} + \text{Travel Expense} + \text{Marketing Expense} + \text{Other operating expense})$ |
| **Profit Before Tax** | $\text{EBITDA} - (\text{Depreciation} + \text{Interest Expense})$ |

### 6. Grand Total Aggregation
* For every period key (`apr_2025`, `Q1`, `FY`), a pseudo-BU `"Grand Total"` is constructed by aggregating actuals and planned targets across all Business Units.

---

## 🎨 Frontend Rendering Logic (`mis.js`)

### 1. Matrix Header Hierarchy (Time Period at Top)
The table matrix groups **Time Periods at the top level**, allowing all Business Units to be compared side-by-side:

* **Monthly View (`Show Monthly` checked):**
  $$\text{Month (Apr 2025)} \longrightarrow \text{Business Units (Mantra, Partner Bu, ..., Grand Total)} \longrightarrow [\text{Actual}, \text{Planned}, \text{Var (\%)}]$$

* **Quarterly View (`Show Quarterly` checked):**
  $$\text{Quarter (Q1)} \longrightarrow \text{Business Units (Mantra, Partner Bu, ..., Grand Total)} \longrightarrow [\text{Actual}, \text{Planned}, \text{Var (\%)}]$$

* **Both View (`Show Monthly` & `Show Quarterly` checked):**
  $$\text{Quarter (Q1)} \longrightarrow \text{Month (Apr, May, Jun, Total)} \longrightarrow \text{Business Units} \longrightarrow [\text{Actual}, \text{Planned}, \text{Var (\%)}]$$

* **Yearly View (Both unchecked):**
  $$\text{Business Units (Mantra, Partner Bu, ..., Grand Total)} \longrightarrow [\text{Actual}, \text{Planned}, \text{Var (\%)}]$$

### 2. Excel Export Functionality
* Exports dynamic matrix data as a formatted spreadsheet preserving headers, cell borders, currency formatting, and conditional color styling.

---

## 🛠️ Adding New Particulars Guide

### Adding a Standard Ledger-Mapped Particular
1. Create a new record in the **Particulars** doctype (e.g. *"Marketing Expense"*).
2. Create a **Target Ledger Map** entry linking the Particular, BU, and Fiscal Year, and specify monthly targets in the child table.
3. **No code updates required.** The dashboard will automatically fetch GL actuals, calculate targets, and compute variance.

### Adding a Derived Formula Particular
1. Create the Particular name in **Particulars** doctype.
2. Add its mathematical formula inside `evaluate_calculated_particular()` in `mis.py`.
