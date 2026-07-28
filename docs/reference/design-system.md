# DragonCP Design System

Last updated: 2026-07-28
Primary files: `frontend/src/index.css`, `frontend/index.html`, `frontend/src/components/layout/`, `frontend/src/components/transfers/transfer-bits.tsx`, `frontend/src/components/webhooks/webhook-bits.tsx`, `frontend/src/components/dashboard/disk-utils.ts`

## Purpose

The visual conventions this app actually follows, read out of the stylesheet and
the layout components rather than invented. Use it when adding a screen so the
new screen looks like the rest of the app.

For structure, hooks and stores, see [frontend.md](./frontend.md).

## Dark only

`frontend/index.html` ships `<html lang="en" class="dark">` and nothing changes
it. There is no theme toggle, and the toast component hard-codes `theme="dark"`
with a comment explaining that it does so because the class is pinned. A light
block of variables exists in `index.css` under `:root`, but no screen exercises
it — treat light mode as untested rather than supported.

## Brand tokens

`index.css` opens with five exact brand values and two gradients built from
them. The comment above them is a rule: components use these tokens or the
semantic ones below, never a raw hex or a stock `fuchsia`/`purple` utility.

| Token | Value | Role |
|---|---|---|
| `--brand-deep` | `#8313eb` | Deep violet — supporting shade, top of the gradient |
| `--brand` | `#a60eef` | Electric purple — the primary brand colour |
| `--brand-hover` | `#d508f5` | Bright magenta — hover and active |
| `--brand-accent` | `#f902fb` | Hot pink — accent, bottom of the gradient |
| `--brand-foreground` | `#fae8ff` | Light tint for text sitting on a brand wash |
| `--gradient-brand` | violet → purple → magenta → pink, top to bottom | |
| `--gradient-brand-x` | the same ramp, left to right | |

`@theme inline` maps these to Tailwind colours, so in markup they are
`bg-brand`, `text-brand-hover`, `text-brand-accent`, `text-brand-foreground`,
`border-brand/40`, `ring-brand/35` and so on. Three custom utilities carry the
gradient: `bg-brand-gradient` (vertical), `bg-brand-gradient-x` (horizontal, the
one used for rails and bars) and `text-brand-gradient` (clipped to text — used
for the "CP" in the wordmark on the sidebar and the login page).

The brand also drives `--primary`, `--ring`, and the chart series
(`--chart-1` … `--chart-5` walk pink → violet, with `#5c0ba8` derived one step
deeper than `--brand-deep`).

## Surfaces and borders

The dark palette is a set of near-black greys, deliberately not pure black:

| Variable | Dark value | Used for |
|---|---|---|
| `--background` | `#141414` | page background |
| `--card` | `#1e1e1e` | every card and panel |
| `--popover` | `#1e1e1e` | popovers, menus |
| `--sidebar` | `#1a1a1a` | sidebar |
| `--border` | `oklch(1 0 0 / 10%)` | all hairlines |
| `--input` | `oklch(1 0 0 / 15%)` | input outlines |
| `--ring` | `--brand-hover` | focus ring |

**The surface idiom is one line**: `rounded-xl border border-border bg-card`.
That exact combination appears about two dozen times across the app — stat
tiles, section cards, the dashboard ticker, the storage strip. A new panel
should use it rather than inventing a shadow or a tint.

Depth comes from the shell, not from individual cards. `app-layout.tsx` puts an
`app-ambient` background on the whole page — a base of `#0f0f10`, darker than
`--background`, with a violet glow top-left and a hot-pink glow bottom-right —
and then floats the content in a `SidebarInset` that carries
`border border-border` and one large soft shadow. The sidebar itself is made
transparent so it sits in the gutter of that ambient canvas. The login page uses
the same trick with two radial gradients in brand violet and pink.

Recessed elements — chips, the metrics pill in the header, the media badge — use
a black wash instead of a lighter card: `bg-black/20` through `bg-black/40` over
the standard border. The progress meter's empty track is `bg-white/8`.

Within a card, subsections are separated by a hairline at reduced strength
(`border-t border-border/70` in `SectionCard`), not by spacing alone.

Radius: `--radius` is `0.625rem`, and `sm`/`md`/`lg`/`xl`/`2xl`/`3xl`/`4xl` are
computed from it (−4px, −2px, base, +4, +8, +12, +16). Cards are `rounded-xl`,
smaller inline pieces `rounded-md`, badges and dots `rounded-full`.

## Typography

Three variable fonts, all self-hosted through `@fontsource-variable`:

| Tailwind class | Family | Where |
|---|---|---|
| `font-sans` (default) | Nunito Sans Variable | body copy, everything unmarked |
| `font-display` | Space Grotesk Variable | headings, stat numbers, the wordmark, the breadcrumb leaf |
| `font-mono` | JetBrains Mono Variable | every number, path, log line, ID and eyebrow label |

`font-mono` is by far the most-used marker in the app (around eighty uses
against ten for `font-display`), because the interface is mostly numbers and
paths. The rule in practice: if a value would misalign as it changes — a byte
count, a percentage, a duration, a queue count — it is mono, usually with
`tabular-nums`.

**The eyebrow** is the app's recurring small label: uppercase, ~10px, wide
letter-spacing, `text-muted-foreground`. It appears above every stat tile, at the
head of every `SectionCard`, over each fact in a transfer detail, and above each
sidebar group. Tracking varies slightly by context — `0.06em` on stat tiles,
`0.1em` on detail facts, `0.14em` on section headers and popover cells,
`0.18em` on sidebar group labels — and the sidebar's version is the one that uses
`font-display` rather than mono.

Page titles are `text-3xl font-bold` (`PageHeader`); stat values are
`font-display text-2xl font-semibold tabular-nums`.

## Status colours

Status is carried by a fixed four-note vocabulary, and only ever by tone name in
the code — components map a tone to classes through a `Record`, so the palette
changes in one place.

| Tone | Meaning | Text | Badge (border / fill / text) |
|---|---|---|---|
| `ok` | finished, healthy | `text-emerald-400` | `border-emerald-500/40 bg-emerald-500/15 text-emerald-300` |
| `warn` | queued, paused, needs attention | `text-amber-400` | `border-amber-500/40 bg-amber-500/15 text-amber-400` |
| `crit` | failed, full | `text-rose-400` | `border-rose-500/40 bg-rose-500/15 text-rose-400` |
| `brand` | in progress, live | `text-brand-foreground` | `border-brand/40 bg-brand/15 text-brand-foreground` |

`StatTiles` adds a `default` tone (`text-foreground`) for numbers that are just
numbers, and `transfer-bits.tsx` adds `muted`
(`border-border bg-muted/40 text-muted-foreground`) for a stopped transfer,
which is an outcome without a verdict.

The important convention here is that **in-progress is brand, not blue or
green**. A running transfer, an active queue slot and a healthy disk all read
purple; green is reserved for something that has finished. `disk-utils.ts` makes
this explicit — a disk under 78% full draws in `bg-brand-gradient-x`, 78% and
over turns amber, 92% and over turns rose.

Badges are consistent in shape as well as colour: `rounded-full`, a hairline
border, a 15% fill of the same hue, an icon, and the label in bold uppercase at
9–10px. `TransferStatusBadge` and `StatusBadge` are deliberately separate
components with the same look, because transfers and webhooks have different
status words (running / paused / cancelled versus syncing / manual-sync).

Two places extend the vocabulary rather than reuse it. `StatTiles` keeps labels
and units quiet so a screen of tiles does not become a traffic light. The
realtime pill in `realtime-status.tsx` needs six states rather than four, so it
adds blue for "connecting" and yellow for "settings changed", and uses plain
`text-muted-foreground` for the resting polling state.

## The active-state idiom

There is exactly one way this app says "you are here", and it is the brand
gradient. Every navigation surface uses a variation of it, and a new one should
too rather than introducing a pill, a filled block or an inverted colour.

| Surface | Treatment |
|---|---|
| Sidebar item (`app-sidebar.tsx`) | `bg-brand/15` wash, `ring-1 ring-brand/35 ring-inset`, label to `text-brand-foreground`, icon to `text-brand-hover` |
| Mobile bottom nav (`mobile-nav.tsx`) | 3px `bg-brand-gradient-x` rail across the top edge of the tab, label to `text-brand-foreground`, icon to `text-brand-hover` |
| Page tab bar (`page-tabs.tsx`) | shadcn's `line` tab variant, its underline re-tinted to `bg-brand-gradient-x`, label to `text-brand-foreground`, icon to `text-brand-hover` |

The comment in `page-tabs.tsx` states the reasoning directly: the bottom nav
already marks "where am I" with a brand rail, so a page does the same, and the
app has one idiom instead of two.

Inactive is quiet, not grey-on-grey: sidebar labels sit at
`text-sidebar-foreground/80` with icons at `/55`, so the active item lights up
against them rather than being the only legible one.

## Icons

All icons come from `@tabler/icons-react`. Inline icons default to `size-4`
through the button styles; navigation icons are `size-[22px]` on the mobile bar
and `size-[18px]` in the header; status-badge icons are `size-3` (`size-2.5` at
the small size).

Colour follows the same rule as text: an icon in an active nav item goes
`text-brand-hover`, an icon inside a status badge inherits the badge tone, and
everything else is `text-muted-foreground` until hovered.

## Writing style in the UI

Empty states are an invitation rather than a shrug — `SectionEmpty` takes an
icon, a title, an optional hint that explains how the section fills up
("Imports show up here once Radarr or Sonarr points at this app.") and an
optional action, which the webhooks page uses to offer a "Show all" button when
a filter is what emptied the list. Toasts and popover copy are full sentences
("The session idled out. Reconnect to resume."), not status codes. Where colour
carries meaning, something else carries it too: the filename diff adds a
`−`/`+` gutter alongside the tinted tokens, and status badges pair the tone with
an icon and a word.

## Applying classes

Every component composes classes through `cn()` from `@/lib/utils` (clsx plus
tailwind-merge), so a caller's `className` reliably overrides a default.
Variant-heavy components (`Button`, `Badge`, `TabsList`) use
`class-variance-authority` and export their variants
(`buttonVariants`, `badgeVariants`, `tabsListVariants`) for the cases where a
link has to carry button styling — see the header's notification and settings
links, which do exactly that so an interactive element is not nested inside
another.

## Known defect

`components/webhooks/webhook-bits.tsx` builds the poster-fallback stripe pattern
from `var(--surface-3)` and `var(--surface-2)`. Neither variable is defined
anywhere in `frontend/src/`, so that background resolves to nothing and the
fallback shows only the media icon on a transparent tile. Either define the two
surface steps in `index.css` or rewrite the pattern in terms of existing tokens.

## Not verified

- Whether the light-mode variable block is intended for future use or is
  leftover from the shadcn scaffold. It is only confirmed unexercised.
