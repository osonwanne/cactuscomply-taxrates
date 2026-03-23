# Stripe Tax Collection for CactusComply

## Current Setup (2026-03-15)

AZ TPT tax rates are applied to CactusComply SaaS subscriptions based on business address:
**8427 W Salter Dr, Peoria, AZ 85382**

### Tax Rates Applied

| Jurisdiction | Code | Business Code | Rate | Stripe Tax Rate ID |
|---|---|---|---|---|
| PE - Peoria (city) | 214 | Rental, Leasing and Licensing for Use of TPP | 1.8% | txr_1TB9szEvADIQMWtXn8F5aSxS |
| MAR - Maricopa County | 014 | Personal Property Rental | 6.3% | txr_1TB9t0EvADIQMWtXJeGMzOCR |
| **Total** | | | **8.1%** | |

### Products with Tax Collection Enabled

| Product | Price | Stripe Product ID | Tax Enabled |
|---|---|---|---|
| Cactus Comply Pro Plan | $79/mo | prod_Smd3Ucc7jlgzku | YES |
| Cactus Comply Starter Plan | $29/mo | prod_Smd2EMszAZydyD | YES |

### Products NOT Yet Configured (TODO)

These products exist in the same Stripe account but do NOT have AZ TPT tax rates applied.
Review and determine if they should collect AZ TPT:

| Product | Price | Stripe Product ID | Notes |
|---|---|---|---|
| CoveredCalls.AI Premium Plan | $299/mo | prod_QyRMY7xZd4Cvyf | Different product — may need own tax config |
| CoveredCalls.AI Pro Plan | $99/mo | prod_QyR4J7Lbt0PErR | Different product — may need own tax config |
| CoveredCalls.AI Starter Plan | $29/mo | prod_QyR4J7Lbt0PErR | Different product — may need own tax config |
| Private 1-on-1 Mentoring | $500/mo or $5000/yr | prod_LMvpRgybVg644D | Service — may be exempt from TPT |
| Annual Plan | $1200/yr | prod_LMY1DrD7VJJhZH | Review if SaaS or service |
| Monthly Plan | $125/mo | prod_LMY1JQxPX5eaoa | Review if SaaS or service |

### Action Items

- [ ] Determine if CoveredCalls.AI products are taxable SaaS under AZ TPT (same address? same business?)
- [ ] Determine if mentoring/consulting services are subject to TPT (likely not — services are generally exempt)
- [ ] When adding NEW products to Stripe, add their product ID to `CACTUSCOMPLY_PRODUCT_IDS` in `scripts/007_sync_stripe_tax_rates.py`
- [x] Ensure subscription creation code passes `default_tax_rates` with the tax rate IDs from product metadata
  - Done: `billing_service.py` on `feature/stripe-billing-integration` branch in `cactuscomply-integrations` (commit `55bc09f`)
  - Adds `subscription_data={"default_tax_rates": AZ_TPT_TAX_RATE_IDS}` to `stripe.checkout.Session.create()`
  - Goes live when the Stripe billing PR is merged

## How It Works

1. ADOR publishes new monthly tax rate CSV
2. Run `python scripts/004_add_monthly_rates.py --auto` to ingest rates
3. Script 004 auto-triggers `007_sync_stripe_tax_rates.py`
4. Script 007 checks if Peoria (214) or Maricopa County (014) rates changed
5. If changed: creates new Stripe tax rate, archives old, updates all active CactusComply subscriptions
6. If unchanged: exits with "No rate changes detected"

## Important Notes

- Stripe tax rates are **immutable** — when a rate changes, a new rate is created and the old one is archived
- `tax_behavior: exclusive` means tax is added ON TOP of the price (customer sees $79 + $6.40 tax)
- Tax rate IDs are stored in product metadata (`default_tax_rates`) for reference during subscription creation
- Only subscriptions for products in `CACTUSCOMPLY_PRODUCT_IDS` are updated
