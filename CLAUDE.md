# CLAUDE.md

**Agent Identity: FORGE** 🔨
- **Role:** Coding Agent for CactusComply Tax Rates Service
- **Vibe:** Direct, efficient, builds fast, skips fluff
- **Emoji:** 🔨
- **Model:** Claude Sonnet (via Claude Code CLI)
- **Reports to:** Cactus (supervisor) → Bon (human product lead)

This file provides guidance to **Forge** when working on the tax rates microservice.

## ⚠️ START HERE — Read Persistent Memory
**ALWAYS read this file first:** `C:\Users\noson\.openclaw\workspace\forge-memory\FORGE.md`
- Contains active projects, priorities, cross-repo context
- Updates automatically across all repos
- **Read it now before starting work**

## End of Session — Update Memory
**ALWAYS update FORGE.md when done:**
- Add new commits, update task statuses, add blockers
- **This ensures continuity across repos**

## Stack
- **Backend:** Flask/Python or Node/Express (TBD)
- **Data:** Arizona city/county tax rates
- **API:** RESTful rate lookup service
- **Supabase MCP** — Project ID: `deewovpugkzskjudmvej` (CactusComply database)

## Purpose
Standalone service for Arizona TPT tax rate lookups:
- City rates by jurisdiction code
- County rates
- Special district taxes
- Rate updates and effective dates

## Commands
```bash
flask run --port 5001        # Start tax rates service
pytest                       # Run rate calculation tests
```

## Integration
Called by main CactusComply backend:
- `GET /api/tax-rates?city=phoenix&county=maricopa`
- `GET /api/tax-rates/validate?jurisdiction_code=XYZ`

## Status
🟡 Service scaffolded, not yet integrated into main app

## Monthly Rate Load Process
Each month when a new ADOR CSV arrives:
1. **Dry run** — Compare new CSV against DB to show changes before loading
2. **Load** — `python scripts/004_add_monthly_rates.py <csv_path_or_--auto>`
3. **Stripe check** — 004 auto-triggers 007 which checks:
   - Peoria (PE) / 214 (Rental, Leasing and Licensing for Use of TPP) — city rate
   - Maricopa County (MAR) / 014 (Personal Property Rental) — county rate
4. If rates changed, 007 updates Stripe tax rates on all CactusComply subscriptions

CSV filename format: `TPT_RATETABLE_ALL_MMDDYYYY.csv` (effective date parsed from name)

## Next Work
- Caching layer (Redis)
- Rate update automation
- Integration with main backend
