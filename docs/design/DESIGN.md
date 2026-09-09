# Serverjack Design Direction

This file is intended for coding agents working anywhere in the Serverjack UI. Treat these rules as durable design constraints even while features and information architecture change.

## Design intent

Serverjack should feel like a **modern terminal application**, not a terminal emulator and not a Fallout/Pip-Boy replica. The visual language combines classic monochrome-terminal cues with contemporary product UI: restrained phosphor green, dark surfaces, monospaced display/technical text, translucent overlays, subtle blur, crisp hierarchy, and comfortable touch targets.

Four adjectives: **terminal-native, modern, minimal, powerful**.

Avoid copyrighted/franchise-specific imagery, mascots, Vault-style marks, radiation symbols, faux hardware bezels, distressed metal, or other explicit Fallout references.

## Color tokens

Use semantic tokens rather than scattering literal colors through components.

```css
:root {
  --bg-primary: #080f0e;
  --bg-secondary: #111815;
  --surface: #1a2420;
  --surface-alt: #232e28;
  --border: #2f3f36;

  --text-primary: #e6f7e9;
  --text-secondary: #9fb3a8;
  --text-muted: #8a9b92;

  --accent: #39ff88;
  --accent-dim: #1ed06a;
  --warning: #ffc857;
  --danger: #ff5f56;
  --info: #58a6ff;
  --agent-purple: #c678ff;
}
```

The accent green is precious. Use it for current/active state, primary actions, focus, success/online state, and small pieces of branding. Do not turn whole screens green.

## Typography

- Preferred technical/display face: **Geist Mono** (fallback: `ui-monospace`, `SFMono-Regular`, `Menlo`, `Consolas`, monospace).
- Preferred UI/body face: **Inter** (fallback: system sans-serif).
- Use mono for the wordmark, section labels, commands, paths, session metadata, status text, key hints, terminal output, and other technical information.
- Use Inter for longer explanations, form help, settings descriptions, and dense prose.
- Favor medium/semibold over very heavy weights.
- Uppercase + modest letter spacing is appropriate for small section labels, not normal body copy.
- Numbers, paths, and commands should remain highly legible rather than decorative.

Suggested scale: display 32/40, H1 24/32, H2 20/28, H3 16/24, body-large 16/24, body 14/20, caption/label 12/16.

## Surfaces, transparency, and depth

- The app background should be near-black with a subtle green cast, not pure black.
- Normal content surfaces should be only slightly elevated from the background.
- Use transparency and backdrop blur primarily for transient or layered UI such as bottom sheets, menus, command surfaces, floating navigation, and modal surfaces.
- Glass should remain dark and readable. Never sacrifice contrast for the effect.
- Borders should do more work than shadows. Prefer thin low-contrast borders and restrained highlights.
- Avoid stacks of visually heavy nested cards. Group related content with spacing, dividers, and subtle surface shifts.
- Optional background texture may use extremely faint topographic/contour lines or very subtle scanlines. Texture must disappear perceptually during normal use and must never reduce readability.

## Geometry and spacing

Use an 8px spacing system, with 4px available for micro-spacing. Typical values: 4, 8, 16, 24, 32, 48.

Radius vocabulary: 4px xs, 8px sm, 12px md, 16px lg, 24px xl. Modern rounded geometry is encouraged; do not make everything look like a hard-edged CRT UI.

Interactive controls should have generous hit targets, especially on mobile. Visual density can feel terminal-like while actual interaction remains comfortable.

## Component behavior principles

- Primary actions: bright accent fill with very dark text; reserve for the most important action in a context.
- Secondary actions: dark/translucent surface with accent or neutral border.
- Ghost actions: minimal chrome; use for lower-priority actions.
- Destructive actions: use red only when the action is actually destructive.
- Selected tabs/filters should be obvious through accent, border, fill, or underline without relying on color alone.
- Inputs should feel like command fields: dark, crisp, clearly focused, but still use normal labels/help/error affordances.
- Status indicators should combine color with text/icon/shape where practical.
- Menus and bottom sheets should feel like layered terminal panes: translucent dark material, clear separators, compact icons, and strong focus.
- Notifications should be quiet and compact. Success green, informational blue, warning amber, destructive/error red.

## UX practices

1. **Fast paths first.** This is an operational tool. Frequent actions should feel immediate and require little ceremony.
2. **Progressive disclosure.** Keep routine surfaces simple; expose advanced configuration only when needed.
3. **Preserve context.** Prefer overlays, sheets, menus, and lightweight transitions when an action does not deserve a full context switch.
4. **Show system state.** Starting, connecting, running, stopped, failed, and detached states should be explicit. Never make users infer whether an operation succeeded.
5. **Optimistic only when safe.** Immediate feedback is good, but terminal/session state must reconcile with reality and visibly recover from failure.
6. **Keyboard-friendly by default.** Desktop interactions should support logical tab order, visible focus, Escape to dismiss transient UI, Enter where expected, and shortcuts when discoverable.
7. **Touch-friendly by default.** Mobile should not be a shrunken desktop terminal. Maintain comfortable targets and use native-feeling transient patterns such as bottom sheets.
8. **Accessibility is part of the aesthetic.** Maintain contrast, respect reduced-motion settings, expose semantic labels, and never encode state solely with green/red.
9. **Motion should communicate mechanics.** Use short fades/slides for layer changes and subtle state transitions. Avoid ornamental animation or anything that slows operation. The CRT effects below are the one deliberate exception, and they stay inside the budget in that section.
10. **Terminal flavor comes from typography, color, language, and micro-details—not usability compromises.**

## CRT effects

A small, deliberately cheap CRT costume is allowed on top of the modern look: a
tube warm-up on page load, a collapse-to-a-line when leaving through one of our
own controls, a scanline sweep while the terminal connects, an almost invisible
flicker/roll on the page background, and a static phosphor glow on the wordmark.

Rules:

- **Opacity and transform only.** Those are the properties a compositor can
  animate without repainting. No canvas, no JS animation loop, no animated
  `filter`, no images, no fonts.
- **Everything is gated on `body.fx`**, which the server puts on `<body>`
  (`SERVERJACK_FX=off` leaves it off) and a per-browser toggle overrides via
  `localStorage['sj-fx']`. With the class removed, the UI is pixel-for-pixel what
  it is without the feature.
- **All of it is off under `@media (prefers-reduced-motion: reduce)`**, and the
  static result must look the same as with the effects off.
- **Never over the terminal at rest.** Overlays on `#frame-wrap` are
  `pointer-events:none`, only exist during a transition, and stay under ~6%
  alpha for any wash. The iframe's own content (ttyd/xterm) is never touched.
- **No franchise references.** No mascots, vault marks, radiation symbols or
  faux hardware bezels — this is a phosphor tube, not a prop.
- **Budget:** the whole feature is roughly 120 lines of CSS + JS + markup. If an
  effect costs more than that, it is not wanted.

## Copy and voice

Use concise, technical, calm language. Labels can borrow terminal vocabulary where it is immediately understandable (`Open`, `Attach`, `Running`, `Command`, `Directory`), but do not turn normal UI into role-play or fake command syntax.

The brand line is **“Jack into your server.”** Keep this flavor mostly in branding/empty states rather than every control.

## Icons

Use simple outline icons with consistent stroke weight. Terminal prompt, folder, agent/bot, play, grid, gear, plus, search, overflow, link/attach, and status-dot motifs fit well. Avoid franchise-specific iconography.

## Agent implementation rules

When implementing or refactoring UI:

- Reuse semantic theme tokens; add a token only when a genuinely reusable semantic role is missing.
- Do not introduce one-off arbitrary greens, grays, radii, shadows, or font sizes.
- Keep feature structure/layout decisions separate from the theme layer so rapidly changing product flows can evolve without rewriting the visual system.
- Prefer reusable primitives for surface, text, button, field, status, overlay, and focus treatment.
- Check the result in narrow mobile and desktop widths.
- Check keyboard focus and reduced-motion behavior.
- Keep effects subtle enough that removing blur/texture would not break the hierarchy.
- When uncertain, choose the cleaner/more modern option rather than increasing retro decoration.

## Implementation constraints for serverjack

- **System fonts only.** No webfont downloads: use the fallback stacks (`ui-monospace, SFMono-Regular, Menlo, Consolas, monospace` and `system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`). The page must work offline and anywhere.
- **No external assets.** Everything inline in `bin/serverjack`; no CDN, no icon fonts. Icons are inline SVG or plain glyphs.
- **The terminal itself is ttyd's xterm.js.** Its theming is out of scope for the UI layer; only the wrapper bar, soft keys, compose bar and the landing page follow this document.
- The reference design boards are not checked in (large PNGs); the tokens above are the source of truth.
