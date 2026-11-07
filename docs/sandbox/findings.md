# SAP sandbox data check

Issue #7. Run twice on 2026-11-07 against `https://sandbox.api.sap.com` with
`uv run python -m scripts.sandbox_check`. Every number below comes from the script; the second
run's output is in [check_results.json](check_results.json) (including a log of every call), and
the raw `$metadata` of the four APIs is in [metadata/](metadata/). Both runs gave the same counts
and statuses; only the timings differ, so the timing table shows both.

The sandbox is shared and changes daily (plant AUC1 gains about one released order per day),
so the counts below drift. Acceptance tests should assert the rules, not these numbers.

## Summary

| Question | Answer |
|---|---|
| Plant | **AUC1**: most released open orders (725), all with components, all three colours occur at component level, loads in 2.3–3.5 s |
| Release filter | `OrderIsReleased eq 'X' and OrderIsDelivered eq '' and OrderIsTechnicallyCompleted eq '' and OrderIsClosed eq '' and OrderIsDeleted eq '' and OrderIsMarkedForDeletion eq ''` |
| Start-date field | `MfgOrderScheduledStartDate` (always filled; equal to `MfgOrderPlannedStartDate` in AUC1) |
| Unit codes | Components: only `PC` in AUC1; `PC`, `KG`, `EA` in 1710. Stock in AUC1: only `PC` |
| Unrestricted stock | `InventoryStockType eq '01' and InventorySpecialStockType eq ''` |
| Statuses in AUC1 | Components: 3,884 red, 6 amber, 2,021 green, 0 unit mismatch. Orders: 474 red, 251 green, **0 amber** |
| Competing demand | Yes: all 16 component materials of AUC1 are needed by two or more orders |
| Load time for AUC1 | 2.3–3.5 s with 3 calls (orders + components 1.2–2.2 s, stock and descriptions ~0.5–0.7 s each) |
| Biggest risk | **No released open order starts today or later**, in any plant. The default range (today to +14 days) shows only overdue orders |

## Production orders (`API_PRODUCTION_ORDER_2_SRV`)

Entity set `A_ProductionOrder_2`. All released open orders are category `10`. Their order type is
mostly `ZBM1` (AUC1: 724 of 725; 1710: 517 of 572, plus `YBM1`, `YBM4`, `YBM5`; the one
order in 1010 is `YBM3`). The release
filter does not depend on the type.

### Orders per plant

Counts per status flag (a flag is `'X'` when set and `''` when not set). "Released open" uses the
release filter above.

| Plant | Total | Released | Delivered | Techn. completed | Closed | Deleted | Marked for deletion | Released open |
|---|---|---|---|---|---|---|---|---|
| 1710 | 55,968 | 46,921 | 54,251 | 8,671 | 313 | 0 | 4 | 572 |
| AUC1 | 7,399 | 7,321 | 6,636 | 78 | 0 | 0 | 0 | **725** |
| USC1 | 7,353 | 7,285 | 6,650 | 61 | 7 | 0 | 1 | 676 |
| DEC1 | 6,334 | 6,302 | 5,993 | 31 | 0 | 0 | 0 | 330 |
| 1010 | 9 | 7 | 6 | 1 | 0 | 0 | 0 | 1 |

`OrderIsPartiallyReleased` is never set. `OrderIsReleased` stays set after delivery, so "released"
alone is not enough: the filter must also exclude delivered, completed, closed and deleted orders.
One released open order in 1710 is partially delivered (`OrderIsPartiallyDelivered`); the filter
keeps it.

### Status flag fields

`OrderIsReleased`, `OrderIsDelivered`, `OrderIsTechnicallyCompleted`, `OrderIsClosed`,
`OrderIsDeleted`, `OrderIsMarkedForDeletion` (also present: `OrderIsCreated`,
`OrderIsPartiallyReleased`, `OrderIsPartiallyDelivered`, `OrderIsLocked`). The entity set
`A_ProductionOrderStatus_2` holds the same status as codes; the flags are enough.

### Start dates

| Field | Meaning | Filled in released open orders |
|---|---|---|
| `MfgOrderScheduledStartDate` | Scheduled start | All, every plant |
| `MfgOrderPlannedStartDate` | Basic (planned) start | All, every plant |

The two differ for 5 orders in 1710 and for none in AUC1, DEC1 and USC1. Use
`MfgOrderScheduledStartDate`: it is the date production is scheduled to begin. Dates come as
OData V2 values, e.g. `/Date(1496707200000)/` (milliseconds since 1970, UTC).

Start dates of released open orders in AUC1: 2021-06-04 to 2026-11-06. 14 orders started in
the last 14 days, none today or later. The other plants' latest start dates are older
(1710: 2026-09-02, DEC1 and USC1: 2026-07-23).

### Other order fields

| What | Field |
|---|---|
| Order number | `ManufacturingOrder` (e.g. `1000000`, 7 digits) |
| Plant | `ProductionPlant` (equal to `Plant` on every released open order) |
| Material | `Material` |
| Quantity, unit | `TotalQuantity`, `ProductionUnit` |

## Components

Navigation `to_ProductionOrderComponent` (entity type `A_ProductionOrderComponent_2`), read
together with the orders via `$expand`. All 725 released open orders in AUC1 have components
(5,911 lines, 16 materials, 8.2 per order on average).

| What | Field |
|---|---|
| Material | `Material` |
| Plant | `Plant` |
| Required quantity | `RequiredQuantity` |
| Withdrawn quantity | `WithdrawnQuantity` |
| Unit | `BaseUnit` (also `BaseUnitISOCode`, `BaseUnitSAPCode`) |
| Line | `ManufacturingOrder` + `ReservationItem` |
| Fully issued flag | `ReservationIsFinallyIssued` (boolean) |

Open requirement = `RequiredQuantity − WithdrawnQuantity`. In AUC1 nothing is withdrawn, so the
open requirement equals the requirement. In 1710, 84 components are withdrawn and finally issued
(open requirement 0).

**Unit codes.** `BaseUnit` holds the commercial code: `PC` (ISO `PCE`, internal SAP code `ST`).
Components in AUC1, DEC1 and USC1 are all `PC`. 1710 also has `KG` (6) and `EA` (2). Every
component that has stock uses the same unit as its stock. The two `EA` components
(`MZ-FG-M600-01`, `-02`) have no stock rows at all, so an `EA` against `PC` mismatch never occurs
either.

**The same material on several lines.** In 1710, 5 orders list a material on more than one
line (22 lines in total); AUC1, DEC1 and USC1 have none. The script lets those lines take stock
one after the other, so the second line sees what the first left. REQ-4 does not say whether
such lines are combined (REQ-5 combines them for requisitions). See risk 9.

## Stock (`API_MATERIAL_STOCK_SRV`)

Entity set `A_MatlStkInAcctMod`: one row per material, plant, storage location, batch, stock type
and special stock.

| What | Field |
|---|---|
| Material, plant, storage location | `Material`, `Plant`, `StorageLocation` |
| Quantity | `MatlWrhsStkQtyInMatlBaseUnit` (decimal) |
| Unit | `MaterialBaseUnit` |
| Stock type | `InventoryStockType` |
| Special stock | `InventorySpecialStockType` |

Stock rows for the component materials of 1710: 219, of which stock type `01` 215, `02` 3, `07` 1;
special stock empty 212, `O` 4, `E` 2, `K` 1; units `PC` 216, `KG` 3. AUC1 has 16 rows (DEC1 17,
USC1 28), all `01` with no special stock, all in `PC`. 1010 has no stock rows for its components.

Unrestricted-use, non-special stock (REQ-3) is
`InventoryStockType eq '01' and InventorySpecialStockType eq ''`. In SAP's stock type codes `01` is
unrestricted use, `02` quality inspection and `07` blocked (from SAP's documentation; the sandbox
returns codes only). Special stock such as `E` (sales order) and `K` (consignment) has a
non-empty `InventorySpecialStockType`, also on rows with type `01`. Sum
`MatlWrhsStkQtyInMatlBaseUnit` over storage locations. No material in the checked plants has
stock rows in more than one unit.

## Product (`API_PRODUCT_SRV`)

Description: entity set `A_ProductDescription`, key `Product` + `Language`, field
`ProductDescription` (max 40 characters). Filter `Language eq 'EN'`. Every component material
of every plant has an English description (e.g. `MZ-RM-C990-01` → "BKC-990 Frame").

## Calculation by hand (REQ-4)

The script allocates unrestricted stock to all released open orders of the plant by
`MfgOrderScheduledStartDate`, then order number. It uses the open requirement, takes only the
real requirement from stock, and colours each component red (available < requirement), amber
(available < 1.1 × requirement) or green. Same-dimension units are converted; other unit
differences count as unit mismatch.

| Plant | Components red / amber / green / mismatch / issued | Orders red / amber / green / no open components | Competing materials |
|---|---|---|---|
| AUC1 | 3,884 / 6 / 2,021 / 0 / 0 | 474 / 0 / 251 / 0 | 16 of 16 |
| USC1 | 3,416 / 0 / 2,345 / 0 / 0 | 402 / 0 / 274 / 0 | 28 of 28 |
| DEC1 | 1,970 / 0 / 1,324 / 0 / 0 | 197 / 0 / 133 / 0 | 17 of 17 |
| 1710 | 20 / 6 / 4,818 / 0 / 84 | 16 / 0 / 545 / 11 | 127 of 153 |
| 1010 | 4 / 0 / 0 / 0 / 0 | 1 / 0 / 0 / 0 | 0 of 4 |

Red, amber and green all occur at component level in AUC1 and 1710. **No order has amber as its
worst status in any plant**: the six amber components always sit in an order that also has a
red one. Every material in AUC1 is needed by many orders, so competing demand (earlier orders
taking the stock) is what makes later orders red.

## Calls, timing and paging

Loading one plant takes three kinds of call: orders with expanded components (one call), stock
for the component materials, and descriptions. The script batches 40 materials per stock and
description call.

| Plant | Calls | Run 1 | Run 2 | Run 2 per call |
|---|---|---|---|---|
| AUC1 (16 materials) | 3 | 3.5 s | 2.3 s | 1.2 + 0.5 + 0.5 s |
| USC1 (28 materials) | 3 | 4.0 s | 2.4 s | 1.3 + 0.5 + 0.6 s |
| DEC1 (17 materials) | 3 | 3.1 s | 2.1 s | 0.9 + 0.5 + 0.6 s |
| 1010 (4 materials) | 3 | 3.0 s | 1.6 s | 0.5 + 0.6 + 0.5 s |
| 1710 (162 materials) | 11 | 9.7 s | 8.1 s | 2.5 s for orders, then 10 × ~0.55 s |

A single call costs at least ~0.5 s. The 45 `$count` calls of run 2 took 0.51–1.14 s, 0.58 s on
average.

Paging: the server sets no page size. A GET without `$top` for plant 1710 returned all 55,968
orders in one response, without a `__next` link. `$top` (20,000 returned 20,000 rows), `$skip` and
`$orderby` work. The client should still follow `__next` in case that changes, and should never
read an entity set without a plant filter.

The whole script makes 79 GET calls and takes about a minute.

## Surprises and risks

1. **No orders in the default range.** No released open order in any plant starts today or
   later; all 725 AUC1 orders are overdue. With the default range (today to +14 days), the list
   shows only overdue orders (15 pages of 50). The "in range" half of AC-1 and AC-18 cannot be
   seen with live data; test it with constructed data. AUC1 gains about one order per day, so
   a demo on a given day may show one order dated that day.
2. **No amber orders.** Amber appears on 6 components but never as an order's status. Order-level
   amber (AC-17) is proven by unit tests only (D-19).
3. **No unit conversion or mismatch in the data.** Component and stock units always match, so
   AC-13 and the unit part of AC-19 are proven by unit tests only. AC-11 ("issued") cannot be
   seen in AUC1; 1710 has 84 issued components.
4. **Mostly red.** 65% of AUC1 orders are red, because orders from 2021–2025 that were never
   delivered take the stock first. The demo will look alarming; that is the data, not a bug.
5. **Tonne is `TO`, not `T`.** SAP's commercial code for tonne is `TO`. The spec lists `T` for
   `cockpit/services/units.py`; it should list `TO` (or accept both). Codes come in the
   commercial form (`PC`, `KG`), not ISO (`PCE`, `KGM`) or internal (`ST`).
6. **Plant 1710 misses the 5 s target.** With 162 materials it needs 11 calls and 8–10 s. Offering
   1710 in `COCKPIT_PLANTS` needs fewer, larger stock and description calls or parallel calls.
   AUC1, USC1 and DEC1 fit in 5 s.
7. **Materials without stock.** 8 component materials in 1710 have no unrestricted stock row; the
   cockpit must treat that as stock 0. AUC1 has none.
8. **Phantom components.** 1710 has 5 phantom components (`MaterialComponentIsPhantomItem`),
   which are normally not stocked and so may show red. AUC1 has none. The spec does not mention them.
9. **Repeated materials within one order.** 5 orders in 1710 have the same material on several
   lines. The spec should say whether those lines are combined before allocation (as REQ-5 does
   for requisitions) or allocated line by line (as this script does). It changes statuses only
   in 1710.

## Recommended values for the spec (#12)

- `COCKPIT_PLANTS=AUC1` (USC1 and DEC1 also work; 1710 only after risk 6 is handled).
- Release `$filter` and start-date field as in the summary.
- Component fields `RequiredQuantity`, `WithdrawnQuantity`, `BaseUnit`; stock filter
  `InventoryStockType eq '01' and InventorySpecialStockType eq ''`; description from
  `A_ProductDescription` with `Language eq 'EN'`.
- Unit codes for `units.py`: `G`, `KG`, `TO`, `ML`, `L`, `M3`, `MM`, `CM`, `M`.
- Decide how lines of the same material within one order are allocated (risk 9).
- ACs proven by unit tests only with sandbox data: order-level amber (AC-17), unit conversion and
  mismatch (AC-13, AC-19), "issued" in AUC1 (AC-11), and orders inside the default range (AC-1).
