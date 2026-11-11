# Material Shortage Cockpit requirements

Status: Proposed

## Problem and users

Production planners release production orders in SAP without a quick view of whether the components for those orders are in stock. Shortages surface late, when an order is about to start, and replenishment is requested by hand outside the planning view. Planners need to see which released orders are at risk from component shortages, in what order stock will be consumed, and request replenishment in one step.

Users (one role per user):

- **Viewer**: sees orders, components, stock, statuses and the dashboard. Cannot change anything.
- **Planner**: everything a Viewer can do, plus creating purchase requisitions.
- **Manager**: all business functions, plus approving requisitions and changing the cover buffer (change request).
- **Admin**: manages users and role assignment only. Has no access to business screens.

This product is built twice in a PoC (Mendix + Maia Make and an agentic software factory) against the same requirements. Data comes from the public SAP S/4HANA Cloud sandbox (read only); requisitions go to a shared mock of the SAP purchase requisition API.

## User stories

### REQ-1: See released production orders for a plant and date range

As a Planner, I want to select a plant and a start-date range and see the released production orders in it, so that I know which orders to check.

Done when:
- The plants offered are set by environment variable; the default is AUC1, the plant chosen in the sandbox data check.
- The list shows released orders of the selected plant whose start date falls in the range (inclusive). The default range is today to today + 14 days.
- Released orders with a start date before today are also shown, marked "overdue".
- Each order shows its number, material, quantity, start date and an overall status (see REQ-4).
- The list shows "Data as of <time>" and a Refresh button. Refresh reloads all data for the plant from SAP.
- A cold load of a plant (no stored data yet) completes within 5 seconds, excluding SAP sandbox outages, any single SAP call that alone takes over 5 seconds, and the hosted app waking from sleep.
- The list shows 50 orders per page.
- If SAP cannot be reached, the last loaded data stays visible with a warning banner showing when it was last updated. If no data was ever loaded for the plant, a clear error page explains that SAP is unavailable.

### REQ-2: See component requirements per order

As a Planner, I want to open an order and see its components, so that I know what the order needs.

Done when:
- For each component: material, description, open requirement (required − withdrawn, shown as "Required") and unit. The withdrawn quantity is used for the calculation but not shown.
- Components with no open requirement (fully withdrawn) are shown as "issued" and are left out of the status calculation.
- Quantities always show their unit next to them.

### REQ-3: See current stock per component

As a Planner, I want to see the current stock of each component in the order's plant, so that I can judge whether the order can run.

Done when:
- Stock is the unrestricted-use stock of the material, summed over all storage locations of the plant. Quality inspection, blocked and special stock are not counted.
- Stock is shown in the order's unit. When it was converted, the tooltip shows the original value and unit (e.g. "1,500 G (= 1.5 KG)").

### REQ-4: See shortages with a status

As a Planner, I want each component and order to show whether it is short, at risk or covered, so that I can act on the riskiest orders first.

Done when:
- Stock is allocated to orders by start date (earliest first; ties by order number) across all released orders of the plant, regardless of the current filter. Narrowing the filter never changes a status.
- For each component: available = stock left after earlier orders took their open requirement (never below 0); shortage = max(0, open requirement − available).
- Status: **red** when available < open requirement; **amber** when available covers the requirement but by less than 10% (available < 1.1 × requirement); **green** otherwise.
- The 10% buffer only affects the colour. Allocation takes only the real requirement from stock.
- An order's status is the worst status of its components.
- Each status has a tooltip explaining the rule; the Low cover and Covered texts include the current buffer value. The texts are in [docs/ui/ui-spec.md](docs/ui/ui-spec.md), section 5.2.
- Quantities in different units of the same dimension (mass G/KG/TO, volume ML/L/M3, length MM/CM/M) are converted exactly. Any other unit difference shows a grey "unit mismatch" status with both units in the tooltip; the order gets a warning badge and the component counts as neither red nor green.

### REQ-5: Create a purchase requisition for a shortage

As a Planner, I want to request replenishment for a short or low cover material from the order view, so that purchasing can act without me leaving the cockpit.

Done when:
- A short (red) or low cover (amber) component has a "Request" button. One requisition covers one order and one material (component lines with the same material are combined).
- A confirm step shows material, plant, quantity, unit and delivery date. The quantity is prefilled with the shortage for a short component, and with the amount that brings available up to (100 + buffer)% of the open requirement for a low cover component, rounded up to 3 decimals in the order unit. It can be changed: it must be greater than 0, may be above or below the prefilled value, and has at most 3 decimals. The planner enters it in the order's unit; the confirm step also shows the quantity in the stock unit that will be sent.
- The delivery date is the order's start date, or today if that date has passed.
- On success, the requisition number from SAP is shown and the button is replaced by a "PR sent" label that opens the requisition with its PR number and quantity. The component's status colour does not change, because stock has not changed.
- A second requisition for the same order and material cannot be created once one succeeded.
- On failure, the error message from SAP is shown, the attempt is stored, and the planner can try again.
- A component without any requisition shows the Request button. A component whose latest requisition failed or was rejected shows that label instead; opening it offers Retry (failed) or shows the reason and Request again (rejected).
- A requisition list shows every attempt: number, order, material, quantity, unit, delivery date, user, time and outcome.
- A Viewer never sees the Request button, and a direct request by a Viewer is refused.

### REQ-6: See a shortage dashboard

As a Manager, I want a dashboard of shortages, so that I can see where the plant is at risk at a glance.

Done when:
- The dashboard shows, for the selected plant and range: the number of red orders, shortages per material (total shortage and the orders affected) and shortages per order.
- Unit mismatches are listed separately and not counted as red.
- Viewers, Planners and Managers can open it.

### REQ-7: Control access by role

As an Admin, I want to assign one role to each user, so that only the right people can create or approve requisitions.

Done when:
- Every page requires login. An anonymous user is sent to the login page.
- The Admin assigns users to exactly one role (Viewer, Planner, Manager, Admin) in the built-in admin.
- The Admin cannot open business screens. Business users cannot open user administration.
- Every permission is checked on the server. A forbidden action returns an "access denied" page, also when the request is sent directly.

### REQ-8: Respect the SAP safety stock (change request)

As a Manager, I want statuses to keep the safety stock set in SAP out of reach of orders, so that statuses warn me before stock drops below the level we want to keep.

Done when:
- The safety stock per material and plant is read from the SAP product master during sync. It cannot be edited in the cockpit.
- Safety stock is reserved before allocation: the stock available to orders is unrestricted stock − safety stock (never below 0). A component that would only be covered by eating into safety stock turns red.
- The tooltip mentions the safety stock when it is above 0.
- The settings screen shows that safety stock comes from SAP.

### REQ-9: Maintain the cover buffer (change request)

As a Manager, I want to change the cover buffer, so that the amber warning matches how much margin we need.

Done when:
- The Manager can change the global buffer percentage (default 10%) on the settings screen.
- Statuses and tooltips use the new value immediately.
- Values below 0% or above 100%, or with more than 2 decimals, are rejected with a message.

### REQ-10: Approve large requisitions (change request)

As a Manager, I want requisitions above a set value to need my approval before they go to SAP, so that large orders are checked.

Done when:
- The value of a requisition is its quantity in the stock unit × the material's standard price ÷ its price unit, read from SAP during sync, in the plant's valuation currency.
- A requisition with a value above the approval limit (10,000 in the plant's currency, fixed, not editable) or for a material without a price is stored as "awaiting approval" and not sent to SAP. The planner sees that status instead of a PR number.
- The settings screen shows the approval limit as read only.
- A Manager sees the requests awaiting approval in the requisition list and can approve or reject each one, optionally with a reason when rejecting.
- Approving sends the requisition to SAP and shows the result as in REQ-5. Rejecting closes it, shows the reason (when given) to the planner, and allows a new request for that order and material.
- A Manager cannot approve a requisition they created.
- While a request is awaiting approval, no second request for the same order and material can be created.

## Business rules

- Data is read from SAP only. The app never writes to the SAP sandbox; requisitions go to the configured purchase requisition endpoint (a mock during the PoC).
- One role per user. Permissions per role:

| Action | Viewer | Planner | Manager | Admin |
|---|---|---|---|---|
| See orders, components, stock, status, dashboard, requisition list | yes | yes | yes | no |
| Create a requisition | no | yes | yes | no |
| Approve or reject a requisition (not own) | no | no | yes | no |
| Change the cover buffer | no | no | yes | no |
| Manage users and roles | no | no | no | yes |

- Statuses never depend on the date filter, only on the plant's data and the settings.
- At most one open or successful requisition per order and material.

## Constraints

- The app is reachable online for the demo and the jury test, with one test account per role plus a second Manager (to check that self-approval is refused).
- The SAP connection (base URL, API key, requisition endpoint) is set by environment variables only; there is no configuration page for it.
- No secrets in the repository.
- Cold load of one plant within 5 seconds (REQ-1), measured by a timed run during testing.

## Out of scope

- Writing to a real SAP system (the requisition endpoint is a mock during the PoC).
- Material-specific unit conversions (e.g. box to pieces).
- Editing or cancelling a requisition after it was sent.
- Notifications (email, chat).
- Background or scheduled synchronisation.

## Success measures

None yet. The PoC measures how each track delivers these requirements, not the product's business value.

## Open decisions

None. Closed in #12: safety stock comes from SAP and is reserved before allocation (REQ-8); approval is value-based with a fixed limit in the plant's currency (REQ-10); the plants offered are set by environment variable with AUC1 as the default (REQ-1).
