# Sumiyuru Catering & Roadside Stall — ERP & Cash Flow Cockpit

> **High-Performance Stall Operations, Cash Envelope Accounting, & Catering CRM Engine.**  
> Designed for physical roadside stall environments, multi-supplier cash settlements, and unencumbered owner profit reconciliation.

---

## Architecture Overview

```
                      ┌───────────────────────────────────────┐
                      │   Roadside Stall Smartphone / Desktop │
                      │       PWA Single Page Application     │
                      └──────────────────┬────────────────────┘
                                         │ HTTP / REST
                                         ▼
                      ┌───────────────────────────────────────┐
                      │    Reverse Proxy (Caddy / Nginx)      │
                      │  Automatic HTTPS / SSL (Let's Encrypt)│
                      └──────────────────┬────────────────────┘
                                         │ Port 8080
                                         ▼
                      ┌───────────────────────────────────────┐
                      │  Python aiohttp Async Server Engine   │
                      │  - Executive Cockpit & Projections    │
                      │  - 3-Envelope Cash Flow Allocations   │
                      │  - Mobile Shift Tally & POS Logger    │
                      │  - Catering Pipeline & WhatsApp CRM   │
                      │  - Day-of-Week Waste & Par Optimizer  │
                      └──────────────────┬────────────────────┘
                                         │ SQLite (WAL Mode)
                                         ▼
                      ┌───────────────────────────────────────┐
                      │  sumiyuru.db (Zero-Leakage Relational)│
                      │  - suppliers & unit_economics         │
                      │  - daily_shifts & shift_sales_items   │
                      │  - cash_envelope_handovers            │
                      │  - catering_orders & inventory_rules  │
                      └───────────────────────────────────────┘
```

### The 3-Envelope Physical Cash Flow System
Roadside stall economics in Sri Lanka operate on hard currency till integrity. Every night at closing (9:30 PM), the till cash is audited against sales and apportioned into strict physical envelopes:
1. **[Envelope 1] Tomorrow Morning Suppliers:** Immediate cash buffer for morning bakery & hopper deliveries upon arrival (Delish, Nishan, Hoppers).
2. **[Envelope 2] Helper Wages Packet:** Daily Rs. 1,200 helper wage allocation (or Rs. 0 when owner runs full-time).
3. **[Envelope 3] Master Reserve Heap:** Cumulative owner cash reserve buffer.
   - Accrues month-end kitchen payables (net of pre-paid PW Farm & Nirosha Chicken stock).
   - Accrues Godrej coffee premix & overheads (Electricity @ Rs. 167/day).
   - Generates **Free Memory**: 100% pure, unencumbered owner profit ready for weekly handover to Dad.

---

## Core Capabilities & Features

| Capability | Description |
| :--- | :--- |
| **AI Bill & Receipt Vision Scanner** | Snap or upload receipt photos on mobile. Powered by **Gemini 2.5 Flash Vision** to extract line items, audit vendor math, and auto-commit to the daily shift expenses. |
| **Executive Cash Cockpit** | Live physical envelope tracking, month-end accrual liabilities, pure owner profit in hand, and 30-day forecast. |
| **Roadside POS & Shift Tally** | Touch-optimized mobile stock entry (Opening A vs Leftover B). Real-time gross sales, COGS, and units sold. |
| **Cash Reconciliation Engine** | End-of-shift till cash counter with instant variance calculation (Over/Short) and automated Net-to-Reserve commits. |
| **Catering Order CRM** | Event bookings, guest counts (pax), advance tracking, and 1-click formatted **WhatsApp Quotation generator**. |
| **Inventory Demand Optimizer** | Day-of-week par demand targets, 100% sell-out restock alerts, and high-waste alerts (e.g. Nishan bun par caps). |
| **Day-of-Week Strategy Engine** | Identifies optimal operating days (Thu/Fri/Sat peaks) and recommends weekly closure day (**Tuesday: cuts 10.4% waste**). |
| **Printable Tally Sheet (A4)** | Instant paper tally worksheet printer matching the physical clipboard template with denomination breakdown. |
| **Unit Economics & Margin Matrix** | Live cost, selling price, and unit margin table for all 18 standard menu items across suppliers. |
| **Operational Playbook** | High-priority stall SOPs, supplier order rules, and Poya/weather protocols. |

---

## Prerequisites

- **VPS Operating System:** Any Linux distribution (Ubuntu 20.04+, Debian 11+, Arch Linux, AlmaLinux/Rocky/CentOS).
- **Runtimes (One of the following):**
  - **Option A (Containerized - Recommended):** Docker 24.0+ & Docker Compose v2.
  - **Option B (Native):** Python 3.10+ & SQLite3.
- **Port:** Port `8080` (or `80`/`443` for domain reverse proxy).

---

## Zero-Fluff VPS Deployment

### 1. Transfer Project to VPS
From your local terminal, transfer the repository to your VPS:
```bash
rsync -avz --exclude '.git' /home/kisalnelaka/Work/foodstall_erp/ root@<YOUR_VPS_IP>:/opt/sumiyuru-stall-erp/
```

### 2. Automated Single-Command Deploy
SSH into your VPS and execute the automated setup script:
```bash
ssh root@<YOUR_VPS_IP>
cd /opt/sumiyuru-stall-erp
sudo ./deploy.sh
```
The script will automatically detect whether Docker or Native Python is installed, configure permissions, seed the database with all 17 days of historic Google Sheets records, and start the service.

### 3. Verification
Verify the application health check:
```bash
curl -I http://127.0.0.1:8080/api/health
```
Open your browser and navigate to:
```
http://<YOUR_VPS_IP>:8080
```

---

## Manual Deployment Options

### Method A: Docker Compose (Production Standard)
```bash
# Build and run containers in background
docker compose up -d --build

# View real-time logs
docker compose logs -f app

# Stop containers
docker compose down
```

### Method B: Native Systemd Service
```bash
# Install dependencies
python3 -m pip install -r requirements.txt
python3 db.py

# Link and start systemd daemon
sudo cp sumiyuru.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sumiyuru.service

# Check status
sudo systemctl status sumiyuru.service
```

---

## Automatic HTTPS / SSL Domain Setup

To point your custom domain (e.g., `stall.sumiyuru.com`) with automated Let's Encrypt certificates:

1. Add an **A Record** in your DNS pointing `stall.sumiyuru.com` to `<YOUR_VPS_IP>`.
2. Edit `Caddyfile` and replace `stall.yourdomain.com` with your domain.
3. Uncomment the `caddy` service in `docker-compose.yml` and restart:
```bash
docker compose up -d
```
Caddy will automatically request and renew Let's Encrypt certificates.

---

## API Documentation

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/bills/upload` | Multipart photo upload analyzed by Gemini 2.5 Flash with mathematical cross-audit. |
| `POST` | `/api/bills/confirm` | Commits verified bill into expense ledger and recalculates shift reserve. |
| `GET` | `/api/bills/history` | Audit log of all historical scanned receipts with photo preview links. |
| `GET` | `/api/health` | System health check and SQLite integrity verification. |
| `GET` | `/api/dashboard/cockpit` | Executive KPIs, Cycle 2 vs Cumulative stats, Envelope balances, and 30-day forecast. |
| `GET` | `/api/shifts` | List all historical operational shifts with sales totals and units. |
| `GET` | `/api/shifts/{id}` | Detailed shift audit including line-item quantities for all 18 products. |
| `POST` | `/api/shifts` | Save or update a daily shift tally (Opening A vs Leftover B). |
| `POST` | `/api/shifts/{id}/reconcile` | End-of-shift till cash reconciliation and Master Reserve commit. |
| `GET` | `/api/items` | Full product catalog with unit costs, selling prices, and margins. |
| `POST` | `/api/items` | Create or update a menu product. |
| `GET` | `/api/suppliers` | List of suppliers and settlement terms (Morning_Cash vs Month_End). |
| `GET` | `/api/inventory/optimizer` | Par target recommendations and action signals (Sell-Out / Waste alerts). |
| `GET` | `/api/analytics/day-of-week`| Day-of-week volume, revenue, waste %, and closure strategy. |
| `GET` | `/api/catering` | Catering order bookings, guest counts, and payment status. |
| `POST` | `/api/catering` | Create a catering booking with advance payment tracking. |
| `POST` | `/api/reserve/handover` | Record weekly/cycle cash handover (e.g. to Dad) and reset reserve. |

---

## License
MIT License. Copyright (c) 2026 Sumiyuru Catering & Roadside Stall.
