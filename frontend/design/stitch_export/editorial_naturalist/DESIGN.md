---
name: Editorial Naturalist
colors:
  surface: '#fbf9f3'
  surface-dim: '#dcdad4'
  surface-bright: '#fbf9f3'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f5f3ed'
  surface-container: '#f0eee8'
  surface-container-high: '#eae8e2'
  surface-container-highest: '#e4e2dd'
  on-surface: '#1b1c18'
  on-surface-variant: '#414844'
  inverse-surface: '#30312d'
  inverse-on-surface: '#f3f1eb'
  outline: '#727974'
  outline-variant: '#c1c8c2'
  surface-tint: '#436555'
  primary: '#002014'
  on-primary: '#ffffff'
  primary-container: '#143628'
  on-primary-container: '#7ca08d'
  inverse-primary: '#aacfbb'
  secondary: '#a13f25'
  on-secondary: '#ffffff'
  secondary-container: '#fd8364'
  on-secondary-container: '#721c06'
  tertiary: '#0b1f17'
  on-tertiary: '#ffffff'
  tertiary-container: '#20342b'
  on-tertiary-container: '#879d91'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#c5ebd6'
  primary-fixed-dim: '#aacfbb'
  on-primary-fixed: '#002115'
  on-primary-fixed-variant: '#2c4d3e'
  secondary-fixed: '#ffdad2'
  secondary-fixed-dim: '#ffb4a2'
  on-secondary-fixed: '#3c0700'
  on-secondary-fixed-variant: '#812810'
  tertiary-fixed: '#d1e8da'
  tertiary-fixed-dim: '#b5ccbf'
  on-tertiary-fixed: '#0b1f17'
  on-tertiary-fixed-variant: '#374b41'
  background: '#fbf9f3'
  on-background: '#1b1c18'
  surface-variant: '#e4e2dd'
typography:
  display:
    fontFamily: Plus Jakarta Sans
    fontSize: 48px
    fontWeight: '700'
    lineHeight: 56px
    letterSpacing: -0.03em
  display-mobile:
    fontFamily: Plus Jakarta Sans
    fontSize: 34px
    fontWeight: '700'
    lineHeight: 42px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.02em
  headline-lg-mobile:
    fontFamily: Plus Jakarta Sans
    fontSize: 26px
    fontWeight: '600'
    lineHeight: 34px
    letterSpacing: -0.015em
  headline-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.01em
  headline-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.005em
  body-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
    letterSpacing: 0em
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
  label-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
    letterSpacing: 0.01em
  label-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 11px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.04em
rounded:
  sm: 0.5rem
  DEFAULT: 1rem
  md: 1.5rem
  lg: 2rem
  xl: 3rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-tablet: 1.5rem
  gutter-desktop: 2rem
  margin: 1rem
  margin-tablet: 2rem
  margin-desktop: 3rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2.5rem
---

## Brand & Style

This design system establishes an editorial naturalist aesthetic for exploring cultural, ecological, and geographical photography across Kenya through conversational discovery. The experience rejects tourism clichés, saturated safari tropes, and literal national motifs in favor of an organic, archival, and premium documentary sensibility.

The interface functions as a museum-grade archival lens: quiet, photo-forward, and calm. High-resolution imagery commands focus against warm, tactile paper surfaces. Conversational intelligence appears as thoughtful editorial annotations rather than intrusive chat widgets. Interactions are fluid, paced, and deliberate, prioritizing contemplative discovery over hyperactive social feeds.

## Colors

The palette derives from indigenous landscapes—montane forest canopies, rift valley clay, and weathered stone—rendered with editorial restraint:

- **Primary (`#143628`)**: Deep Forest. Anchors authoritative chrome, primary CTAs, active visual markers, and key header typography.
- **Secondary / Accent (`#BD5338`)**: Warm Terracotta. Applied selectively to critical user actions, conversational focus rings, contextual highlights, and editorial footnotes.
- **Tertiary / Subdued Neutral (`#5B7065`)**: Muted Sage. Governs quiet structural rules, iconography, meta-captions, and inactive indicators.
- **Canvas Neutral (`#F8F6F0`)**: Warm Alabaster. The tactile, uncoated paper canvas that provides high comfort during extended reading and viewing.
- **Primary Text (`#1F2421`)**: Soft Charcoal. Delivers high-contrast legibility without the harshness of pure black (`#000000`).

### Semantic Verification & Status Badges
Status indicators rely on muted, tinted pigments rather than aggressive alert tones:
- **Confirmed**: Soft Emerald tint (`#E8F3ED`, text `#14462B`)
- **Candidate**: Soft Amber tint (`#FDF5E6`, text `#7A4F08`)
- **Clear**: Soft Sky/Sage tint (`#EDF3F2`, text `#2A524B`)
- **Partial**: Soft Terracotta tint (`#F9ECE7`, text `#8F351A`)

## Typography

The type system uses **Plus Jakarta Sans** uniformly to unite geometric precision with open, humanist letterforms. This consistency maintains an editorial, catalog-like rigor across mobile interfaces.

- **Headlines & Display:** Set tightly with slight negative letter tracking (`-0.03em` to `-0.01em`) to mimic modern cultural publications.
- **Body Text:** Kept open with relaxed line heights (`1.55` to `1.6`) for long-form visual descriptions, regional provenance notes, and conversational transcript history.
- **Metadata & Labels:** Set with subtle positive tracking (`+0.01em` to `+0.04em`) at 600 weight to ensure immediate legibility on chips, geo-coordinates, and taxonomy tags.

## Layout & Spacing

A mobile-first fluid layout governs the interface, prioritizing single-column feeds that expand systematically onto wider viewports.

- **Mobile (< 768px):** Single-column layout with fixed edge margins of `1rem` (16px). All full-bleed imagery maintains negative margins to maximize edge-to-edge photography viewing.
- **Tablet (768px – 1024px):** 6-column fluid grid, `1.5rem` gutters, and `2rem` margins. Photographic feeds adapt into dual-column staggered masonry panels.
- **Desktop (> 1024px):** 12-column layout with a max canvas constraint of `1320px`, flanked by `3rem` outer margins. conversational threads pin to a fixed secondary column (`4 cols`) while visual artifacts expand across the primary canvas (`8 cols`).

Touch targets default to a strict minimum of `48px × 48px` on mobile surfaces.

## Elevation & Depth

Visual hierarchy uses warm, diffuse ambient shadowing layered over subtle tonal differentiation, avoiding harsh drop shadows or neon blurs.

- **Surface Level 0 (Canvas):** The warm `#F8F6F0` base layer.
- **Surface Level 1 (Card & Content Blocks):** `#FFFFFF` surfaces layered with a hairline border (`1px solid rgba(91, 112, 101, 0.12)`) and an ambient shadow: `0 4px 20px -2px rgba(20, 54, 40, 0.04)`.
- **Surface Level 2 (Floating Conversational Bars & Menus):** High-opacity frosted surface (`rgba(255, 255, 255, 0.92)` with `backdrop-filter: blur(12px)`), an earthy stroke (`1px solid rgba(91, 112, 101, 0.18)`), and soft depth: `0 12px 32px -4px rgba(20, 54, 40, 0.08)`.
- **Surface Level 3 (Modals & Full-Screen Visual Inspect):** Deep natural diffusion: `0 24px 48px -8px rgba(31, 36, 33, 0.16)`.

## Shapes

The design uses an organic, highly rounded profile that softens information density and honors the natural contours of photographic subjects.

- **Small Components (Chips, Badges, Buttons):** Fully pill-shaped (`9999px` radius) to convey interactive tangibility and frictionless navigation.
- **Standard Cards & Input Containers:** `rounded-2xl` (1.5rem / 24px) for content groupings, conversation snippets, and meta-panels.
- **Primary Hero Cards & Visual Modules:** `rounded-3xl` (2rem / 32px) for focal image containers, featured regional reels, and contextual conversational drawers.

## Components

### Buttons
- **Primary:** Forest Green (`#143628`) background, white text (`#FFFFFF`), full pill radius. State changes transition to hover opacity (`92%`) with a subtle `translateY(-1px)` lift. Minimum height: `52px` for mobile accessibility.
- **Secondary / Accent:** Warm Terracotta (`#BD5338`) background with white text, reserved for critical conversational pivots or direct curation triggers.
- **Outline:** Transparent surface, `1.5px` border in `#5B7065` at 30% opacity, `#1F2421` text. Transitions to 10% Forest Green fill on touch/hover.

### Chips & Badges
- **Editorial Chips:** Pill-shaped, `#FFFFFF` fill with `1px solid rgba(91, 112, 101, 0.2)` border, `#1F2421` text. Interactive filtering toggles the chip to `#143628` background with `#FFFFFF` text.
- **Status Badges:** Small pill containers (`24px` height, `11px` label tracking). Styled with flat background tints without borders:
  - *Confirmed*: `#E8F3ED` background with `#14462B` text.
  - *Candidate*: `#FDF5E6` background with `#7A4F08` text.
  - *Clear*: `#EDF3F2` background with `#2A524B` text.
  - *Partial*: `#F9ECE7` background with `#8F351A` text.

### Cards
- **Image Reel Card:** Styled with a `rounded-3xl` perimeter, `#FFFFFF` backing, and an edge-to-edge photograph adhering to a 4:5 or 1:1 ratio. Overlays use a gentle downward gradient (`linear-gradient(180deg, transparent 60%, rgba(20, 54, 40, 0.75) 100%)`) with white title lockups.
- **Knowledge Annotation Card:** Flat off-white or white card with a `rounded-2xl` radius, `1px solid rgba(91, 112, 101, 0.14)` border, featuring an author/source tag, body synopsis, and provenance chip array.

### Input Fields & Conversational Bar
- **Conversational Query Bar:** Mobile dock floating `16px` above the bottom safe area. Height: `56px`, pill-shaped, frosted background (`rgba(255, 255, 255, 0.94)`), bound by a `1px` muted sage border (`rgba(91, 112, 101, 0.25)`). Accommodates direct text prompts, an integrated microphone icon, and image attachment triggers in Terracotta (`#BD5338`).
- **Standard Text Fields:** `rounded-xl` corners, `#FFFFFF` background, warm charcoal label above, and focus rings tinted in Terracotta (`#BD5338` at 2px outline width).

### Lists & Metadata
- **Archival Item Rows:** Flush horizontal rows divided by hairline dividers (`1px solid rgba(91, 112, 101, 0.12)`). Left-aligned thumbnail (`56px × 56px`, `rounded-xl`), title in 600 weight, and metadata/coordinates set in `body-sm` muted sage.