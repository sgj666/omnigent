---
name: Atmospheric Precision
colors:
  surface: '#0d141b'
  surface-dim: '#0d141b'
  surface-bright: '#333a42'
  surface-container-lowest: '#080f16'
  surface-container-low: '#151c24'
  surface-container: '#192028'
  surface-container-high: '#242b33'
  surface-container-highest: '#2e353e'
  on-surface: '#dce3ee'
  on-surface-variant: '#c2c8c3'
  inverse-surface: '#dce3ee'
  inverse-on-surface: '#2a3139'
  outline: '#8c928e'
  outline-variant: '#424845'
  surface-tint: '#b1cdc0'
  primary: '#e1fef0'
  on-primary: '#1d352c'
  primary-container: '#c5e1d4'
  on-primary-container: '#4c655b'
  inverse-primary: '#4a6459'
  secondary: '#c1c7cf'
  on-secondary: '#2b3137'
  secondary-container: '#41474e'
  on-secondary-container: '#b0b6bd'
  tertiary: '#f5f7fc'
  on-tertiary: '#2e3135'
  tertiary-container: '#d9dae0'
  on-tertiary-container: '#5d5f64'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#cde9dc'
  primary-fixed-dim: '#b1cdc0'
  on-primary-fixed: '#062018'
  on-primary-fixed-variant: '#334c42'
  secondary-fixed: '#dde3eb'
  secondary-fixed-dim: '#c1c7cf'
  on-secondary-fixed: '#161c22'
  on-secondary-fixed-variant: '#41474e'
  tertiary-fixed: '#e1e2e8'
  tertiary-fixed-dim: '#c5c6cc'
  on-tertiary-fixed: '#191c20'
  on-tertiary-fixed-variant: '#44474b'
  background: '#0d141b'
  on-background: '#dce3ee'
  surface-variant: '#2e353e'
typography:
  display-lg:
    fontFamily: Hanken Grotesk
    fontSize: 48px
    fontWeight: '600'
    lineHeight: 56px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Hanken Grotesk
    fontSize: 24px
    fontWeight: '500'
    lineHeight: 32px
    letterSpacing: -0.01em
  body-base:
    fontFamily: Hanken Grotesk
    fontSize: 15px
    fontWeight: '400'
    lineHeight: 24px
    letterSpacing: 0em
  body-sm:
    fontFamily: Hanken Grotesk
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 20px
    letterSpacing: 0em
  label-caps:
    fontFamily: Hanken Grotesk
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 16px
    letterSpacing: 0.08em
  mono-data:
    fontFamily: Geist Mono
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 20px
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  base_unit: 4px
  gutter: 16px
  margin-desktop: 40px
  margin-mobile: 16px
  container-max: 1600px
---

## Brand & Style
The design system embodies "Atmospheric Precision," a visual philosophy tailored for high-stakes AI orchestration. It prioritizes a calm, architectural environment that facilitates deep work and complex decision-making. The aesthetic rejects the frenetic energy of typical startups in favor of a stable, expert-grade interface.

The style is defined by **Minimalism** blended with **Modern Corporate** sensibilities. It utilizes heavy whitespace—not as empty space, but as a structural tool to separate high-density data modules. Surfaces are treated like physical layers of slate and glass, using subtle translucency and precise alignments to create a sense of organized power. The emotional response is one of total control, reliability, and quiet intelligence.

## Colors
The palette is rooted in a monochromatic range of "Deep Charcoal" and "Muted Slate," providing a low-strain background for prolonged professional use. 

- **Glacial Mint (#C5E1D4):** Used exclusively for high-priority actions, active states, and critical AI insights. It should be applied sparingly to maintain its "signature" status.
- **Surface Hierarchy:** 
    - `Base`: #0F1113 (The foundational canvas)
    - `Surface-Low`: #1A1D21 (Primary containers)
    - `Surface-Mid`: #2D3339 (Interactive elements)
- **Light Mode:** When toggled, the palette shifts to a "Paper and Ink" logic. Surfaces become light greys (#F8F9FA) with text moving to Deep Charcoal. The Glacial Mint remains the primary accent, though its saturation may be slightly adjusted for legibility against white.

## Typography
The system uses **Hanken Grotesk** across all primary roles to ensure a modern, balanced, and highly legible experience. 

- **Scale:** The scale is tight, designed for high-density information display. 
- **Hierarchy:** Use `label-caps` for metadata, table headers, and overlines to provide a structural rhythm without occupying excessive vertical space.
- **Technical Data:** While Hanken Grotesk is the primary font, numerical data or AI-generated logs should utilize a monospaced font (like Geist Mono) to emphasize precision.
- **Mobile Adaptation:** On mobile devices, `display-lg` scales down to 32px to prevent excessive wrapping, while body text remains consistent to preserve readability.

## Layout & Spacing
The layout follows a **Rigid Grid** philosophy tailored for desktop power users. It uses a 12-column grid system with 16px gutters, allowing for complex multi-pane workflows.

- **Orchestration View:** Use a 3-pane layout: 
    1. Navigation/Context (Left, 240px fixed)
    2. Primary Workspace (Center, fluid)
    3. Inspector/Details (Right, 320px fixed)
- **Spacing Rhythm:** All spacing must be multiples of 4px. Use generous internal padding within cards (24px) to balance high-density data with visual breathing room. 
- **Reflow:** On smaller screens, the Inspector pane collapses into an overlay, and the Primary Workspace takes precedence.

## Elevation & Depth
Depth is achieved through **Tonal Layering** and **Atmospheric Blurs** rather than traditional drop shadows.

- **Surfaces:** Use shifts in background hex codes to indicate hierarchy. The deeper the element (base), the darker the color. Elevated elements (modals, popovers) use a lighter slate with a subtle backdrop filter (blur: 12px).
- **Borders:** Every container must have a 1px solid border. In dark mode, use `rgba(255, 255, 255, 0.05)`. In light mode, use `rgba(0, 0, 0, 0.08)`. This creates a "blueprint" feel that emphasizes structural precision.
- **Inner Glow:** Interactive elements in a "hover" state should receive a subtle 1px inner border of the primary color at 20% opacity to signal focus.

## Shapes
The shape language is "Soft-Precision." It avoids the playfulness of hyper-rounded corners in favor of a technical, architectural look. 

- **Base Radius:** 4px (Soft) for buttons and inputs.
- **Container Radius:** 8px (Large) for cards and main workspace modules.
- **Selection Indicators:** Use sharp, vertical 2px bars (Glacial Mint) on the left side of active list items to indicate focus without relying solely on background color shifts.

## Components
- **Buttons:** Primary buttons use the Glacial Mint background with dark text. Secondary buttons are ghost-style with the `rgba(255,255,255,0.05)` border. No gradients.
- **Input Fields:** Background should be 5% darker than the surface they sit on. Focus state is a 1px border of Glacial Mint with no outer glow.
- **Status Chips:** Use a "dot + label" system. The dot uses the status color (Success/Warning/Error), while the chip background remains a muted version of the surface color.
- **Data Tables:** Row lines should be the same 5% opacity border used for containers. Use `label-caps` for headers.
- **AI Orchestration Nodes:** Visual representations of AI logic should appear as cards with the subtle backdrop blur and 1px borders, connected by thin, 1px anti-aliased lines in Muted Slate.
- **Scrollbars:** Custom-styled to be ultra-thin (4px) and Muted Slate, appearing only on hover to reduce visual noise.