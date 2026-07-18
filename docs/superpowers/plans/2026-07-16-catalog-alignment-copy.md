# Catalog Alignment And Neutral Copy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove named pharmacy-app references and make the catalog, modal, policy, and supporting sections share clear alignment rules on desktop and mobile.

**Architecture:** Preserve the existing component hierarchy and product data. Fix copy in the two visitor-facing pages, move initial dialog focus from the close button to the dialog container, and correct shared CSS alignment rules instead of adding product-specific exceptions.

**Tech Stack:** Next.js, React, TypeScript, CSS, Node test runner, Playwright CLI.

---

### Task 1: Replace named-service copy

**Files:**
- Modify: `app/catalog-client.tsx`
- Modify: `app/data-policy/page.tsx`
- Test: `tests/rendered-html.test.mjs`

- [ ] **Step 1: Add failing copy assertions**

Add assertions that rendered HTML contains `공개 자료의 출처를 확인해 정리한` and does not contain `메가팩토리약국` or `창고형약국 약값체크`.

- [ ] **Step 2: Run the rendered regression test**

Run: `node --test tests/rendered-html.test.mjs`

Expected: FAIL until visitor-facing copy is replaced.

- [ ] **Step 3: Replace footer and policy copy**

Use neutral wording about public sources and independence. Keep price, provenance, image-rights, correction, and publication-limit warnings intact.

- [ ] **Step 4: Run the rendered regression test**

Run: `node --test tests/rendered-html.test.mjs`

Expected: PASS.

### Task 2: Correct dialog focus and product-summary alignment

**Files:**
- Modify: `components/catalog/ProductModal.tsx`
- Modify: `components/catalog/ExportDialog.tsx`
- Modify: `app/globals.css`
- Test: `tests/rendered-html.test.mjs`

- [ ] **Step 1: Add dialog-focus and layout assertions**

Assert that both dialogs use `tabIndex={-1}`, focus their dialog container, and that the desktop product grid uses a compact fixed image column with `align-items: start`.

- [ ] **Step 2: Move initial focus to each dialog container**

Focus the dialog section with `focus({ preventScroll: true })`. When Tab or Shift+Tab starts on the container, move focus to the first or last interactive control and keep the existing focus trap.

- [ ] **Step 3: Align product image and copy from the top**

Add `modal-product-copy`, reduce the desktop image column, and keep the existing compact mobile two-column layout.

- [ ] **Step 4: Run type and rendered tests**

Run: `npm run typecheck && node --test tests/rendered-html.test.mjs`

Expected: PASS.

### Task 3: Correct shared row and section alignment

**Files:**
- Modify: `app/globals.css`
- Test: `tests/rendered-html.test.mjs`

- [ ] **Step 1: Add an odd-detail-row regression assertion**

Assert that a final odd detail item spans both desktop columns and that the second-to-last border is removed only for even rows.

- [ ] **Step 2: Fix detail rows and supporting columns**

Make odd final detail items span the row, keep mobile rows single-column, give principle numbers and source icons fixed widths, and align the footer and policy link from a stable start edge.

- [ ] **Step 3: Keep catalog heading copy together**

Place the catalog description directly below the heading on desktop and mobile instead of at the far right edge.

- [ ] **Step 4: Run focused tests**

Run: `node --test tests/rendered-html.test.mjs`

Expected: PASS.

### Task 4: Verify without publishing

**Files:**
- Verify: `app/catalog-client.tsx`
- Verify: `app/data-policy/page.tsx`
- Verify: `components/catalog/ProductModal.tsx`
- Verify: `components/catalog/ExportDialog.tsx`
- Verify: `app/globals.css`

- [ ] **Step 1: Run all automated checks**

Run: `npm run typecheck`, `npm run lint`, `npm run test:unit`, `node --test tests/rendered-html.test.mjs`, and `npm run build:static`.

Expected: every command exits with code 0.

- [ ] **Step 2: Inspect real layouts**

Use Playwright at 1920×1080, 1440×900, 1024×900, and 390×844. Check the home/catalog view, a product with no detail rows, product `20250812_113116` with 3 detail rows, a long official-information modal, the export dialog, and the policy page.

- [ ] **Step 3: Confirm no named references or overflow**

Run `rg -n "메가팩토리|창고형약국|약값체크" app components tests` and verify zero visitor-facing matches. Confirm `document.documentElement.scrollWidth === window.innerWidth` at desktop and mobile widths.

- [ ] **Step 4: Leave changes local**

Do not commit, push, or deploy until the user gives a separate publishing instruction.
