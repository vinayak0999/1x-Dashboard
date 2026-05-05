---
name: Lumina Ops
colors:
  surface: '#fcf8ff'
  surface-dim: '#dbd8e4'
  surface-bright: '#fcf8ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f5f2fe'
  surface-container: '#efecf8'
  surface-container-high: '#e9e6f3'
  surface-container-highest: '#e4e1ed'
  on-surface: '#1b1b23'
  on-surface-variant: '#464554'
  inverse-surface: '#303038'
  inverse-on-surface: '#f2effb'
  outline: '#767586'
  outline-variant: '#c7c4d7'
  surface-tint: '#494bd6'
  primary: '#4648d4'
  on-primary: '#ffffff'
  primary-container: '#6063ee'
  on-primary-container: '#fffbff'
  inverse-primary: '#c0c1ff'
  secondary: '#006591'
  on-secondary: '#ffffff'
  secondary-container: '#39b8fd'
  on-secondary-container: '#004666'
  tertiary: '#904900'
  on-tertiary: '#ffffff'
  tertiary-container: '#b55d00'
  on-tertiary-container: '#fffbff'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#e1e0ff'
  primary-fixed-dim: '#c0c1ff'
  on-primary-fixed: '#07006c'
  on-primary-fixed-variant: '#2f2ebe'
  secondary-fixed: '#c9e6ff'
  secondary-fixed-dim: '#89ceff'
  on-secondary-fixed: '#001e2f'
  on-secondary-fixed-variant: '#004c6e'
  tertiary-fixed: '#ffdcc5'
  tertiary-fixed-dim: '#ffb783'
  on-tertiary-fixed: '#301400'
  on-tertiary-fixed-variant: '#703700'
  background: '#fcf8ff'
  on-background: '#1b1b23'
  surface-variant: '#e4e1ed'
typography:
  h1:
    fontFamily: Plus Jakarta Sans
    fontSize: 40px
    fontWeight: '700'
    lineHeight: '1.2'
    letterSpacing: -0.02em
  h2:
    fontFamily: Plus Jakarta Sans
    fontSize: 30px
    fontWeight: '600'
    lineHeight: '1.3'
    letterSpacing: -0.01em
  h3:
    fontFamily: Plus Jakarta Sans
    fontSize: 24px
    fontWeight: '600'
    lineHeight: '1.4'
    letterSpacing: -0.01em
  body-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 18px
    fontWeight: '400'
    lineHeight: '1.6'
    letterSpacing: 0.01em
  body-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 16px
    fontWeight: '400'
    lineHeight: '1.6'
    letterSpacing: 0.01em
  label-caps:
    fontFamily: Plus Jakarta Sans
    fontSize: 12px
    fontWeight: '700'
    lineHeight: '1.2'
    letterSpacing: 0.1em
  data-display:
    fontFamily: Plus Jakarta Sans
    fontSize: 32px
    fontWeight: '500'
    lineHeight: '1.1'
    letterSpacing: -0.03em
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 8px
  container-padding: 32px
  gutter: 24px
  card-gap: 24px
  section-margin: 48px
---

## Brand & Style

The design system is engineered for high-stakes operational environments where clarity and prestige intersect. It targets executive leadership and technical operators who require rapid data synthesis without sacrificing aesthetic sophistication.

The visual style is a hybrid of **Minimalism** and **Glassmorphism**. It leverages a "Luxury Tech" aesthetic characterized by expansive white space, precision-engineered typography, and ethereal depth. The emotional response is one of calm control—transforming complex, dense data streams into a breathable, high-end digital experience that feels both professional and "sexy."

## Colors

The palette is anchored by a pure white (#FFFFFF) foundation to maximize light reflectance and perceived "airiness." 

*   **Primary & Secondary:** A vibrant gradient of Sophisticated Purple and Electric Blue is used for high-importance actions, active states, and data visualizations.
*   **Neutrals:** Very subtle light grays (Slate 50/100) define structural boundaries.
*   **Functional Colors:** Success, Warning, and Error states utilize the same luminosity as the primary palette but are applied sparingly to maintain the luxury feel.

## Typography

The typography utilizes **Plus Jakarta Sans** for its modern, geometric clarity and friendly yet professional apertures. 

To achieve the "luxury" feel:
*   **Generous Tracking:** Body text and labels use increased letter spacing to enhance readability and premium feel.
*   **Contrast:** High-contrast weight scales differentiate between data values (medium/semibold) and supportive labels (bold/uppercase).
*   **Data Density:** Large numerical displays use tighter tracking to maintain a compact, technical look within large metrics.

## Layout & Spacing

This design system employs a **Fluid Grid** with fixed maximum constraints. 

*   **Grid:** A 12-column system with a generous 24px gutter to ensure data density does not result in visual clutter.
*   **Rhythm:** An 8px linear scale governs all padding and margins.
*   **Breathability:** Significant "safe areas" (32px+) are maintained around the perimeter of the dashboard to frame the content as a gallery of information rather than a spreadsheet.

## Elevation & Depth

Depth is conveyed through a "Floating Layer" philosophy. 

*   **Ambient Shadows:** Cards use multi-layered, ultra-soft shadows with a slight blue-tinted hue (e.g., `box-shadow: 0 20px 50px rgba(15, 23, 42, 0.05)`).
*   **Glassmorphism:** Secondary elements such as sidebars, dropdown menus, and modal backdrops utilize a backdrop-blur (20px-30px) with a semi-transparent white tint (80% opacity) to create a sense of verticality and material richness.
*   **Borders:** Use 1px solid strokes in #F1F5F9 to provide crisp definition where shadows overlap.

## Shapes

The shape language is sophisticated and approachable. 

*   **Containers:** Main cards and content areas utilize a 24px radius (`rounded-xl` / `rounded-2xl`).
*   **Interactive Elements:** Buttons and input fields use a 12px-16px radius.
*   **Micro-elements:** Tags and badges use pill-shapes (full round) to distinguish them from structural components.

## Components

### Cards
Cards are the primary container. They feature a white background, 24px corner radius, and a subtle light gray border. Data within cards should be grouped using whitespace rather than internal lines.

### Buttons
*   **Primary:** Solid Electric Blue to Purple gradient with white text.
*   **Secondary:** Ghost-style with a subtle border or light glass effect.
*   **State:** Hover states should involve a slight lift (Y-axis translation) and an increase in shadow spread.

### Glass Elements
Use for persistent sidebars or floating action toolbars. Apply a `backdrop-filter: blur(24px)` and a thin 1px white border to simulate polished glass.

### Form Inputs
Minimalist design with no background (transparent) or a very light gray. Focus states transition the border to the primary purple with a soft outer glow.

### Custom Icons
Use thin-stroke (1.5pt) linear icons. Icons should be dual-toned, using a combination of the neutral text color and a small primary-color accent point.

### Data Visualization
Charts should use "glow" effects on lines (area charts) and rounded caps on bar charts. The primary purple and electric blue are the dominant series colors.