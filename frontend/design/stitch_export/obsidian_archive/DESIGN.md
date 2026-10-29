---
name: Obsidian Archive
colors:
  surface: '#f8f9fb'
  surface-dim: '#d8dadc'
  surface-bright: '#f8f9fb'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f2f4f6'
  surface-container: '#eceef0'
  surface-container-high: '#e6e8ea'
  surface-container-highest: '#e0e3e5'
  on-surface: '#191c1e'
  on-surface-variant: '#44474b'
  inverse-surface: '#2d3133'
  inverse-on-surface: '#eff1f3'
  outline: '#74777b'
  outline-variant: '#c4c6cb'
  surface-tint: '#575f68'
  primary: '#000000'
  on-primary: '#ffffff'
  primary-container: '#141c24'
  on-primary-container: '#7d858e'
  inverse-primary: '#bfc7d1'
  secondary: '#904d00'
  on-secondary: '#ffffff'
  secondary-container: '#fe932c'
  on-secondary-container: '#663500'
  tertiary: '#000000'
  on-tertiary: '#ffffff'
  tertiary-container: '#0b1f13'
  on-tertiary-container: '#738978'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#dbe3ed'
  primary-fixed-dim: '#bfc7d1'
  on-primary-fixed: '#141c24'
  on-primary-fixed-variant: '#404850'
  secondary-fixed: '#ffdcc3'
  secondary-fixed-dim: '#ffb77d'
  on-secondary-fixed: '#2f1500'
  on-secondary-fixed-variant: '#6e3900'
  tertiary-fixed: '#d0e9d4'
  tertiary-fixed-dim: '#b5ccb9'
  on-tertiary-fixed: '#0b1f13'
  on-tertiary-fixed-variant: '#374c3d'
  background: '#f8f9fb'
  on-background: '#191c1e'
  surface-variant: '#e0e3e5'
typography:
  display-hero:
    fontFamily: Plus Jakarta Sans
    fontSize: 56px
    fontWeight: '700'
    lineHeight: 64px
    letterSpacing: -0.03em
  display-hero-mobile:
    fontFamily: Plus Jakarta Sans
    fontSize: 36px
    fontWeight: '700'
    lineHeight: 44px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 40px
    fontWeight: '600'
    lineHeight: 48px
    letterSpacing: -0.025em
  headline-lg-mobile:
    fontFamily: Plus Jakarta Sans
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 36px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 36px
    letterSpacing: -0.02em
  headline-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.015em
  body-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
    letterSpacing: -0.01em
  body-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 15px
    fontWeight: '400'
    lineHeight: 24px
    letterSpacing: 0em
  body-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 20px
    letterSpacing: 0.005em
  label-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
    letterSpacing: 0.02em
  label-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.04em
  label-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 10px
    fontWeight: '600'
    lineHeight: 14px
    letterSpacing: 0.08em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 1.5rem
  gutter-mobile: 1rem
  margin: 3rem
  margin-mobile: 1.25rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.75rem
  space-xl: 3rem
---

## Brand & Style

This design system embodies an editorial, gallery-grade visual archive designed for curators, visual artists, and cultural institutions. The brand ethos bridges timeless museum curation with modern digital velocity. 

The aesthetic is grounded in **Editorial Modernism** infused with **Structured Glassmorphism**. It combines expansive white space, museum-calibrated margins, high-contrast mineral typography, and translucent frosted overlays that echo framed museum vitrines. Visual hierarchy relies on razor-sharp contrast between deep mineral obsidian and luminous paper canvases, warmed by intentional pulses of sunlit ochre. The tone evokes quiet confidence, intellectual rigor, and tactile sophistication without overshadowing the archival imagery it presents.

## Colors

The palette establishes an architectural contrast ratio between deep mineral tones and airy paper surfaces:

- **Primary (`#0D151C`)**: Deep Mineral Obsidian. Used for high-priority typography, sharp structural hairline borders, heavy editorial mastheads, and primary interactive states.
- **Secondary (`#D97706`)**: Sunlit Ochre. Used selectively for archival index tags, curated metadata highlights, interactive focal points, and focused badge states.
- **Tertiary (`#849B89`)**: Soft Sage. A muted organic accent deployed for secondary classification tags, preservation statuses, and muted historical notes. A companion earthy terracotta (`#C86D51`) may be utilized strictly for destructive states or rare physical archive flags.
- **Neutral Canvas (`#F3F5F7`)**: Cool Alabaster. The foundation base that simulates premium heavy-stock archival paper, backed by pure `#FFFFFF` surface containers and `#E2E8F0` hairline dividers.

## Typography

Typography relies on a unified, geometric yet warm grotesque execution via **Plus Jakarta Sans**. 

- **Display & Headlines**: Tightly kerned with negative letter spacing to project authority, editorial gravity, and modern publishing prestige. Headings must avoid loose tracking.
- **Body Text**: Calibrated for extended reading of curatorial essays, provenance records, and historical manifests. Generous line heights ensure readability against stark alabaster backdrops.
- **Labels & Archival Metadata**: Scaled down with wide tracking (`0.04em` to `0.08em`) and medium/semibold weights to evoke precision archival indexing, accession stamping, and gallery placard notations.

## Layout & Spacing

The layout model is anchored on an asymmetric 12-column responsive fluid grid with generous, exhibition-grade negative margins.

- **Desktop (1200px+)**: 12 columns with `3rem` section margins and `1.5rem` gutters. Content spreads utilize asymmetrical distribution—image assets occupy wider spans (7–9 columns) while curatorial prose resides in narrow, focused reading rails (3–4 columns).
- **Tablet (768px – 1199px)**: 8 columns with `2rem` margins and `1.25rem` gutters. Two-up gallery views collapse gracefully into staggered offsets.
- **Mobile (< 768px)**: 4 columns with `1.25rem` outer margins and `1rem` gutters. Gallery grids transition to single-column full-bleed exhibition views with stacked meta blocks.
- **Vertical Rhythm**: Spacing scales follow geometric steps, prioritizing large spatial breathing room (`space-xl` and above) around photography framing to preserve editorial gravitas.

## Elevation & Depth

Visual hierarchy rejects exaggerated drop shadows in favor of **Tonal Glassmorphism** paired with **Razor Hairline Borders**:

1. **Surface Base (Level 0)**: Cool Alabaster (`#F3F5F7`), completely flat, textureless, mimicking matte gallery walls.
2. **Exhibition Glass (Level 1)**: Translucent overlays (`rgba(255, 255, 255, 0.72)`) backed by a `16px` backdrop-blur and a `1px` structural outline (`rgba(13, 21, 28, 0.08)`). Used for sticky filter rails, contextual floating toolbars, and metadata drawers.
3. **Placard Floating (Level 2)**: Used for active modals, context menus, and expanded artwork inspect views. Elevated through a crisp mineral border (`rgba(13, 21, 28, 0.12)`) and an ambient, low-opacity shadow tinted with the mineral obsidian hue: `0 20px 40px -12px rgba(13, 21, 28, 0.08)`.
4. **Vitrines & Overlays (Level 3)**: Pure `#0D151C` modal shields at `85%` opacity, allowing faint gallery silhouettes to emerge beneath full-screen high-resolution lightboxes.

## Shapes

The design system employs a **Soft (`1`)** shape language, prioritizing strict architectural discipline:

- Base interactive items, chips, inputs, and standard buttons utilize a subtle `0.25rem` (4px) corner radius to avoid brutalist harshness while remaining clean and rectangular.
- Image vitrines, modal panels, and surface cards feature a `rounded-lg` radius of `0.5rem` (8px), mirroring cut matboards and modern framed exhibits.
- Circular elements are restricted strictly to media controls, audio playheads, and zoom toggles. Pill-shaped components are explicitly avoided to preserve museum-grade dignity.

## Components

- **Buttons**:
  - *Primary*: Solid `#0D151C` fill, pure white label, `0.25rem` radius, `12px 24px` padding. Transitions on hover to `#1E293B` with no dimensional offset.
  - *Secondary / Outline*: Transparent background, 1px border in `rgba(13, 21, 28, 0.24)`, `#0D151C` text. Hover shifts to `#0D151C` with white text.
  - *Curatorial Action*: Ochre-accented text (`#D97706`) with an understated bottom hairline border for in-text citations and asset downloads.

- **Chips & Placard Tags**:
  - Metadata badges and category indicators use a compact silhouette (`4px 10px`), an ultra-light tint base (`rgba(13, 21, 28, 0.04)`), an exact 1px border (`rgba(13, 21, 28, 0.08)`), and uppercase tracked typography (`label-sm`).
  - Active/Filter chips toggle to solid `#0D151C` or ochre indicator pips (`#D97706`).

- **Archive Cards**:
  - Unbroken white (`#FFFFFF`) or glassmorphic backdrop with a uniform 1px border (`#E2E8F0`). 
  - Photography within cards sits on zero-padding or uniform matboard borders (`16px`). Image hovers trigger subtle metadata slide-ins from the bottom edge rather than zoom distortions.

- **Input Fields & Search Bars**:
  - Minimalist text boxes with transparent or alabaster fills, bounded by a 1px border (`#CBD5E1`).
  - Focus state swaps the border to `#0D151C` with a hairline secondary inner ring. Placeholder text uses `body-md` in `#94A3B8`.

- **Checkboxes & Radios**:
  - Strict 4px rounded rectangles for checkboxes, crisp geometric circles for radios. Checked states fill with `#0D151C` containing a stark alabaster checkmark.

- **Lists & Provenance Tables**:
  - Border-bottom ruled rows with `1px solid rgba(13, 21, 28, 0.08)`. Alternating row zebra patterns are prohibited; state distinction relies entirely on hover luminosity shifts.

- **Archival Lightbox & Filmstrip**:
  - Floating frosted navigation glass at the bottom viewport edge housing miniature framed thumbnail previews with an ochre active frame highlight (`2px solid #D97706`).