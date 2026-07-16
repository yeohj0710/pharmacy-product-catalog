# Catalog Density Design Implementation Plan

> **Execution note:** Implement this plan inline in the current task. The user explicitly prohibited subagents.

**Goal:** Make the catalog feel compact and cohesive on desktop and mobile without reducing Korean text readability or changing product data.

**Architecture:** Keep the existing React structure and correct the shared layout cause in `app/globals.css`. Introduce one content-width token, tighten repeated section spacing and control dimensions, then add focused rendered-CSS regression checks. Preserve the existing modal text compaction and official-data rendering behavior.

**Tech Stack:** Next.js, React, TypeScript, CSS, Node test runner, Playwright CLI.

---

### Task 1: Establish shared density rules

**Files:**
- Modify: `app/globals.css`
- Test: `tests/rendered-html.test.mjs`

1. Add shared content-width and gutter tokens.
2. Align the header, hero, summary, catalog, principles, and footer to the same content width.
3. Add a CSS regression test for the shared width token and key compact dimensions.

### Task 2: Tighten the catalog browsing surface

**Files:**
- Modify: `app/globals.css`

1. Reduce hero and section vertical whitespace.
2. Reduce summary-card, toolbar, filter-panel, table-row, mobile-card, pagination, and selection-bar spacing.
3. Keep interactive controls at least 44px high and retain visible focus styles.
4. Preserve readable body text and existing long-text wrapping.

### Task 3: Tighten supporting pages and responsive layouts

**Files:**
- Modify: `app/globals.css`

1. Compact the data-principles section, footer, export dialog, and data-policy page.
2. Apply mobile-specific spacing so the catalog begins earlier without shrinking text below readable sizes.
3. Verify no horizontal overflow at 390px, 1024px, and 1440px.

### Task 4: Verify the full result

**Files:**
- Verify: `app/globals.css`
- Verify: `components/catalog/ProductModal.tsx`
- Verify: `tests/catalog-utils.test.ts`
- Verify: `tests/rendered-html.test.mjs`

1. Run `npm run typecheck`, `npm run lint`, `npm run test:unit`, `node --test tests/rendered-html.test.mjs`, and `npm run build:static`.
2. Inspect desktop, tablet, and mobile screens with Playwright.
3. Check the product modal and data-policy page as well as the home/catalog screen.
4. Keep all changes local; do not commit, push, or deploy without a separate instruction.
