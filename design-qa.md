# Customer Inbox redesign — design QA

## Evidence

- Source visual truth: `/Users/zhuli/.codex/generated_images/019f50ad-93c7-7803-8ffb-0d1af4bc1497/exec-b843d3c4-6775-4951-b67d-15d1d72535b0.png`
- Desktop implementation: `/tmp/giffgaff-ui-redesign-desktop-detail-final.png`
- Mobile list implementation: `/tmp/giffgaff-ui-redesign-mobile-list-final.png`
- Mobile detail implementation: `/tmp/giffgaff-ui-redesign-mobile-detail-final.png`
- Full-view comparison: `/tmp/giffgaff-ui-final-side-by-side.png`
- Focused detail comparison: `/tmp/giffgaff-ui-final-detail-side-by-side.png`
- Desktop viewport: `1487 × 1058`, first customer selected, detail at top.
- Mobile viewport: `390 × 844`, list and first-customer detail states.

## Findings

No actionable P0, P1, or P2 issue remains.

- [P3] The implementation uses text-only main navigation while the visual target includes decorative navigation icons.
  - Evidence: the three-column hierarchy, labels, active treatment, and spacing remain clear without icon assets.
  - Impact: minor visual fidelity difference with no loss of navigation clarity.
  - Follow-up: add a bundled icon-library set in a later visual-only pass if desired; no placeholder glyphs or handcrafted SVGs were added.
- [P3] The customer list is slightly wider and the detail surface uses editable cards instead of the target's mostly read-only key/value rows.
  - Evidence: source and implementation in `/tmp/giffgaff-ui-final-detail-side-by-side.png`.
  - Impact: the detail pane is denser vertically, but editing, copy actions, and all existing operational fields remain directly available.
  - Follow-up: optional compact read/edit modes could tighten density later without changing the current workflow.

## Required fidelity surfaces

- Fonts and typography: both views use a compact system-sans hierarchy; headings, monospace values, metadata, badges, and controls remain legible without clipping. Mobile wrapping was checked at 390 px.
- Spacing and layout rhythm: the selected master/detail direction is preserved with a fixed header, vertical navigation, compact customer list, and independently scrolling detail. Sections use consistent 8–22 px spacing and aligned two-column fields on desktop.
- Colors and visual tokens: the purple header/selection system, white work surfaces, light dividers, and semantic status badges match the source direction with sufficient foreground contrast.
- Image quality and asset fidelity: the target contains no required product photography or illustration. The implementation adds no placeholder image, CSS drawing, handcrafted SVG, or fake visual asset.
- Copy and content: existing customer-management terminology and all operational fields are preserved. Label printing and courier printing are explicitly separated, and no sender-address UI is present.
- Responsive behavior: desktop has no horizontal overflow. Mobile detail occupies the full `390 × 844` viewport, opens at scroll position 0, starts on “账号与身份”, and returns through the visible “返回客户列表” control. Mobile navigation remains a single horizontally scrollable row with its scrollbar hidden.
- Accessibility and states: customer rows support keyboard activation, buttons retain accessible names, search and form controls have visible labels/placeholders, and the console reported zero errors or warnings in the final desktop and mobile checks.

## Primary interactions tested

- Expand and collapse “快速添加客户”.
- Search by exact phone number and receive one matching customer.
- Open a customer through the row “查看” button.
- Use continuous-section navigation; “发货” scrolls to its section and receives the active state.
- Open mobile detail from the list, verify top position, then return to the list.
- Open “打印标签”: normal default template selector is visible and selects `basic-50x30` in the fixture.
- Open “打印快递单”: title changes, template selector container is hidden, and `courier-50x40` is selected.
- Confirm final browser console has zero errors and warnings.

## Comparison history

### Iteration 1

- [P1] The “查看” button received focus but did not open the detail pane because a capture-phase propagation handler intercepted the button callback.
  - Fix: removed the redundant capture listener; the button's own handler still stops row propagation after calling `viewCustomer`.
  - Post-fix evidence: `/tmp/giffgaff-ui-redesign-desktop-detail-final.png` shows the selected customer and populated detail.
- [P1] Mobile detail retained an earlier desktop section scroll and active navigation item.
  - Fix: every `viewCustomer` call now resets the detail scroller to 0 and restores “账号与身份” as the active section.
  - Post-fix evidence: `/tmp/giffgaff-ui-redesign-mobile-detail-final.png`; measured `scrollTop = 0`.
- [P2] Mobile exposed a redundant close icon and visible horizontal navigation scrollbar.
  - Fix: retained the labeled back action, hid the duplicate close button at the mobile breakpoint, and visually hid scrollbars while preserving touch scrolling.
  - Post-fix evidence: `/tmp/giffgaff-ui-redesign-mobile-list-final.png` and `/tmp/giffgaff-ui-redesign-mobile-detail-final.png`.

### Iteration 2

- Re-captured desktop and mobile at the required viewports.
- Re-ran the full-view and focused comparisons.
- No actionable P0/P1/P2 differences remain; only the two P3 follow-up items above remain.

## Implementation checklist

- [x] Customer Inbox three-column desktop workspace.
- [x] Continuous detail sections and sticky section navigation.
- [x] Full-screen mobile detail with labeled return action.
- [x] Separate label and courier print flows.
- [x] Persistent default label template support.
- [x] Existing customer, email, activation, QR, and shipping functions preserved.
- [x] Worker `API_BASE` and public QR implementation unchanged.
- [x] Browser, backend, Worker, JavaScript syntax, and diff checks passed.

final result: passed
