# UI spec: Material Shortage Cockpit

> Status: agreed for S0-14 (#14), 10 Nov 2026. Where it conflicted with `spec.md`, each outcome is recorded on issue #14.
> Source: the reviewed wireframes (D-29), exported as `wireframes.pdf` (7 pages), plus decisions D-10 to D-36 in the Sprint 0 backlog (not in this repo; their outcomes are in `spec.md` and this document).
> Shared by both tracks. It describes what the user sees and does, not how to build it.

## 0. How to use this document

- **Order of authority:** `spec.md` (AC-n, INV-n) > this document > the screenshots. When they disagree, the higher one wins; report the conflict instead of guessing.
- **Values:** every colour, size, spacing, radius and shadow comes from `tokens.css`. No other values, except the few fixed sizes named in this document (6px pill dot, 3px selection bar, 28px timeline circle, 900px breakpoint).
- **Sample data in the screenshots is illustrative.** Numbers, order IDs and materials are made up and not always consistent across screens. `[PLANT]` is the selected plant and `[NB]` the requisition type from `mock_pr/README.md`. Where the wireframes show `€ [V] / [LIMIT]`, section 4 has the real content.
- **Implementation is free** (templates, components, partial page updates), as long as behaviour, labels and look match.
- **Exact copy:** labels and tooltip texts in section 5 are used word for word.

## 1. Files

| File | Content |
|---|---|
| `docs/ui/wireframes.pdf` | All 7 screens, default state |
| `docs/ui/screens/*.png` | One image per PDF page (section 7) |
| `docs/ui/source/*.html` | Wireframe source, for reference markup and CSS patterns. Written in the canvas's component format (`<x-dc>`, `{{…}}` placeholders, `<sc-for>`/`<sc-if>`, a `./support.js` runtime that is not included): read it, don't open or run it. The state logic at the bottom of each file shows the extra states. |
| `docs/ui/tokens.css` | Design tokens |
| `docs/ui/ui-spec.md` | This document |

## 2. Global layout

### 2.1 Page frame
- Two columns: **sidebar** (left, min `--sidebar-min-width`, `--color-sidebar`) and **content** (rest, `--color-page`, padding `--space-8`, max content width `--content-max-width`).
- Content is a vertical stack with `--space-section` between sections.
- **Page header:** H1 title on the left. On data screens (Orders, Order detail, Dashboard) the right side shows `Data as of [dd Mon HH:MM]` (muted) and a **Refresh** button with a refresh icon (D-17).
- **Breadcrumb** above the header on detail pages: `Orders / 1000123`, `Requisitions / REQ-0016`. Each part except the last is a link.
- **Below 900px wide:** sidebar stacks above content; card rows stack into one column; wide tables scroll horizontally inside their card. No horizontal page scroll.

### 2.2 Sidebar
- Top: logo mark (cube icon, `--color-sidebar-accent`) and the name "Material Shortage Cockpit".
- Navigation items: icon + label, min height `--touch-target`. Active item: `--color-sidebar-active`, semibold. Hover: `--color-sidebar-hover`.
- Bottom: user name (bold), role name (muted), then **Log out**.
- **Items per role (D-15, D-29):**

| Role | Items |
|---|---|
| Viewer | Orders, Dashboard, Requisitions |
| Planner | Orders, Dashboard, Requisitions |
| Manager | Orders, Dashboard, Requisitions (+ count badge), Thresholds |
| Admin | No business screens; Django admin only |

- **Count badge** on Requisitions (Manager only): number of requisitions awaiting approval that the manager may decide (own requests excluded). Hidden at 0. `--color-badge` on `--color-on-badge`, pill shape.

## 3. Components

### 3.1 Status pill
Rounded pill (`--radius-pill`), caption size, semibold, with a 6px dot in the text colour.

| Status | Colours | Dot | Used for |
|---|---|---|---|
| Short | `--color-short` on `--color-short-bg` | yes | component and order status |
| Low cover | `--color-low` on `--color-low-bg` | yes | component and order status |
| Covered | `--color-covered` on `--color-covered-bg` | yes | component and order status |
| Unit mismatch | `--color-neutral` on `--color-neutral-bg` | no | component status |
| Issued | neutral | no | component status |
| Overdue | neutral | no | badge next to a start date (D-18) |

Order status = worst component status (D-12); unit mismatch and issued components don't count.

`spec.md` and `REQUIREMENTS.md` name the statuses by colour: red = Short, amber = Low cover, green = Covered. "Issued" is a component with no open requirement and no status (AC-11).

### 3.2 Requisition label
Outlined pill (white background, 1px border and text in the colour below), no dot.

| Label | Colour | Meaning |
|---|---|---|
| PR sent | `--color-info` | sent to SAP, PR number known |
| Awaiting approval | `--color-low` | waiting for a manager (CR) |
| PR failed | `--color-short` | SAP returned an error |
| Rejected | `--color-neutral` | rejected by a manager (CR) |
| – | muted text | no requisition |

- **Order list:** one label per order. With several requisitions, show the most urgent: PR failed > Awaiting approval > PR sent (D-30). Rejected is not shown on the order list.
- **Order detail:** one label per component; it is a button that opens the requisition in the side panel.
- A requisition label never changes the status colour (D-16).

### 3.3 Info tooltip (ⓘ)
- Circle-i icon button next to a status pill, a tile label or a column header. Label for screen readers: `What does [status] mean?`.
- Tooltip shows on **hover and keyboard focus** only; hides on leave and blur. Never shown permanently.
- Look: `--color-tooltip` background, white text, small size, `--radius-tooltip`, `--shadow-tooltip`, width `--tooltip-width`. Opens below the icon.
- Texts: section 5.2.

### 3.4 KPI tile (filter tile)
- White card, `--radius-card`, label (small, muted) above a large number (`--font-size-kpi`, bold, coloured per status).
- No sub-text.
- ⓘ icon in the top-right corner (all tiles except "All orders").
- **The tile is a toggle button:** click filters the list to that status; click again (or "All orders") clears it. Selected tile: border and 1px inner ring in `--color-primary`, `--color-row-selected` background. Exposed as pressed/not pressed to screen readers.

### 3.5 Summary tile strip
Read-only numbers in one bordered strip, divided by thin vertical lines, centred label above value. Used in the requisition panel, the approval slide-in and the requisition detail.

### 3.6 Filter bar (collapsible)
- Card with one line when collapsed: `[n] filters active:` + one chip per active filter (`Plant [PLANT]`, `Start [dd Mon] – [dd Mon yyyy]`) + an **Edit filters** button on the right.
- **Collapsed by default.** Edit filters expands it below the line; the button then reads **Hide filters**.
- Expanded fields: Plant (select), Start date from, Start date to, and **Reset to default**.
- **The list updates when a value changes.** No Go or Show button (D-30).
- Defaults on every visit (D-18, not remembered): the user's plant, today to today + 14 days.

### 3.7 Data table
- Inside a white card. Header row: `--color-surface-muted`, caption size, semibold, muted. Row dividers `--color-border-subtle`.
- Numbers right-aligned with tabular figures. **Quantities always show their unit** (`20 PC`, `8.000 KG`).
- Two-line cells: main value bold, sub-line caption and muted (e.g. material ID, then description).
- **Table toolbar** (optional, top of the card): title of the current view on the left, filters on the right (select, checkbox), plus **Clear** when any list filter is active.
- Pagination below the card: `Showing [n] of [total] …` on the left, **Previous** / **Next** on the right (50 per page, D-17).
- Selected row (the one shown in a side panel or slide-in): `--color-row-selected` with a 3px inset bar in `--color-primary` on the left.

### 3.8 Buttons
| Type | Look | Use |
|---|---|---|
| Primary | `--color-primary` fill, white text | main action: Send requisition, Approve and send, Save, Retry, Request |
| Secondary | white, `--color-border-control` border | Cancel, Reject, Close, Refresh, Previous/Next |
| Ghost | no border, primary text | Edit filters, Reset to default, Clear, Show |
| Compact | height `--control-compact` | buttons inside table rows (Request, Review) |

All buttons min height `--touch-target` except compact ones. Disabled: neutral background, muted text, not-allowed cursor.

### 3.9 Side panel (order detail)
- Card to the right of the components table (stacks below it on narrow screens). Width about one third.
- Contents change in place; the page does not navigate. States in 4.2.

### 3.10 Slide-in panel (approvals)
- Opens from the right over the Requisitions page, width `--drawer-width`, full height, `--shadow-drawer`, with a scrim (`--color-scrim`) over the page.
- Closes with the ✕ button, a click on the scrim, or Escape. Focus moves into the panel on open and back to the Review button on close.
- Layout: header (status pill, title, sub-line, ✕), body (summary strip, details, link), footer (actions).

### 3.11 Timeline
Vertical list of steps. Each step: 28px circle + bold title + muted sub-line (who, when). A line connects the circles.

| Step state | Circle |
|---|---|
| Done | `--color-covered-bg` with a check |
| Waiting | `--color-low-bg` with a clock |
| Failed or rejected | `--color-short-bg` with a cross |
| Not reached | white with a dashed border |

### 3.12 Notes and banners
- **Banner** (full width, `--radius-group`): `--color-low` on `--color-low-bg` for "needs attention" (pending approvals, sync failed). Text plus an optional ghost action on the right.
- **Error note** (inside a card): `--color-short-bg` / `--color-short`, plain-language message.

## 4. Screens

### 4.1 Orders (PDF page 1, all roles)
- Header: "Production orders" + Data as of + Refresh.
- Filter bar (3.6).
- Four KPI tiles: **All orders**, **Short**, **Low cover**, **Covered** (counts over the current filter). Tiles filter the list (3.4).
- Table toolbar: title = current view (`All orders`, `Short orders`, plus ` · requisition: [label]` when that filter is on); **Requisition** select (All, None, PR sent, Awaiting approval, PR failed); **Clear** when any list filter is active.
- Columns: Order (link, bold ID + header material and description), Start date (+ Overdue pill), Quantity, Status (pill + warning icon if a component has a unit mismatch), Requisition (label, 3.2), chevron.
- Row click or order ID opens Order detail.
- Sorted by start date. Overdue released orders always listed (D-18).
- Unit mismatch: warning triangle icon next to the order status; hover text `Unit mismatch: a component isn't checked` (D-31).

### 4.2 Order detail (PDF page 2, all roles; Request only for Planner and Manager)
- Breadcrumb, H1 `Order [id]` + order status pill, sub-line: `[material] · [description] · Plant [plant] · Start [date] · [qty unit] · Released`. Data as of + Refresh.
- **Components table** (left): Component (bold ID + description · item), Required, Available, Shortage, Status (pill + ⓘ), Requisition.
  - Available shows the converted value; when converted, hover shows the original stock value in the REQ-3 format (`3,200 ML (= 3.2 L)`, D-14).
  - Requisition column: **Request** button (compact, primary) for Short and Low cover components without any requisition; otherwise the label of the latest requisition (3.2), including PR failed and Rejected; `–` for others.
  - Viewers see no Request buttons; the note under the table says so.
- **Side panel** (right), one of these states:

| State | Shown when | Content |
|---|---|---|
| Empty | nothing selected | Title "Requisition", hint text |
| Review | Request clicked | Icon + "Review requisition" + material. Summary strip: **Shortage**, **Requested** (short) or **To [100 + buffer]% cover** (low cover, e.g. `To 110% cover`; rounded up to 3 decimals), **Sent to SAP** (stock unit). Field **Quantity (order unit [U])**, prefilled (D-32). Delivery date, Plant. **Cancel** / **Send requisition**. |
| PR sent | send succeeded below the limit | Green check icon, "PR sent", PR number, quantity, requested by + time. **Close**. |
| Awaiting approval | value above the limit (CR) | Amber clock icon, "Awaiting approval", quantity, requested by + time, `Sent to SAP once a manager approves.` **Close**. |
| PR failed | SAP error | Red icon, "PR failed", error note in plain words, collapsible "Request and response". **Close** / **Retry** (back to Review). |
| Rejected | a manager rejected it (CR) | Grey cross icon, "Rejected", rejected by + time, `Reason: …` when given. **Close** / **Request again** (back to Review). |

  - The selected component row is highlighted while the panel shows it.
  - Clicking a component's requisition label opens that requisition's outcome state in the panel.
  - After Send, the snapshot syncs again (D-17); the component label updates.
- Quantity validation (D-16): > 0, max 3 decimals; error shown under the field.

### 4.3 Dashboard (PDF page 3, all roles)
- Header: "Shortage dashboard", sub-line `Plant [plant] · start [range]` (same plant and range as Orders), Data as of + Refresh.
- **Orders by status:** donut (chart tokens) with the total in the middle and a legend with counts: Short, Low cover, Covered, Unit mismatch.
- Four KPI cards with icon: **Red orders**, **Short components · [n] materials**, **Low cover components**, **Open requisitions · [n] awaiting approval**.
- Note: `Unit mismatch lines are excluded from component counts.`
- **Shortage per material:** Material, Shortage (stock unit), Orders, First needed (+ Overdue). Sorted by first needed. No totals across materials (mixed units).
- **Shortage per order:** Order (link), Start, Short, Low, Status.

### 4.4 Requisitions (PDF page 4, all roles; Review only for Manager)
- Header: "Requisitions".
- **Manager banner** (amber): `[n] awaiting your approval` + **Show** (sets the status filter to Awaiting approval). Hidden when 0 or when that filter is already on.
- Table toolbar: title = current view; **Status** select (All, Awaiting approval, PR sent, PR failed, Rejected); **Only mine** checkbox.
- Columns: Requisition (link, bold `REQ-n` + `PR [number]` or `No PR number yet` / `No PR number`), Material, Quantity, Needed by, For order (link), Requested by (+ date time), Status (pill: PR sent, Awaiting approval, PR failed, Rejected), action.
- Action column: **Review** (compact, primary) on rows awaiting approval, Manager only.
- No payloads or technical data in this list (D-33).
- Newest first.
- **Approval slide-in** (3.10), opened by Review:
  - Header: Awaiting approval pill, `[REQ-n] · [material] [description]`, `For order [id] · needed by [date]`.
  - Summary strip: **Requested**, **Shortage**, **Value / limit** (`[value] [currency] / 10,000.00 [currency]`, e.g. `12,400.00 EUR / 10,000.00 EUR`; without a price: `No price in SAP`). The Awaiting approval pill has the tooltip from 5.2.
  - Requested by + time; **Open full details** link.
  - Footer: **Reject** / **Approve and send**.
  - Reject first shows **Reason (optional)** text area, then **Back** / **Confirm reject**.
  - Own request: both buttons disabled, footer text `Your own request: another manager decides.` (D-15, D-34).
  - After a decision: the panel closes, the row and badge update.

### 4.5 Requisition detail (PDF page 5, all roles)
- Breadcrumb, H1 `[REQ-n]` + status pill, sub-line `[material] · [description] · [PR number or "No PR number yet"]`.
- Header actions: **Reject** / **Approve and send** (Manager, awaiting approval, not own); **Retry** (Planner or Manager, failed).
- Summary strip: **Requested**, **Shortage when requested**, **Value / limit** (format as in 4.4), **Needed by**.
- **Progress** card with timeline (3.11):

| Status | Steps |
|---|---|
| Awaiting approval | Requested ✓ · Manager approval (waiting) · Sent to SAP (not reached) |
| PR sent, no approval needed | Requested ✓ · Sent to SAP ✓ (PR number, time) |
| PR sent, after approval | Requested ✓ · Approved ✓ (who, when) · Sent to SAP ✓ |
| PR failed | … · Sent to SAP ✗ + error note in plain words |
| Rejected | Requested ✓ · Rejected ✗ (who, when) + `Reason: …` note |

- **Details** card: For order (link) · item, Plant, Quantity sent to SAP, Requested by.
- **Technical details** (collapsed, only when status is PR sent or PR failed): request sent to SAP and the response.

### 4.6 Thresholds (PDF page 6, Manager only, URL `/settings/`)
Three cards:
- **Cover buffer:** current value (large), field **New value (%)**, **Save**. Text: `Margin above the requirement before a component is Covered.` + `Last change: [user] · [date time]`. Validation: number from 0 to 100, max 2 decimals (AC-33).
- **Approval limit:** `Requisition value above` + `10,000 in the plant's currency` (large), tag `Fixed for the PoC`, text `Value = quantity × standard price from SAP. Without a price, a manager always approves.` Read only.
- **Safety stock:** tag `From SAP`, text `Read per material and plant, and held back from available stock. Maintained in SAP, not here.` Read only.

### 4.7 System states (PDF page 7)
| State | Behaviour |
|---|---|
| A · Login | Required for every page. Username, Password, **Log in**. Note: `Accounts and roles: Admin in Django admin.` |
| B · Sync running | On Refresh, first open of a plant, after a PR, snapshot > 5 min (D-17). Spinner + `Loading orders from SAP for [plant]…`, placeholder rows; Refresh disabled. |
| C · Sync failed, snapshot exists | Amber banner `SAP could not be reached. Showing data as of [time].` + **Try again**. Page stays usable; requisitions can still be created (D-19). |
| D · First sync failed | Full message `No data for plant [plant] yet` + explanation + error and time + **Try again** / **Choose another plant**. |
| E · Not allowed (403) | `403`, `You don't have permission for this`, then one of: (role) `You are logged in as [role]. This role cannot open this page or do this action.` with **Back to orders**, or **Go to user administration** (to `/admin/`) for Admin; (no role or several) `Your account has no role. Ask an Admin to assign one.` with **Log out**; (logged out, e.g. a stale form) `Your session has expired or the form was out of date. Log in again.` with **Log in**. Also returned for direct requests (INV-1), CSRF failures, and HTMX requests, where it replaces the whole page (#22). |
| F · Sidebar per role | See 2.2. |

## 5. Copy

### 5.1 Labels (word for word)
Production orders · Shortage dashboard · Requisitions · Thresholds · Data as of · Refresh · Edit filters · Hide filters · Reset to default · [n] filters active: · All orders · Short · Low cover · Covered · Unit mismatch · Issued · Overdue · PR sent · Awaiting approval · PR failed · Rejected · Request · Review · Review requisition · Send requisition · Cancel · Close · Retry · Approve and send · Reject · Confirm reject · Request again · Back · Reason (optional) · Open full details · Technical details · Request and response · Only mine · Clear · Show · Progress · Details · Cover buffer · Approval limit · Safety stock · Fixed for the PoC · From SAP · Log out.

### 5.2 Tooltip texts
| Where | Text |
|---|---|
| Tile Short | At least one component has less stock available than it needs, after earlier orders take their share. |
| Tile Low cover | All components are covered, but at least one has less than 10% to spare. |
| Tile Covered | All components have at least 10% to spare. |
| Component Short | Short: available stock is below the open requirement, after earlier orders take their share. |
| Component Low cover | Low cover: covered, but less than 10% to spare (available below 110% of required). Nothing is reserved. |
| Component Covered | Covered: at least 10% to spare. |
| Component Unit mismatch | Unit mismatch: order unit [U1] and stock unit [U2] can't be converted, so this component isn't checked. |
| Component Issued | Issued: no open requirement left, so it isn't checked. |
| Awaiting approval, above the limit | Value [value] [currency] is above the approval limit of 10,000.00 [currency]. |
| Awaiting approval, no price | No price in SAP, so a Manager must approve. |

"10%" and "110%" always show the **current cover buffer** (editable in the CR, D-13). With the CR, when the material's safety stock is above 0, the Short text ends with: `Available = stock minus SAP safety stock of [n] [unit].`

## 6. Formats
- Dates: `03 Nov 2026` in tables and headers; `04 Nov` in compact columns (Needed by, First needed, dashboard). Date and time: `02 Nov 10:11`.
- Quantities: number + space + unit code. Up to 3 decimals; trailing zeros only where the source has them (`8.000 KG` as sent to SAP).
- Money: amount + space + the plant's currency code, `1,250.00 EUR`. Never a hard-coded currency.
- Units: order unit on order screens, stock unit for anything sent to SAP; show both in the review panel (D-16).

## 7. Screenshot map

One image per PDF page. The other states (side panel outcomes in 4.2, requisition statuses in 4.5) have no screenshot: their tables in section 4 and the state logic in `source/02-order-detail.html` and `source/05-requisition-detail.html` are the reference.

| File | Screen / state | Source |
|---|---|---|
| `01-orders.png` | Orders, default | PDF p1 |
| `02-order-detail.png` | Order detail, panel in Review | PDF p2 |
| `03-dashboard.png` | Dashboard | PDF p3 |
| `04-requisitions.png` | Requisitions with approval slide-in open | PDF p4 |
| `05-requisition-detail.png` | Requisition detail, awaiting approval | PDF p5 |
| `06-thresholds.png` | Thresholds | PDF p6 |
| `07-states.png` | System states A–F | PDF p7 |

## 8. Accessibility (applies everywhere)
- Real buttons, links and form fields; every field has a visible label.
- Everything reachable and usable with the keyboard; visible focus outline in `--color-primary`.
- Tooltips open on focus as well as hover.
- Icon-only buttons have a text label for screen readers.
- Status is never shown by colour alone: pills always carry their text.
- Text contrast at least 4.5:1 (the token pairs meet this).
- Click targets at least `--touch-target` high, except compact row buttons (`--control-compact`).
