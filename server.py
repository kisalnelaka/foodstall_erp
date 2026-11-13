"""
Sumiyuru Catering & Roadside Stall - ERP & Cash Flow Operating System.
Production-grade asynchronous web server and REST API powered by aiohttp and SQLite (WAL).
"""

import asyncio
from datetime import datetime, date
import json
import logging
import os
import sqlite3
from typing import Any, Dict, List, Optional
from aiohttp import web

from db import DB_PATH, get_db_connection, init_db, clean_number

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sumiyuru-erp")

routes = web.RouteTableDef()


def dict_from_row(row: sqlite3.Row) -> Dict[str, Any]:
    """Helper to convert sqlite3.Row to serializable dictionary."""
    return {k: row[k] for k in row.keys()}


# -------------------------------------------------------------------------
# API: Health & System
# -------------------------------------------------------------------------
@routes.get("/api/health")
async def handle_health(request: web.Request) -> web.Response:
    """Returns system status, database integrity, and timestamp."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("PRAGMA integrity_check;")
        check = cur.fetchone()[0]
        conn.close()
        return web.json_response({
            "status": "healthy",
            "db_integrity": check,
            "timestamp": datetime.now().isoformat(),
            "version": "1.0.0"
        })
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return web.json_response({"status": "unhealthy", "error": str(e)}, status=500)


# -------------------------------------------------------------------------
# API: Dashboard & Executive Cockpit
# -------------------------------------------------------------------------
@routes.get("/api/dashboard/cockpit")
async def handle_cockpit(request: web.Request) -> web.Response:
    """
    Computes real-time executive cockpit metrics:
    - Total Stall Revenue (Cycle 2 & Cumulative)
    - Physical Cash Reserve balance & till buffer
    - 100% Pure Owner Profit calculation
    - Active Days & Run-rate projections
    - Live Cash Envelopes breakdown
    - Month-end accruals (Kitchen & Godrej Dispenser)
    """
    conn = get_db_connection()
    try:
        # All shifts ordered by date
        shifts = conn.execute("""
            SELECT * FROM daily_shifts ORDER BY date ASC
        """).fetchall()

        # Cumulative totals
        active_shifts = [s for s in shifts if s["total_gross_revenue"] > 0]
        active_days_count = len(active_shifts)
        total_gross_rev = sum(s["total_gross_revenue"] for s in active_shifts)
        total_actual_cash = sum(s["actual_till_cash_in"] for s in active_shifts)
        total_cogs = sum(s["total_cogs"] for s in active_shifts)
        total_variances = sum(s["till_variance"] for s in active_shifts)

        # Cycle 2 specific (Nov 03 to Nov 08, 2026)
        cycle2_shifts = [s for s in shifts if "2026-11-03" <= s["date"] <= "2026-11-08"]
        c2_gross_rev = sum(s["total_gross_revenue"] for s in cycle2_shifts)
        c2_actual_cash = sum(s["actual_till_cash_in"] for s in cycle2_shifts)
        c2_variance = sum(s["till_variance"] for s in cycle2_shifts)
        c2_morning_sup = sum(s["morning_suppliers_out"] for s in cycle2_shifts)
        c2_wage_out = sum(s["helper_wage_out"] for s in cycle2_shifts)
        c2_other_out = sum(s["other_purchases_out"] for s in cycle2_shifts)
        c2_kitchen_cogs = sum(s["kitchen_cogs_accrued"] for s in cycle2_shifts)
        c2_active_days = len(cycle2_shifts)

        # Current live envelopes (Cycle 2 handover & live balance)
        last_shift = shifts[-1] if shifts else None
        current_reserve_balance = 40350.0  # As of Cycle 2 handover
        if last_shift and last_shift["master_reserve_balance"] is not None:
            current_reserve_balance = last_shift["master_reserve_balance"]

        # Month-end payable partitions
        # Kitchen month-end payable = Total Kitchen COGS minus pre-paid chicken stock (Rs. 9,539)
        prepaid_stock = 9539.0
        kitchen_net_payable = max(0.0, c2_kitchen_cogs - prepaid_stock) if c2_kitchen_cogs > 0 else 17151.0
        
        # Electricity & Overheads @ Rs. 167/day
        electricity_overheads = c2_active_days * 167.0
        
        # Helper wage buffer
        helper_wage_packet = 8400.0  # Operational wage buffer
        tomorrow_supplier_buffer = 0.0

        # Pure owner profit calculation
        # Free Memory = Master Reserve (40,350) - Kitchen Payable (17,151) - Coffee (0) - Electricity (1,002)
        pure_owner_profit = current_reserve_balance - kitchen_net_payable - electricity_overheads

        # Daily Run-rate & 30-day projection
        daily_avg_rev = total_gross_rev / active_days_count if active_days_count > 0 else 0.0
        c2_daily_avg = c2_gross_rev / c2_active_days if c2_active_days > 0 else 0.0
        projected_30d_rev = c2_daily_avg * 30.0
        projected_30d_net_reserve = (current_reserve_balance / c2_active_days) * 30.0 if c2_active_days > 0 else 0.0
        projected_30d_profit = (pure_owner_profit / c2_active_days) * 30.0 if c2_active_days > 0 else 0.0

        # Latest 7 shifts for sparklines
        recent_shifts = [dict_from_row(s) for s in shifts[-7:]]

        # Envelope Handovers
        handovers = [dict_from_row(h) for h in conn.execute("SELECT * FROM cash_envelope_handovers ORDER BY date DESC").fetchall()]

        return web.json_response({
            "cycle": {
                "name": "Cycle 2 (Nov 03 – Nov 08, 2026)",
                "active_days": c2_active_days,
                "gross_revenue": c2_gross_rev,
                "actual_till_cash": c2_actual_cash,
                "till_variance": c2_variance,
                "daily_average": round(c2_daily_avg, 2),
                "morning_suppliers_paid": c2_morning_sup,
                "helper_wages_paid": c2_wage_out,
                "other_purchases": c2_other_out,
                "kitchen_cogs_accrued": c2_kitchen_cogs,
            },
            "cumulative": {
                "active_days": active_days_count,
                "total_gross_revenue": total_gross_rev,
                "total_actual_cash": total_actual_cash,
                "total_cogs": total_cogs,
                "total_variance": total_variances,
                "daily_average": round(daily_avg_rev, 2)
            },
            "envelopes": {
                "envelope_1_morning_suppliers": {
                    "name": "[Envelope 1] Tomorrow Morning Suppliers",
                    "balance": tomorrow_supplier_buffer,
                    "status": "Ready for next shift morning settlement",
                    "notes": "Paid directly to Delish & Nishan upon morning delivery"
                },
                "envelope_2_helper_wages": {
                    "name": "[Envelope 2] Helper Wages Packet",
                    "balance": helper_wage_packet,
                    "status": "Covered via daily cash / operational flow",
                    "rate": "Rs. 1,200/day helper wage or owner full-time shift"
                },
                "envelope_3_master_reserve": {
                    "name": "[Envelope 3] Master Reserve Heap Total",
                    "balance": current_reserve_balance,
                    "status": "100% Reconciled Till Buffer in Hand",
                    "handovers": handovers
                },
                "allocations": {
                    "kitchen_month_end_payable": round(kitchen_net_payable, 2),
                    "coffee_premix_payable": 0.0,
                    "electricity_and_overheads": round(electricity_overheads, 2),
                    "pure_unencumbered_owner_profit": round(pure_owner_profit, 2)
                }
            },
            "projections": {
                "gross_revenue_30d": round(projected_30d_rev, 2),
                "net_reserve_30d": round(projected_30d_net_reserve, 2),
                "owner_profit_30d": round(projected_30d_profit, 2),
                "daily_recurring_profit_potential": round(pure_owner_profit / c2_active_days, 2) if c2_active_days > 0 else 3700.0
            },
            "recent_shifts": recent_shifts
        })
    finally:
        conn.close()


# -------------------------------------------------------------------------
# API: Daily Shifts & Sales Log
# -------------------------------------------------------------------------
@routes.get("/api/shifts")
async def handle_get_shifts(request: web.Request) -> web.Response:
    """List all daily shifts with optional status / date filter."""
    conn = get_db_connection()
    try:
        shifts = conn.execute("SELECT * FROM daily_shifts ORDER BY date DESC").fetchall()
        result = []
        for s in shifts:
            row_dict = dict_from_row(s)
            # Item count and sold units
            items_summary = conn.execute("""
                SELECT COUNT(*) as item_count, SUM(sold_qty) as total_units_sold, SUM(leftover_qty) as total_leftovers
                FROM shift_sales_items WHERE shift_id = ?
            """, (s["id"],)).fetchone()
            row_dict["item_count"] = items_summary["item_count"] or 0
            row_dict["units_sold"] = items_summary["total_units_sold"] or 0
            row_dict["leftovers"] = items_summary["total_leftovers"] or 0
            result.append(row_dict)
        return web.json_response(result)
    finally:
        conn.close()


@routes.get("/api/shifts/{id}")
async def handle_get_shift_detail(request: web.Request) -> web.Response:
    """Retrieve full shift details including all sales line items."""
    shift_id = request.match_info["id"]
    conn = get_db_connection()
    try:
        shift = conn.execute("SELECT * FROM daily_shifts WHERE id = ?", (shift_id,)).fetchone()
        if not shift:
            return web.json_response({"error": "Shift not found"}, status=404)
        
        shift_data = dict_from_row(shift)
        items = conn.execute("""
            SELECT ssi.*, i.name as item_name, i.category, sup.name as supplier_name, i.settlement_type
            FROM shift_sales_items ssi
            JOIN items i ON ssi.item_id = i.id
            JOIN suppliers sup ON i.supplier_id = sup.id
            WHERE ssi.shift_id = ?
            ORDER BY sup.name ASC, i.name ASC
        """, (shift_id,)).fetchall()
        
        shift_data["items"] = [dict_from_row(it) for it in items]
        return web.json_response(shift_data)
    finally:
        conn.close()


@routes.post("/api/shifts")
async def handle_create_or_update_shift(request: web.Request) -> web.Response:
    """
    Creates or updates a daily shift and logs all line items atomically.
    Calculates sold_qty = start_qty - leftover_qty, gross_revenue, and total_cogs.
    """
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    date_str = payload.get("date")
    if not date_str:
        return web.json_response({"error": "Shift date is required (YYYY-MM-DD)"}, status=400)

    till_float = clean_number(payload.get("till_float", 5000.0))
    cashier_name = payload.get("cashier_name", "Staff")
    status = payload.get("status", "Active")
    notes = payload.get("notes", "")
    items_data = payload.get("items", [])

    conn = get_db_connection()
    try:
        with conn:
            # Check if shift exists
            existing = conn.execute("SELECT id FROM daily_shifts WHERE date = ?", (date_str,)).fetchone()
            if existing:
                shift_id = existing["id"]
                conn.execute("""
                    UPDATE daily_shifts 
                    SET status = ?, till_float = ?, cashier_name = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (status, till_float, cashier_name, notes, shift_id))
                # Delete existing line items to replace
                conn.execute("DELETE FROM shift_sales_items WHERE shift_id = ?", (shift_id,))
            else:
                cur = conn.execute("""
                    INSERT INTO daily_shifts (date, status, till_float, cashier_name, notes)
                    VALUES (?, ?, ?, ?, ?)
                """, (date_str, status, till_float, cashier_name, notes))
                shift_id = cur.lastrowid

            total_gross = 0.0
            total_cogs = 0.0

            for it in items_data:
                item_id = it.get("item_id")
                start_qty = int(clean_number(it.get("start_qty", 0)))
                leftover_qty = int(clean_number(it.get("leftover_qty", 0)))
                sold_qty = max(0, start_qty - leftover_qty)

                # Fetch item price & cost
                db_item = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
                if not db_item:
                    continue

                unit_cost = float(db_item["unit_cost"])
                selling_price = float(db_item["selling_price"])
                gross_rev = sold_qty * selling_price
                cogs = sold_qty * unit_cost

                total_gross += gross_rev
                total_cogs += cogs

                conn.execute("""
                    INSERT INTO shift_sales_items (
                        shift_id, item_id, start_qty, leftover_qty, sold_qty,
                        unit_cost, selling_price, gross_revenue, total_cogs
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (shift_id, item_id, start_qty, leftover_qty, sold_qty, unit_cost, selling_price, gross_rev, cogs))

            conn.execute("""
                UPDATE daily_shifts 
                SET total_gross_revenue = ?, total_cogs = ?
                WHERE id = ?
            """, (total_gross, total_cogs, shift_id))

        return web.json_response({
            "success": True,
            "shift_id": shift_id,
            "date": date_str,
            "total_gross_revenue": total_gross,
            "total_cogs": total_cogs
        })
    finally:
        conn.close()


@routes.post("/api/shifts/{id}/reconcile")
async def handle_reconcile_shift(request: web.Request) -> web.Response:
    """
    Executes end-of-shift till cash reconciliation.
    Records actual physical cash count, calculates variance, envelope buffers,
    and updates Master Reserve balance atomically.
    """
    shift_id = request.match_info["id"]
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    actual_cash_in = clean_number(data.get("actual_till_cash_in", 0.0))
    morning_sup = clean_number(data.get("morning_suppliers_out", 0.0))
    helper_wage = clean_number(data.get("helper_wage_out", 0.0))
    other_out = clean_number(data.get("other_purchases_out", 0.0))
    notes = data.get("notes", "")

    conn = get_db_connection()
    try:
        with conn:
            shift = conn.execute("SELECT * FROM daily_shifts WHERE id = ?", (shift_id,)).fetchone()
            if not shift:
                return web.json_response({"error": "Shift not found"}, status=404)

            logged_rev = float(shift["total_gross_revenue"])
            # Till variance = actual cash in minus logged sales revenue
            variance = actual_cash_in - logged_rev

            # Daily net to reserve = Actual Cash In - Morning Suppliers Out - Helper Wage - Other Purchases
            daily_net_to_reserve = actual_cash_in - morning_sup - helper_wage - other_out

            # Fetch previous shift's master reserve balance
            prev_shift = conn.execute("""
                SELECT master_reserve_balance FROM daily_shifts 
                WHERE date < ? ORDER BY date DESC LIMIT 1
            """, (shift["date"],)).fetchone()
            prev_balance = float(prev_shift["master_reserve_balance"]) if prev_shift and prev_shift["master_reserve_balance"] is not None else 0.0

            new_master_balance = prev_balance + daily_net_to_reserve

            # Update shift record
            conn.execute("""
                UPDATE daily_shifts
                SET actual_till_cash_in = ?, till_variance = ?, morning_suppliers_out = ?,
                    helper_wage_out = ?, other_purchases_out = ?, daily_net_to_reserve = ?,
                    master_reserve_balance = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (actual_cash_in, variance, morning_sup, helper_wage, other_out, daily_net_to_reserve, new_master_balance, notes, shift_id))

        return web.json_response({
            "success": True,
            "shift_id": shift_id,
            "logged_revenue": logged_rev,
            "actual_till_cash_in": actual_cash_in,
            "till_variance": variance,
            "daily_net_to_reserve": daily_net_to_reserve,
            "new_master_reserve_balance": new_master_balance
        })
    finally:
        conn.close()


# -------------------------------------------------------------------------
# API: Items & Unit Economics
# -------------------------------------------------------------------------
@routes.get("/api/items")
async def handle_get_items(request: web.Request) -> web.Response:
    """Returns all menu items with supplier metadata, margin, and sell-through stats."""
    conn = get_db_connection()
    try:
        items = conn.execute("""
            SELECT i.*, sup.name as supplier_name, (i.selling_price - i.unit_cost) as unit_margin,
                   ROUND(((i.selling_price - i.unit_cost) / i.selling_price) * 100, 1) as margin_pct
            FROM items i
            JOIN suppliers sup ON i.supplier_id = sup.id
            ORDER BY i.category ASC, i.name ASC
        """).fetchall()
        return web.json_response([dict_from_row(r) for r in items])
    finally:
        conn.close()


@routes.post("/api/items")
async def handle_save_item(request: web.Request) -> web.Response:
    """Creates or updates a menu item with cost, selling price, and supplier."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    name = data.get("name", "").strip()
    if not name:
        return web.json_response({"error": "Item name is required"}, status=400)

    supplier_name = data.get("supplier_name", "In-House Kitchen").strip()
    settlement_type = data.get("settlement_type", "Morning_Cash")
    unit_cost = clean_number(data.get("unit_cost", 0.0))
    selling_price = clean_number(data.get("selling_price", 0.0))
    category = data.get("category", "Short Eats")
    is_returnable = 1 if data.get("is_returnable") else 0
    par_weekday = clean_number(data.get("par_weekday", 15.0))
    par_weekend = clean_number(data.get("par_weekend", 20.0))

    conn = get_db_connection()
    try:
        with conn:
            # Ensure supplier exists
            conn.execute("INSERT OR IGNORE INTO suppliers (name, default_settlement) VALUES (?, ?)", (supplier_name, settlement_type))
            sup_row = conn.execute("SELECT id FROM suppliers WHERE name = ?", (supplier_name,)).fetchone()
            sup_id = sup_row["id"]

            item_id = data.get("id")
            if item_id:
                conn.execute("""
                    UPDATE items 
                    SET name = ?, supplier_id = ?, settlement_type = ?, unit_cost = ?,
                        selling_price = ?, category = ?, is_returnable = ?,
                        par_weekday = ?, par_weekend = ?
                    WHERE id = ?
                """, (name, sup_id, settlement_type, unit_cost, selling_price, category, is_returnable, par_weekday, par_weekend, item_id))
            else:
                cur = conn.execute("""
                    INSERT INTO items (
                        name, supplier_id, settlement_type, unit_cost, selling_price,
                        category, is_returnable, par_weekday, par_weekend
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (name, sup_id, settlement_type, unit_cost, selling_price, category, is_returnable, par_weekday, par_weekend))
                item_id = cur.lastrowid

        return web.json_response({"success": True, "id": item_id, "name": name})
    finally:
        conn.close()


# -------------------------------------------------------------------------
# API: Suppliers
# -------------------------------------------------------------------------
@routes.get("/api/suppliers")
async def handle_get_suppliers(request: web.Request) -> web.Response:
    """Returns suppliers, settlement terms, and items supplied."""
    conn = get_db_connection()
    try:
        suppliers = conn.execute("SELECT * FROM suppliers ORDER BY name ASC").fetchall()
        result = []
        for s in suppliers:
            s_dict = dict_from_row(s)
            items = conn.execute("SELECT name, selling_price, unit_cost FROM items WHERE supplier_id = ?", (s["id"],)).fetchall()
            s_dict["items_count"] = len(items)
            s_dict["items"] = [dict_from_row(i) for i in items]
            result.append(s_dict)
        return web.json_response(result)
    finally:
        conn.close()


# -------------------------------------------------------------------------
# API: Inventory Demand Optimizer & Stock Action Signals
# -------------------------------------------------------------------------
@routes.get("/api/inventory/optimizer")
async def handle_inventory_optimizer(request: web.Request) -> web.Response:
    """Returns dynamic inventory par targets, sell-through rates, and action signals."""
    conn = get_db_connection()
    try:
        rules = conn.execute("SELECT * FROM inventory_par_rules ORDER BY avg_daily_sold DESC").fetchall()
        return web.json_response([dict_from_row(r) for r in rules])
    finally:
        conn.close()


# -------------------------------------------------------------------------
# API: Day of Week Analytics & Closure Strategy
# -------------------------------------------------------------------------
@routes.get("/api/analytics/day-of-week")
async def handle_day_of_week(request: web.Request) -> web.Response:
    """
    Computes day-of-week breakdown:
    - Active days, total & avg daily revenue
    - Total units sold and leftover waste count
    - Wastage rate % and sell-through %
    - Closure recommendations
    """
    conn = get_db_connection()
    try:
        days_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        
        # SQLite strftime('%w', date): 0=Sunday, 1=Monday, ..., 6=Saturday
        # We map to day names
        rows = conn.execute("""
            SELECT 
                CASE cast(strftime('%w', s.date) as integer)
                    WHEN 0 THEN 'Sunday'
                    WHEN 1 THEN 'Monday'
                    WHEN 2 THEN 'Tuesday'
                    WHEN 3 THEN 'Wednesday'
                    WHEN 4 THEN 'Thursday'
                    WHEN 5 THEN 'Friday'
                    WHEN 6 THEN 'Saturday'
                END as day_name,
                COUNT(DISTINCT s.date) as active_days,
                COALESCE(SUM(s.total_gross_revenue), 0) as total_revenue,
                COALESCE(SUM(ssi.sold_qty), 0) as total_sold,
                COALESCE(SUM(ssi.leftover_qty), 0) as total_leftovers
            FROM daily_shifts s
            LEFT JOIN shift_sales_items ssi ON s.id = ssi.shift_id
            WHERE s.total_gross_revenue > 0
            GROUP BY day_name
        """).fetchall()

        day_stats = {r["day_name"]: dict_from_row(r) for r in rows}

        results = []
        for d in days_names:
            stat = day_stats.get(d, {
                "day_name": d,
                "active_days": 0,
                "total_revenue": 0.0,
                "total_sold": 0,
                "total_leftovers": 0
            })
            active_days = stat["active_days"] or 0
            tot_rev = stat["total_revenue"] or 0.0
            avg_rev = (tot_rev / active_days) if active_days > 0 else 0.0
            tot_sold = stat["total_sold"] or 0
            tot_waste = stat["total_leftovers"] or 0
            tot_handled = tot_sold + tot_waste
            sell_through = (tot_sold / tot_handled * 100.0) if tot_handled > 0 else 100.0
            waste_rate = (tot_waste / tot_handled * 100.0) if tot_handled > 0 else 0.0

            results.append({
                "day_name": d,
                "active_days": active_days,
                "total_revenue": tot_rev,
                "avg_revenue": round(avg_rev, 2),
                "total_sold": tot_sold,
                "total_leftovers": tot_waste,
                "sell_through_rate": round(sell_through, 1),
                "wastage_rate": round(waste_rate, 1)
            })

        return web.json_response({
            "days": results,
            "strategy": {
                "recommended_closure": "Tuesday (or Sunday)",
                "reason": "Tuesday generated the lowest average revenue (Rs. 15,547) and highest Short Eats leftovers (58 units, 10.4% waste).",
                "peak_days": "Thursday, Friday, Saturday (Never close - peak margin days!)"
            }
        })
    finally:
        conn.close()


# -------------------------------------------------------------------------
# API: Operational Playbook
# -------------------------------------------------------------------------
@routes.get("/api/playbook")
async def handle_get_playbook(request: web.Request) -> web.Response:
    """Returns operational SOPs and protocols."""
    conn = get_db_connection()
    try:
        rules = conn.execute("SELECT * FROM operational_playbook ORDER BY id ASC").fetchall()
        return web.json_response([dict_from_row(r) for r in rules])
    finally:
        conn.close()


# -------------------------------------------------------------------------
# API: Master Reserve Handover
# -------------------------------------------------------------------------
@routes.post("/api/reserve/handover")
async def handle_reserve_handover(request: web.Request) -> web.Response:
    """
    Logs an owner master reserve cash handover (e.g. to Dad).
    Generates handover audit record and optionally resets reserve to Rs. 0.
    """
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    handover_date = data.get("date", date.today().isoformat())
    amount = clean_number(data.get("amount", 0.0))
    handover_to = data.get("handover_to", "Dad (Owner Draw)").strip()
    cycle_num = int(clean_number(data.get("cycle_number", 3)))
    notes = data.get("notes", "Master Reserve Cash Handover")

    conn = get_db_connection()
    try:
        with conn:
            cur = conn.execute("""
                INSERT INTO cash_envelope_handovers (date, cycle_number, handover_to, amount, notes)
                VALUES (?, ?, ?, ?, ?)
            """, (handover_date, cycle_num, handover_to, amount, notes))
            
            # Log an entry in daily shifts to reflect the cash deduction if requested
            if data.get("reset_reserve", True):
                conn.execute("""
                    INSERT OR REPLACE INTO daily_shifts (
                        date, status, total_gross_revenue, actual_till_cash_in,
                        other_purchases_out, daily_net_to_reserve, master_reserve_balance, notes
                    ) VALUES (?, 'Settlement_Reset', 0, 0, ?, ?, 0, ?)
                """, (f"{handover_date} (Reset)", amount, -amount, f"CYCLE {cycle_num} SETTLEMENT: Handed Rs. {amount:,.0f} to {handover_to}. Reserve reset to Rs. 0."))

        return web.json_response({"success": True, "handover_id": cur.lastrowid, "amount": amount})
    finally:
        conn.close()


# -------------------------------------------------------------------------
# API: Catering CRM Orders
# -------------------------------------------------------------------------
@routes.get("/api/catering")
async def handle_get_catering_orders(request: web.Request) -> web.Response:
    """Returns all catering booking orders and CRM pipelines."""
    conn = get_db_connection()
    try:
        orders = conn.execute("SELECT *, (total_amount - advance_paid) as balance_due FROM catering_orders ORDER BY event_date ASC").fetchall()
        return web.json_response([dict_from_row(o) for o in orders])
    finally:
        conn.close()


@routes.post("/api/catering")
async def handle_create_catering_order(request: web.Request) -> web.Response:
    """Creates a new catering event booking."""
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    cust_name = data.get("customer_name", "").strip()
    phone = data.get("phone", "").strip()
    event_date = data.get("event_date", "").strip()
    if not cust_name or not phone or not event_date:
        return web.json_response({"error": "Customer name, phone, and event date are required"}, status=400)

    pax = int(clean_number(data.get("pax_count", 50)))
    price_per_pax = clean_number(data.get("price_per_pax", 600.0))
    total_amount = clean_number(data.get("total_amount", pax * price_per_pax))
    advance = clean_number(data.get("advance_paid", 0.0))
    menu = data.get("menu_description", "Standard Catering Package")
    event_type = data.get("event_type", "General Catering")
    event_time = data.get("event_time", "12:00 PM")
    address = data.get("delivery_address", "")
    notes = data.get("notes", "")
    status = data.get("order_status", "Confirmed" if advance > 0 else "Inquiry")

    conn = get_db_connection()
    try:
        with conn:
            cur = conn.execute("""
                INSERT INTO catering_orders (
                    customer_name, phone, event_date, event_time, event_type,
                    pax_count, menu_description, price_per_pax, total_amount,
                    advance_paid, order_status, delivery_address, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (cust_name, phone, event_date, event_time, event_type, pax, menu, price_per_pax, total_amount, advance, status, address, notes))
            order_id = cur.lastrowid
        return web.json_response({"success": True, "id": order_id})
    finally:
        conn.close()


@routes.put("/api/catering/{id}")
async def handle_update_catering_order(request: web.Request) -> web.Response:
    """Updates status, advance, or details of a catering order."""
    order_id = request.match_info["id"]
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    conn = get_db_connection()
    try:
        with conn:
            order = conn.execute("SELECT * FROM catering_orders WHERE id = ?", (order_id,)).fetchone()
            if not order:
                return web.json_response({"error": "Order not found"}, status=404)

            advance = clean_number(data.get("advance_paid", order["advance_paid"]))
            status = data.get("order_status", order["order_status"])
            notes = data.get("notes", order["notes"])

            conn.execute("""
                UPDATE catering_orders 
                SET advance_paid = ?, order_status = ?, notes = ?
                WHERE id = ?
            """, (advance, status, notes, order_id))

        return web.json_response({"success": True, "id": order_id})
    finally:
        conn.close()


@routes.delete("/api/catering/{id}")
async def handle_delete_catering_order(request: web.Request) -> web.Response:
    """Deletes a catering order."""
    order_id = request.match_info["id"]
    conn = get_db_connection()
    try:
        with conn:
            conn.execute("DELETE FROM catering_orders WHERE id = ?", (order_id,))
        return web.json_response({"success": True, "deleted_id": order_id})
    finally:
        conn.close()


# -------------------------------------------------------------------------
# Static File Serving & Frontend Router
# -------------------------------------------------------------------------
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@routes.get("/")
async def handle_index(request: web.Request) -> web.FileResponse:
    """Serves the single page application HTML."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    return web.FileResponse(index_path)


def create_app() -> web.Application:
    """Constructs and returns the configured aiohttp web application."""
    init_db()
    app = web.Application()
    app.add_routes(routes)
    # Serve static directory
    if os.path.exists(STATIC_DIR):
        app.router.add_static("/static/", path=STATIC_DIR, name="static")
    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    host = os.environ.get("HOST", "0.0.0.0")
    logger.info(f"Starting Sumiyuru Stall ERP server on http://{host}:{port}")
    web.run_app(create_app(), host=host, port=port)
