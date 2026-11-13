"""
Database initialization and Google Sheets migration seeder for Sumiyuru Stall ERP.
Enforces strict relational isolation, foreign keys, and WAL journal mode.
"""

import json
import os
import re
import sqlite3
from typing import Any, Dict, List, Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "sumiyuru.db")


def get_db_connection() -> sqlite3.Connection:
    """Creates an optimized SQLite connection with foreign keys and WAL mode."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def clean_number(val: Any) -> float:
    """Cleans currency strings like 'Rs. 17,770', '-Rs. 30', '93.0%' into float."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s or s in ("—", "-", "None"):
        return 0.0
    is_neg = "-" in s
    # Strip prefix 'Rs.' or 'Rs' or 'rs'
    s = re.sub(r'(?i)rs\.?\s*', '', s)
    s = s.replace(",", "").replace("%", "").strip()
    # Keep only digits and decimal point
    s = re.sub(r"[^\d.]", "", s)
    if not s:
        return 0.0
    try:
        f = float(s)
        return -f if is_neg else f
    except ValueError:
        return 0.0


def init_db() -> None:
    """Executes schema DDL to create normalized tables."""
    conn = get_db_connection()
    with conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS suppliers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            default_settlement TEXT NOT NULL DEFAULT 'Morning_Cash',
            contact_phone TEXT,
            notes TEXT,
            current_debt REAL DEFAULT 0.0
        );

        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
            settlement_type TEXT NOT NULL,
            unit_cost REAL NOT NULL,
            selling_price REAL NOT NULL,
            category TEXT DEFAULT 'Short Eats',
            is_active INTEGER DEFAULT 1,
            is_returnable INTEGER DEFAULT 0,
            par_weekday REAL DEFAULT 15.0,
            par_weekend REAL DEFAULT 20.0,
            par_holiday REAL DEFAULT 20.0
        );

        CREATE TABLE IF NOT EXISTS daily_shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'Active',
            till_float REAL DEFAULT 5000.0,
            cashier_name TEXT DEFAULT 'Owner',
            total_gross_revenue REAL DEFAULT 0.0,
            total_cogs REAL DEFAULT 0.0,
            actual_till_cash_in REAL DEFAULT 0.0,
            till_variance REAL DEFAULT 0.0,
            morning_suppliers_out REAL DEFAULT 0.0,
            helper_wage_out REAL DEFAULT 0.0,
            other_purchases_out REAL DEFAULT 0.0,
            daily_net_to_reserve REAL DEFAULT 0.0,
            master_reserve_balance REAL DEFAULT 0.0,
            kitchen_cogs_accrued REAL DEFAULT 0.0,
            coffee_cogs_accrued REAL DEFAULT 0.0,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS shift_sales_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shift_id INTEGER NOT NULL REFERENCES daily_shifts(id) ON DELETE CASCADE,
            item_id INTEGER NOT NULL REFERENCES items(id),
            start_qty INTEGER NOT NULL DEFAULT 0,
            leftover_qty INTEGER NOT NULL DEFAULT 0,
            sold_qty INTEGER NOT NULL DEFAULT 0,
            unit_cost REAL NOT NULL,
            selling_price REAL NOT NULL,
            gross_revenue REAL NOT NULL,
            total_cogs REAL NOT NULL,
            notes TEXT
        );

        CREATE TABLE IF NOT EXISTS cash_envelope_handovers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            cycle_number INTEGER NOT NULL,
            handover_to TEXT NOT NULL,
            amount REAL NOT NULL,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS inventory_par_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_name TEXT UNIQUE NOT NULL,
            supplier_name TEXT NOT NULL,
            avg_daily_sold REAL,
            peak_sold REAL,
            sell_through_pct REAL,
            mon_wed_target TEXT,
            thu_sat_target TEXT,
            sun_poya_target TEXT,
            action_signal TEXT
        );

        CREATE TABLE IF NOT EXISTS operational_playbook (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            priority TEXT NOT NULL,
            category TEXT NOT NULL,
            rule_description TEXT NOT NULL,
            target_impact TEXT NOT NULL,
            status TEXT DEFAULT 'Active'
        );

        CREATE TABLE IF NOT EXISTS catering_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            event_date TEXT NOT NULL,
            event_time TEXT,
            event_type TEXT DEFAULT 'General Catering',
            pax_count INTEGER NOT NULL DEFAULT 50,
            menu_description TEXT NOT NULL,
            price_per_pax REAL NOT NULL,
            total_amount REAL NOT NULL,
            advance_paid REAL DEFAULT 0.0,
            order_status TEXT DEFAULT 'Inquiry',
            delivery_address TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS supplier_expenses_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            supplier_name TEXT NOT NULL,
            category TEXT NOT NULL,
            amount REAL NOT NULL,
            payment_source TEXT NOT NULL,
            receipt_note TEXT,
            image_path TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
        # Safe column migration for existing tables
        cursor = conn.execute("PRAGMA table_info(supplier_expenses_ledger);")
        columns = [row["name"] for row in cursor.fetchall()]
        if "image_path" not in columns:
            conn.execute("ALTER TABLE supplier_expenses_ledger ADD COLUMN image_path TEXT;")
    conn.close()
    print("Database schema successfully verified.")


def seed_from_sheets_json() -> None:
    """Migrates all raw sheets JSON data into relational tables."""
    raw_dir = os.path.join(os.path.dirname(__file__), "data", "raw")
    conn = get_db_connection()

    with conn:
        # 1. Suppliers and Items from Unit_Economics
        ue_path = os.path.join(raw_dir, "Unit_Economics.json")
        supplier_map = {}
        if os.path.exists(ue_path):
            with open(ue_path, "r", encoding="utf-8") as f:
                ue_data = json.load(f)
            # Row 0 is header: ['Item_ID', 'Supplier', 'Settlement_Type', 'Unit_Cost', 'Selling_Price', 'Unit_Margin']
            for row in ue_data[1:]:
                if not row or not row[0]:
                    continue
                item_name = str(row[0]).strip()
                supplier_name = str(row[1]).strip() if len(row) > 1 and row[1] else "General"
                settlement = str(row[2]).strip() if len(row) > 2 and row[2] else "Morning_Cash"
                unit_cost = clean_number(row[3]) if len(row) > 3 else 0.0
                selling_price = clean_number(row[4]) if len(row) > 4 else 0.0

                if supplier_name not in supplier_map:
                    cursor = conn.execute(
                        "INSERT OR IGNORE INTO suppliers (name, default_settlement) VALUES (?, ?)",
                        (supplier_name, settlement)
                    )
                    row_sup = conn.execute("SELECT id FROM suppliers WHERE name = ?", (supplier_name,)).fetchone()
                    supplier_map[supplier_name] = row_sup["id"]

                sup_id = supplier_map[supplier_name]

                # Categorize item
                category = "Short Eats"
                if "Rice" in item_name or "Curry" in item_name or "Chicken Leg" in item_name:
                    category = "Rice & Kitchen Meals"
                elif "Bread" in item_name or "Paan" in item_name or "Buns" in item_name:
                    category = "Bakery"
                elif "Coffee" in item_name or "Tea" in item_name:
                    category = "Beverages"
                elif "Dosa" in item_name or "Parata" in item_name or "String Hoppers" in item_name:
                    category = "Dinner Specialties"

                is_returnable = 1 if supplier_name in ("Delish", "Nishan") and "Buns" in item_name else 0

                conn.execute("""
                    INSERT INTO items 
                    (name, supplier_id, settlement_type, unit_cost, selling_price, category, is_returnable)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        supplier_id = excluded.supplier_id,
                        settlement_type = excluded.settlement_type,
                        unit_cost = excluded.unit_cost,
                        selling_price = excluded.selling_price,
                        category = excluded.category,
                        is_returnable = excluded.is_returnable
                """, (item_name, sup_id, settlement, unit_cost, selling_price, category, is_returnable))

        # Build item name -> id lookup
        items_cursor = conn.execute("SELECT id, name, unit_cost, selling_price FROM items")
        item_lookup = {r["name"]: r for r in items_cursor.fetchall()}

        # 2. Daily Cash Commit Log -> daily_shifts table
        dcl_path = os.path.join(raw_dir, "Daily_Cash_Commit_Log.json")
        shift_id_map = {}
        if os.path.exists(dcl_path):
            with open(dcl_path, "r", encoding="utf-8") as f:
                dcl_data = json.load(f)
            # Header: ['Date', 'Logged Sales Rev', 'Actual Till Cash In', 'Till Variance', 'Morning Suppliers Out',
            #          'Helper Wage Set-Aside', 'Other Purchases Out', 'Daily Net to Reserve', 'Master Reserve Balance',
            #          'Kitchen COGS Accrued', 'Coffee COGS Accrued', 'Commit Notes']
            cycle_num = 1
            for row in dcl_data[1:]:
                if not row or not row[0]:
                    continue
                date_str = str(row[0]).strip()
                
                # Check for Handover / Reset row e.g. '2026-11-02 (Sun Reset)' or '2026-11-08 (Sun Reset)'
                if "Reset" in date_str:
                    clean_date = date_str.split()[0]
                    handover_amt = clean_number(row[6]) # 'Other Purchases Out' or negative net to reserve
                    if handover_amt == 0.0:
                        handover_amt = abs(clean_number(row[7]))
                    notes = str(row[11]) if len(row) > 11 else "Reserve handover"
                    conn.execute("""
                        INSERT INTO cash_envelope_handovers (date, cycle_number, handover_to, amount, notes)
                        VALUES (?, ?, 'Dad (Owner Reserve)', ?, ?)
                    """, (clean_date, cycle_num, handover_amt, notes))
                    cycle_num += 1
                    continue
                
                if "CYCLE" in date_str or "TOTAL" in date_str:
                    continue

                logged_rev = clean_number(row[1]) if len(row) > 1 else 0.0
                actual_cash = clean_number(row[2]) if len(row) > 2 else 0.0
                variance = clean_number(row[3]) if len(row) > 3 else 0.0
                morning_sup = clean_number(row[4]) if len(row) > 4 else 0.0
                wage_out = clean_number(row[5]) if len(row) > 5 else 0.0
                other_out = clean_number(row[6]) if len(row) > 6 else 0.0
                net_reserve = clean_number(row[7]) if len(row) > 7 else 0.0
                reserve_bal = clean_number(row[8]) if len(row) > 8 else 0.0
                kitchen_cogs = clean_number(row[9]) if len(row) > 9 else 0.0
                coffee_cogs = clean_number(row[10]) if len(row) > 10 else 0.0
                notes = str(row[11]).strip() if len(row) > 11 else ""

                status = "Active"
                if logged_rev == 0.0:
                    status = "Closed"
                    if "rain" in notes.lower():
                        status = "Closed_Rain"
                    elif "event" in notes.lower():
                        status = "Closed_Event"

                cur = conn.execute("""
                    INSERT INTO daily_shifts (
                        date, status, total_gross_revenue, actual_till_cash_in, till_variance,
                        morning_suppliers_out, helper_wage_out, other_purchases_out,
                        daily_net_to_reserve, master_reserve_balance, kitchen_cogs_accrued,
                        coffee_cogs_accrued, notes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(date) DO UPDATE SET
                        status = excluded.status,
                        total_gross_revenue = excluded.total_gross_revenue,
                        actual_till_cash_in = excluded.actual_till_cash_in,
                        till_variance = excluded.till_variance,
                        morning_suppliers_out = excluded.morning_suppliers_out,
                        helper_wage_out = excluded.helper_wage_out,
                        other_purchases_out = excluded.other_purchases_out,
                        daily_net_to_reserve = excluded.daily_net_to_reserve,
                        master_reserve_balance = excluded.master_reserve_balance,
                        kitchen_cogs_accrued = excluded.kitchen_cogs_accrued,
                        coffee_cogs_accrued = excluded.coffee_cogs_accrued,
                        notes = excluded.notes
                """, (
                    date_str, status, logged_rev, actual_cash, variance,
                    morning_sup, wage_out, other_out,
                    net_reserve, reserve_bal, kitchen_cogs,
                    coffee_cogs, notes
                ))
                shift_row = conn.execute("SELECT id FROM daily_shifts WHERE date = ?", (date_str,)).fetchone()
                shift_id_map[date_str] = shift_row["id"]

                # If other_purchases_out > 0, log an expense entry
                if other_out > 0:
                    conn.execute("""
                        INSERT INTO supplier_expenses_ledger (date, supplier_name, category, amount, payment_source, receipt_note)
                        VALUES (?, 'Operational / Store Restock', 'Supplies & Expenses', ?, 'Master Reserve', ?)
                    """, (date_str, other_out, notes))

        # 3. Daily Sales Log -> shift_sales_items
        dsl_path = os.path.join(raw_dir, "Daily_Sales_Log.json")
        if os.path.exists(dsl_path):
            with open(dsl_path, "r", encoding="utf-8") as f:
                dsl_data = json.load(f)
            # Header: ['Date', 'Item_ID', 'Start_Qty', 'Leftover_Qty', 'Sold_Qty', 'Supplier', 'Settlement_Type', 'Unit_Cost', 'Selling_Price', 'Gross_Revenue', 'Total_COGS']
            for row in dsl_data[1:]:
                if not row or not row[0]:
                    continue
                date_str = str(row[0]).strip()
                item_name = str(row[1]).strip()
                if item_name not in item_lookup:
                    # Dynamically add if new
                    sup_name = str(row[5]).strip() if len(row) > 5 else "General"
                    if sup_name not in supplier_map:
                        conn.execute("INSERT OR IGNORE INTO suppliers (name) VALUES (?)", (sup_name,))
                        sup_id = conn.execute("SELECT id FROM suppliers WHERE name = ?", (sup_name,)).fetchone()["id"]
                        supplier_map[sup_name] = sup_id
                    else:
                        sup_id = supplier_map[sup_name]

                    u_cost = clean_number(row[7]) if len(row) > 7 else 0.0
                    s_price = clean_number(row[8]) if len(row) > 8 else 0.0
                    conn.execute("""
                        INSERT OR IGNORE INTO items (name, supplier_id, settlement_type, unit_cost, selling_price)
                        VALUES (?, ?, ?, ?, ?)
                    """, (item_name, sup_id, row[6] if len(row) > 6 else 'Morning_Cash', u_cost, s_price))
                    new_item = conn.execute("SELECT id, name, unit_cost, selling_price FROM items WHERE name = ?", (item_name,)).fetchone()
                    item_lookup[item_name] = new_item

                item_info = item_lookup[item_name]
                item_id = item_info["id"]

                # Ensure shift exists
                if date_str not in shift_id_map:
                    conn.execute("INSERT OR IGNORE INTO daily_shifts (date, status) VALUES (?, 'Active')", (date_str,))
                    shift_row = conn.execute("SELECT id FROM daily_shifts WHERE date = ?", (date_str,)).fetchone()
                    shift_id_map[date_str] = shift_row["id"]

                shift_id = shift_id_map[date_str]
                start_qty = int(clean_number(row[2])) if len(row) > 2 else 0
                leftover_qty = int(clean_number(row[3])) if len(row) > 3 else 0
                sold_qty = int(clean_number(row[4])) if len(row) > 4 else (start_qty - leftover_qty)
                unit_cost = clean_number(row[7]) if len(row) > 7 else float(item_info["unit_cost"])
                selling_price = clean_number(row[8]) if len(row) > 8 else float(item_info["selling_price"])
                gross_rev = clean_number(row[9]) if len(row) > 9 else (sold_qty * selling_price)
                total_cogs = clean_number(row[10]) if len(row) > 10 else (sold_qty * unit_cost)

                conn.execute("""
                    INSERT INTO shift_sales_items (
                        shift_id, item_id, start_qty, leftover_qty, sold_qty,
                        unit_cost, selling_price, gross_revenue, total_cogs
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    shift_id, item_id, start_qty, leftover_qty, sold_qty,
                    unit_cost, selling_price, gross_rev, total_cogs
                ))

            # Recalculate total_cogs for all shifts
            conn.execute("""
                UPDATE daily_shifts 
                SET total_cogs = (
                    SELECT COALESCE(SUM(total_cogs), 0)
                    FROM shift_sales_items 
                    WHERE shift_sales_items.shift_id = daily_shifts.id
                )
            """)

        # 4. Inventory Optimizer
        inv_path = os.path.join(raw_dir, "Inventory_Optimizer.json")
        if os.path.exists(inv_path):
            with open(inv_path, "r", encoding="utf-8") as f:
                inv_data = json.load(f)
            # Find the header row starting with Item_ID
            start_idx = -1
            for idx, r in enumerate(inv_data):
                if r and any("Item_ID" in str(cell) for cell in r):
                    start_idx = idx
                    break
            if start_idx != -1:
                for row in inv_data[start_idx + 1:]:
                    # Filter empty padding
                    cells = [c for c in row if c and str(c).strip()]
                    if len(cells) < 4:
                        continue
                    item_name = str(cells[0]).strip()
                    sup_name = str(cells[1]).strip()
                    avg_sold = clean_number(cells[2])
                    peak_sold = clean_number(cells[3])
                    sell_thru = clean_number(cells[4]) if len(cells) > 4 else 0.0
                    mon_wed = str(cells[5]).strip() if len(cells) > 5 else "15"
                    thu_sat = str(cells[6]).strip() if len(cells) > 6 else "20"
                    sun_poya = str(cells[7]).strip() if len(cells) > 7 else "20"
                    action_sig = str(cells[8]).strip() if len(cells) > 8 else "Optimal"

                    conn.execute("""
                        INSERT OR REPLACE INTO inventory_par_rules (
                            item_name, supplier_name, avg_daily_sold, peak_sold,
                            sell_through_pct, mon_wed_target, thu_sat_target,
                            sun_poya_target, action_signal
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        item_name, sup_name, avg_sold, peak_sold,
                        sell_thru, mon_wed, thu_sat, sun_poya, action_sig
                    ))

        # 5. Operational Playbook
        play_path = os.path.join(raw_dir, "Operational_Playbook.json")
        if os.path.exists(play_path):
            with open(play_path, "r", encoding="utf-8") as f:
                play_data = json.load(f)
            # Find header with 'Priority'
            start_idx = -1
            for idx, r in enumerate(play_data):
                if r and any("Priority" in str(cell) for cell in r):
                    start_idx = idx
                    break
            if start_idx != -1:
                for row in play_data[start_idx + 1:]:
                    cells = [c for c in row if c and str(c).strip()]
                    if len(cells) >= 4:
                        priority = str(cells[0]).strip()
                        cat = str(cells[1]).strip()
                        desc = str(cells[2]).strip()
                        impact = str(cells[3]).strip()
                        status = str(cells[4]).strip() if len(cells) > 4 else "Active"
                        conn.execute("""
                            INSERT INTO operational_playbook (priority, category, rule_description, target_impact, status)
                            VALUES (?, ?, ?, ?, ?)
                        """, (priority, cat, desc, impact, status))

        # 6. Seed sample Catering Orders for CRM demonstration
        conn.execute("""
            INSERT OR IGNORE INTO catering_orders (
                customer_name, phone, event_date, event_time, event_type,
                pax_count, menu_description, price_per_pax, total_amount, advance_paid, order_status, notes
            ) VALUES 
            ('Dr. Bandara (General Hospital)', '0771234567', '2026-11-20', '12:30 PM', 'Hospital Staff Lunch', 65, 'Mix Fried Rice w/ Leg, Small Cutlet, Mixed Salad, Gravy & Chutney', 650.0, 42250.0, 20000.0, 'Confirmed', 'Hospital Staff Room 3rd Floor. Delivery via stall van at 12:00 PM sharp.'),
            ('Nimal Perera', '0719876543', '2026-11-22', '7:00 PM', 'Birthday Gathering', 40, 'String Hopper Platter, Kiri Hodi, Pol Sambol, Chicken Curry, Dosa & Parata Assortment', 550.0, 22000.0, 10000.0, 'Confirmed', 'Needs 2 warm chafing dishes provided.'),
            ('Samanthi Weerasinghe', '0765551234', '2026-11-28', '11:00 AM', 'Bana / Almsgiving', 100, 'Vegetarian Rice & Curry Premium Package (7 curries, dhal, papadam, curd & treacle)', 700.0, 70000.0, 0.0, 'Inquiry', 'Pending family confirmation on exact guest count by Nov 18.')
        """)

    conn.close()
    print("Database seeding from Google Sheets completed successfully.")


if __name__ == "__main__":
    init_db()
    seed_from_sheets_json()
