# Financial MIS Dashboard - Technical Architecture & Business Logic

This document describes the technical implementation, data pipeline, financial reporting engine integration, target disbursal calculations, and frontend table rendering matrix for the **Management Information System (MIS)** dashboard.

---

## 📁 File Structure

Location: `/home/jeeluat/apps/mis/mis/mis/page/mis/`

| File | Role | Description |
| :--- | :--- | :--- |
| `mis.py` | Python Backend API | Fetches financial data, deduplicates accounts, disburses targets, computes formulas, and aggregates BU figures. |
| `mis.js` | JavaScript Frontend | Manages page UI, handles user input, builds multi-level dynamic header tables, and manages Excel export. |
| `mis.css` | CSS Styling | Provides matrix styling, sticky headers/first column, zebra striping, variance badges, and media print layout. |
| `mis.json` | Page Metadata | Frappe DocType page configuration file. |
| `README.md` | Logic Documentation | Comprehensive reference documentation of the MIS module. |

---

## ⚙️ Backend Logic (`mis.py`)

### 1. ERPNext Financial Engine Integration
* Data is fetched using native ERPNext financial reporting methods from `erpnext.accounts.report.financial_statements`:
  * `get_period_list()`: Generates period boundaries for Monthly, Quarterly, and Yearly views.
  * `get_data()`: Queries general ledger entries for Income (Credit-based) and Expense (Debit-based) categories filtered by company and BU cost centers.

### 2. Business Unit (BU) Discovery
* Queries all `Bu Master` documents where `cost_center` is specified.
* Supports both leaf Business Units and parent Group Business Units (e.g. *Mantra*).

### 3. Target Account Deduplication (`_get_leaf_accounts`)
* **Problem Solved:** When both a parent group account (e.g., `Direct Expenses - MSIPL`) and its child group account (e.g., `Stock Expenses - MSIPL`) are added to a `Target Ledger Map`, standard queries count child balances twice.
* **Solution:** `_get_leaf_accounts()` resolves all mapped accounts into their unique leaf child accounts (`is_group = 0`) using left (`lft`) and right (`rgt`) nested set boundaries.

```python
def _get_leaf_accounts(account_list):
    leaf_accounts = set()
    for acc in account_list:
        acc_info = frappe.db.get_value("Account", acc, ["is_group", "lft", "rgt"], as_dict=True)
        if acc_info and acc_info.is_group:
            children = frappe.db.get_all(
                "Account",
                filters={"lft": (">=", acc_info.lft), "rgt": ("<=", acc_info.rgt), "is_group": 0},
                pluck="name"
            )
            leaf_accounts.update(children)
        else:
            leaf_accounts.add(acc)
    return leaf_accounts
```

### 4. Target Disbursal Rules
* Target amounts defined in `Target Ledger Map` (`lm.amount`) are treated as **ANNUAL targets**.
* **Monthly Planned Target:** $\text{Annual Target} \div \text{Total FY Months}$ (usually 12).
* **Quarterly Planned Target:** $\text{Monthly Planned Target} \times 3$.
* **Full Year Planned Target:** Sum across all months / annual target.
* **Variance %:** Calculated as:
  $$\text{Variance (\%)} = \frac{\text{Actual} - \text{Planned}}{\text{Planned}} \times 100$$

### 5. Derived & Calculated Particular Formulas (`evaluate_calculated_particular`)
Calculated Particulars are evaluated dynamically using dependency logic:

| Particular | Formula |
| :--- | :--- |
| **Gross Profit** | $\text{Revenue} - \text{Cost of goods sold}$ |
| **Gross Profit Margin (%)** | $(\text{Gross Profit} \div \text{Revenue}) \times 100$ |
| **EBITDA** | $\text{Gross Profit} - (\text{Employee Expense} + \text{Software Expense} + \text{Travel Expense} + \text{Marketing Expense} + \text{Other operating expense})$ |
| **Profit Before Tax** | $\text{EBITDA} - (\text{Depreciation} + \text{Interest Expense})$ |

### 6. Grand Total Aggregation
* For every period key (e.g., `apr_2025`, `Q1`, `FY`), a pseudo-BU `"Grand Total"` is constructed by summing actuals and planned targets across all Business Units.

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
* Generates an HTML blob with MIME type `application/vnd.ms-excel`.
* Preserves multi-tier `rowspan` and `colspan` table headers, cell borders, currency formatting, and green/red variance text styling when opened in Microsoft Excel.

---

## 🛠️ Adding New Particulars Guide

### Adding a Standard Ledger-Mapped Particular
1. Create a new record in the **Particulars** doctype (e.g. *"Marketing Expense"*).
2. Create a **Target Ledger Map** entry linking the Particular to the relevant BU and GL accounts.
3. **No code updates required.** The dashboard will automatically fetch GL actuals, disburse targets, and compute variance.

### Adding a Derived Formula Particular
1. Create the Particular name in **Particulars** doctype.
2. Add its mathematical relationship inside `evaluate_calculated_particular()` in `mis.py`.
