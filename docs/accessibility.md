# Accessibility and responsive checks

PlanGuard uses semantic links, buttons, labels, landmarks, and native modal
dialogs. Shared styles provide high-visibility keyboard focus, a skip link,
reduced-motion behavior, text wrapping, and mobile layouts.

Automated tests verify:

- shared navigation and main-content landmarks;
- dialog names, descriptions, initial focus, and trigger-focus restoration;
- accessible labels for assignment actions;
- focus indicators, reduced-motion rules, mobile target sizes, and reflow rules;
- WCAG AA contrast ratios for the primary text palette.

Before a UI release, manually check the dashboard, assignment form, and both
dialogs at 320px, 375px, 768px, and desktop widths:

1. Navigate using only Tab, Shift+Tab, Enter, Space, and Escape.
2. Confirm the skip link appears on focus and moves focus to main content.
3. Open each dialog, confirm focus starts inside it, and close it with its button
   and Escape. Focus should return to the control that opened it.
4. At 200% browser zoom, confirm content reflows without horizontal scrolling or
   clipped text.
5. With reduced motion enabled, confirm transitions are effectively removed.
6. Run a browser accessibility inspector or axe scan and review any new
   violations before merging.
