---
name: Warm Archival Earth
colors:
  surface: '#fef8f4'
  surface-dim: '#ded9d5'
  surface-bright: '#fef8f4'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f8f3ef'
  surface-container: '#f2ede9'
  surface-container-high: '#ece7e3'
  surface-container-highest: '#e6e2de'
  on-surface: '#1d1b19'
  on-surface-variant: '#45474b'
  inverse-surface: '#32302e'
  inverse-on-surface: '#f5f0ec'
  outline: '#76777b'
  outline-variant: '#c6c6cb'
  surface-tint: '#5c5e64'
  primary: '#030408'
  on-primary: '#ffffff'
  primary-container: '#1b1e23'
  on-primary-container: '#83868c'
  inverse-primary: '#c4c6cd'
  secondary: '#476556'
  on-secondary: '#ffffff'
  secondary-container: '#c9ead8'
  on-secondary-container: '#4d6b5c'
  tertiary: '#0e0100'
  on-tertiary: '#ffffff'
  tertiary-container: '#3d0d00'
  on-tertiary-container: '#d5643b'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#e1e2e9'
  primary-fixed-dim: '#c4c6cd'
  on-primary-fixed: '#191c21'
  on-primary-fixed-variant: '#44474c'
  secondary-fixed: '#c9ead8'
  secondary-fixed-dim: '#aecebc'
  on-secondary-fixed: '#032015'
  on-secondary-fixed-variant: '#304d3f'
  tertiary-fixed: '#ffdbcf'
  tertiary-fixed-dim: '#ffb59c'
  on-tertiary-fixed: '#390c00'
  on-tertiary-fixed-variant: '#822801'
  background: '#fef8f4'
  on-background: '#1d1b19'
  surface-variant: '#e6e2de'
typography:
  display-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 56px
    fontWeight: '700'
    lineHeight: 64px
    letterSpacing: -0.02em
  display-lg-mobile:
    fontFamily: Plus Jakarta Sans
    fontSize: 36px
    fontWeight: '700'
    lineHeight: 44px
    letterSpacing: -0.015em
  headline-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.01em
  headline-lg-mobile:
    fontFamily: Plus Jakarta Sans
    fontSize: 26px
    fontWeight: '600'
    lineHeight: 34px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.005em
  headline-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  body-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 15px
    fontWeight: '400'
    lineHeight: 24px
  body-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 20px
  label-lg:
    fontFamily: Plus Jakarta Sans
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
    letterSpacing: 0.02em
  label-md:
    fontFamily: Plus Jakarta Sans
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.04em
  label-sm:
    fontFamily: Plus Jakarta Sans
    fontSize: 11px
    fontWeight: '500'
    lineHeight: 14px
    letterSpacing: 0.06em
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
  margin-tablet: 2rem
  margin-mobile: 1.25rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 1rem
  space-lg: 1.5rem
  space-xl: 2.5rem
---

## Brand & Style
The design system reflects a museum-grade photographic repository and conversational visual knowledge base. It evokes the material permanence of sun-cured archival papers, linen portfolio mounts, and the mineral landscapes of East Africa. The interface feels deliberate, warm, and tactile—eschewing clinical digital neutrality in favor of an artisanal, physical medium where photography and conversational intelligence coalesce.

The aesthetic philosophy draws from **Warm Editorial Tactility** combined with **Contemporary Archival Minimalism**:
- **Atmospheric Medium:** Absolute exclusion of sterile `#FFFFFF`. All canvas and component states live on organic sand, papyrus, and earthen clay planes.
- **Physical Gravitas:** Typography and structural elements carry the authority of ink pressed into heavy stock, balancing archaeological reverence with conversational immediacy.
- **Target Audience:** Curators, researchers, cultural documentarians, and photographers seeking deep contextual narratives around Kenyan visual histories.

## Colors
The color hierarchy establishes an unyielding anti-glare environment inspired by Kenyan earth and sun-bleached papyrus:

- **Base Canvas (`neutral_color_hex`: `#F4EFEB` / Clay Papyrus):** The universal floor of the application. Replaces digital white with warm, raw pulp undertones.
- **Primary Ink (`primary_color_hex`: `#1B1E23` / Roasted Espresso):** Used for authoritative typography, high-priority interactive glyphs, and structural grounding lines.
- **Secondary Accent (`secondary_color_hex`: `#3D5A4C` / Acacia Mineral):** Communicates contextual depth, secondary categorization, conversational AI verification states, and calm metadata badges.
- **Tertiary Vitality (`tertiary_color_hex`: `#C85A32` / Sun-baked Terracotta):** Reserved for focal points, highlights, visual playbacks, critical interactive prompts, and time markers.
- **Surface Elevation Hierarchy:**
  - Base Floor: `#F4EFEB`
  - Elevated Surface Layer 1: `#EBE5DD` (Tactile Canvas)
  - Elevated Surface Layer 2: `#E5DFD6` (Recessed / Focus Trays)
  - Hairline Structural Border: `#D8D0C5` (Parchment Edge)

## Typography
Plus Jakarta Sans provides geometric precision tempered by organic humanist curves, echoing classic catalog cartography while retaining optimal legibility across photographic overlays and dense archival logs.

- **Headings & Display:** Styled with tight tracking (`-0.02em` to `-0.01em`) and assertive weights (`600` and `700`) to evoke architectural mastheads.
- **Narrative & Archival Body:** Line height is intentionally generous (`1.5` to `1.6`) to sustain sustained reading of historical field notes, oral history transcripts, and conversational synthesis.
- **Labels & Monographic Metadata:** Rendered in small caps or expanded letter-spacing (`0.02em` to `0.06em`) to emulate museum specimen tags, geographic coordinates, and timestamp ribbons.

## Layout & Spacing
The layout adheres to a structured 12-column responsive fluid grid designed around exhibition framing:
- **Canvas Framing:** Desktop layouts utilize a substantial outer margin (`3rem`) to present content within a broad mat-board border. Tablet scales to `2rem`, and mobile narrows to `1.25rem`.
- **Rhythm:** Spacing follows an organic 4px/8px modular base. Element groupings within conversational threads stay tight (`space-xs` to `space-sm`), while contextual shifts between archived visual sets demand breath (`space-xl`).
- **Photographic Gallery Span:** Imagery prioritizes asymmetric column breaks—favoring 7:5 conversational-to-media ratios on desktop, stacking to a single fluid column on mobile screens under 768px.

## Elevation & Depth
Depth is produced through physical paper stratification rather than synthetic light casting:

- **Tonal Stepping:** Surfaces never lift via pure drop shadows. Depth is achieved by placing `#EBE5DD` upon `#F4EFEB`, or `#E5DFD6` upon `#EBE5DD`.
- **Mineral Ambient Glow:** When tactile lift is required (e.g., dragged photographic loupe or active dialog overlay), use a soft, clay-tinted ambient spread: `0 12px 32px -4px rgba(27, 30, 35, 0.08), 0 4px 12px -2px rgba(200, 90, 50, 0.04)`.
- **Low-Contrast Parchment Seams:** Cards, trays, and dividers rely on single-pixel solid borders of `#D8D0C5`. No translucent alpha borders are permitted over the sand surfaces.

## Shapes
The shape language employs a disciplined, architectural soft cornering (`roundedness: 1`). 
- Default radius is `0.25rem` (4px), creating crisp, precision-cut paper edges.
- Containers, media mats, and cards scale to `0.5rem` (`rounded-lg` / 8px).
- Modals, visual loupe frames, and floating conversational docks peak at `0.75rem` (`rounded-xl` / 12px).
- Circular pills are barred from core containment, reserved solely for micro status indicators and metadata dots.

## Components

### Buttons
- **Primary:** Background of Roasted Espresso (`#1B1E23`) with Sand (`#F4EFEB`) typography. Border-radius `4px`. Active feedback settles into Terracotta (`#C85A32`).
- **Secondary / Archival:** Background `#EBE5DD`, border `1px solid #D8D0C5`, text `#1B1E23`. Hover shifts fill to `#E5DFD6`.
- **Terracotta Accent (Action/Highlight):** Fill `#C85A32`, text `#F4EFEB`. Hover deepens to `#B34A24`.

### Cards & Photo Mounts
- Layered on `#EBE5DD` with a perimeter outline of `1px solid #D8D0C5`.
- Inner photo framing incorporates an inset mat board effect: `12px` of `#E5DFD6` surrounding the archival image. No pure white borders under any circumstance.
- Captions and provenance markers sit below the mat in `body-sm` (`#1B1E23`) with tags in `label-sm` (`#3D5A4C`).

### Chips & Metadata Badges
- **Status & Taxonomy:** Border `1px solid #D8D0C5`, background `#E5DFD6`, text `#3D5A4C`.
- **Active Filter:** Border `1px solid #C85A32`, background `#C85A32`, text `#F4EFEB`.
- Radius `4px`, padding `4px 10px`, typography `label-sm` uppercase.

### Input Fields & Conversational Bar
- Background `#E5DFD6` bordered by `1px solid #D8D0C5`.
- Text typed in `#1B1E23`, placeholder rendered in `#6E6962`.
- Focus state switches border to `1.5px solid #C85A32` with zero synthetic glow rings.

### Checkboxes & Radio Controls
- Base unselected state: `#E5DFD6` box with `1.5px solid #D8D0C5`.
- Selected state: Roasted Espresso (`#1B1E23`) or Terracotta (`#C85A32`) fill with papyrus check indicator (`#F4EFEB`). Radius `2px` for checkboxes.

### Conversational Visual Thread (Archive Specific)
- **User Query:** Flush right, background `#EBE5DD`, border `1px solid #D8D0C5`.
- **Archival Agent Response:** Flush left, transparent canvas backed by vertical `2px` hairline rule in `#3D5A4C` (Acacia Mineral).
- **Referenced Artifact Thumbnails:** Floating tiles with `#E5DFD6` backdrop, thumbnail, and micro metadata stamp.