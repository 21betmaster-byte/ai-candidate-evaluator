# Design System Document: The Editorial Intelligence

## 1. Overview & Creative North Star
The "Creative North Star" for this design system is **The Digital Curator**. 

In an industry often defined by cold, mechanical spreadsheets, this system pivots toward an editorial, high-end experience. It treats candidate data not as rows in a database, but as profiles in a premium publication. By moving away from the rigid, "boxed-in" layout of traditional SaaS dashboards, we employ a sophisticated interplay of **Tonal Layering** and **Intentional Asymmetry**. 

The goal is to foster a sense of "Calm Authority." We achieve this through expansive white space, a rejection of harsh structural lines, and a typography scale that favors dramatic contrasts between large, expressive headlines and highly legible, functional data labels.

---

## 2. Colors: The Tonal Depth Philosophy
Our palette is anchored by the deep, authoritative `#1C0715` and balanced by the warmth of `#FD4077`. We move beyond flat color application to create a living, breathing interface.

### The "No-Line" Rule
**Explicit Instruction:** Designers are prohibited from using 1px solid borders for sectioning or containment. 
Boundaries must be defined solely through background color shifts. For example, a `surface-container-low` section should sit on a `surface` background. If you feel the need for a line, use a 16px or 24px vertical gap from the spacing scale instead.

### Surface Hierarchy & Nesting
Treat the UI as a series of physical layers—like stacked sheets of fine, heavy-stock paper.
*   **Base Layer:** `surface` (#fff8f9) for the primary application background.
*   **Secondary Sections:** `surface-container-low` (#fff0f5) for sidebar navigation or inactive panels.
*   **Actionable Containers:** `surface-container-lowest` (#ffffff) for primary cards to create a natural "pop" against the off-white background.
*   **Elevated Detail:** `surface-container-high` (#ffe0ef) for temporary states like hover-overs or tooltips.

### The "Glass & Gradient" Rule
To ensure the hiring dashboard feels modern and bespoke:
*   **Floating Elements:** Modals and dropdowns must use Glassmorphism. Apply `surface-container-lowest` at 80% opacity with a `20px` backdrop-blur.
*   **Signature Textures:** For high-value actions (e.g., "Hire Candidate"), use a subtle linear gradient from `primary` (#b8004a) to `primary-container` (#dd2561) at a 135-degree angle. This adds a "soul" to the UI that flat colors cannot replicate.

---

## 3. Typography: Editorial Authority
The typography system relies on a high-contrast pairing: **Epilogue** for bold, expressive personality and **Inter** for clinical, data-driven precision.

*   **Display & Headlines (Epilogue):** Used for candidate names and high-level dashboard metrics. The generous sizing of `display-lg` (3.5rem) should be used sparingly to create focal points, establishing an "Editorial" hierarchy.
*   **Body & Titles (Inter):** Used for all functional data, descriptions, and candidate bios. Inter’s neutral character balances the personality of Epilogue, ensuring the dashboard remains a tool of efficiency.
*   **Labels (Plus Jakarta Sans):** Small-scale metadata (e.g., "Time in Stage" or "Salary Expectation") uses `label-md` (0.75rem). This ensures that even at small sizes, the dashboard feels sophisticated and "designed."

---

## 4. Elevation & Depth: Tonal Layering
Traditional shadows and borders are replaced by a physics-based layering approach.

*   **The Layering Principle:** Depth is achieved by stacking. A `surface-container-lowest` card placed on a `surface-container` background creates a soft, natural lift without the "dirtiness" of dark shadows.
*   **Ambient Shadows:** Where a floating effect is required (e.g., a "Quick View" candidate drawer), use an extra-diffused shadow: `0px 12px 32px rgba(43, 20, 35, 0.06)`. Note the color: the shadow is a tinted version of `on-surface`, never pure black or grey.
*   **The "Ghost Border" Fallback:** If accessibility requires a stroke (e.g., high-contrast mode), use the `outline-variant` token at **15% opacity**. A 100% opaque border is a failure of the system.
*   **Glassmorphism Depth:** Use backdrop-blur for all top-level navigation headers (Z-index: 1000). This allows the colors of the dashboard content to "bleed" through as the user scrolls, creating a sense of continuity.

---

## 5. Components: Styled for Efficiency

### Buttons
*   **Primary:** Gradient of `primary` to `primary-container`. `9999px` (full) roundedness. No border. Text is `on-primary`.
*   **Secondary:** `surface-container-highest` background. No border. `md` (0.375rem) roundedness.
*   **Tertiary:** Ghost style. No background or border. Text uses `primary` (#b8004a).

### Cards & Lists
*   **Constraint:** Never use divider lines.
*   **Styling:** Use a 24px vertical margin between list items. Use a `surface-container-low` background for the entire list area and `surface-container-lowest` for the individual list items to create separation.

### Input Fields
*   **Background:** `surface-container-lowest`. 
*   **Bottom Border Only:** To maintain the editorial look, use a 2px bottom border in `outline-variant` instead of a full box. Upon focus, the border transitions to `primary`.

### Candidate Insight Chips
*   **Selection Chips:** Use `secondary-container` (#cec9ff) with `on-secondary-container` text. Use `full` roundedness to distinguish from functional data boxes.

### Dashboard-Specific Components
*   **The Progress Ribbon:** For candidate pipelines, do not use "Chevrons." Use a continuous horizontal bar with varying tonal saturations of `primary-fixed` to `primary`.
*   **Metric Tiles:** Large `headline-lg` numbers in `primary` color, sitting on a `surface-container-lowest` card. No icons—let the typography do the work.

---

## 6. Do's and Don'ts

### Do
*   **Embrace Negative Space:** If a screen feels "empty," don't add more lines. Increase the font size of the header or increase the padding.
*   **Use Subtle Color Shifts:** To highlight a "New" application, change the background of that row to `surface-container-highest` rather than adding a "New" badge.
*   **Align to a Soft Grid:** While the layout is asymmetrical, elements should still align to a 8px baseline grid to maintain underlying professional rigor.

### Don't
*   **Don't use pure #000000:** Always use `on-surface` (#2b1423) for text to maintain the "Plum" inspired warmth.
*   **Don't use 1px borders:** Even for checkboxes, prefer a soft `outline-variant` fill that fills with `primary` when checked.
*   **Don't crowd the data:** If a table has more than 6 columns, use a "Master-Detail" view rather than shrinking the text.