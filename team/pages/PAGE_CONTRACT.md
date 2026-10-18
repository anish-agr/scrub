# Page contract for published artifact pages (follow exactly)
- Write page content directly: NO <!doctype>, <html>, <head>, <body> tags. Start the file with <title> (2-4 word name, no colon/dash explainer), then <link> Google Fonts, then <style>, then markup, then <script>.
- Scripts only from cdnjs.cloudflare.com (pinned version, UMD). Fonts only from Google Fonts with real fallback stacks. No other external resources, no iframes of other sites, no alert/confirm/prompt, no print buttons, no <a download>.
- Theme: every color is a CSS token defined on bare :root (light), redefined in `@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){... color-scheme:dark}}` AND `:root[data-theme="dark"]{... color-scheme:dark}`. body sets background: var(--bg). No literal colors in component rules.
- Responsive: works at 390px, no horizontal page scroll, 16px side gutter on body via padding-inline (use padding-block for vertical). Wide tables go in their own overflow-x:auto wrapper. min-width:0 on grid/flex children holding text.
- Complete at rest: nothing hidden at opacity 0 waiting for scroll. Respect prefers-reduced-motion. Visible focus states.
- Design: deliberate type pairing (avoid Inter, Space Grotesk, Roboto); avoid cream+terracotta serif look, purple gradients, emoji section markers, everything centered, identical rounded shadowed cards everywhere. Use tabular-nums for numbers. Semantic color for good/warn/critical.
- Copy: plain, direct, no em dashes, no "not X but Y", no stock phrases. Keep [UNVERIFIED]/[U] markers visible as a small "unverified" chip so the team knows what to check. Keep source links as real <a href target="_blank" rel="noopener">.
- Charts: inline SVG drawn to scale, labels from theme tokens, explicit fills.
