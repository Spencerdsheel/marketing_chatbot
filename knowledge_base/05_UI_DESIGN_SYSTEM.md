# UI Design System

## Design Language: "Ventriloc"

### Color Philosophy
The design system uses a carefully curated palette:

| Token | Usage | Hex |
|-------|-------|-----|
| signal-orange | Primary accent, CTAs | #ff682c |
| sienna-bronze | Secondary accent | warm bronze |
| carbon | Dark text, headings | near-black |
| graphite | Body text | dark gray |
| slate | Muted text | medium gray |
| fog | Borders, dividers | light gray |
| mist | Subtle backgrounds | very light gray |
| chalk | Card surfaces | off-white |
| paper | Primary card surface | #ffffff |

**Reusable Insight:** Define a limited color palette with clear usage rules. Every color should have a purpose. Avoid arbitrary color values.

### Typography System

#### Font Pairing
- **Space Grotesk:** Display text, KPI numbers, headings
- **Inter:** Body text, labels, descriptions

#### Type Scale
- KPI numbers: 2.25rem, tight tracking, tabular-nums
- Headings: 1.5rem - 2rem, Space Grotesk
- Body: 0.875rem - 1rem, Inter
- Labels: 0.75rem, Inter, uppercase

**Reusable Insight:** Limit yourself to two fonts. One for display, one for body. Use weight and size for hierarchy, not additional fonts.

### Card Design Pattern

#### .card-ventriloc
- White surface (#ffffff)
- 8px border radius
- Subtle ghost elevation (box-shadow)
- Consistent padding (1.5rem)
- Clean hover states

**Reusable Insight:** Cards are the fundamental layout unit. Define a single card pattern and use it everywhere. Consistency builds trust.

### Navigation Pattern

#### Pill-Shaped Navigation
- Active state: pill shape (rounded-pill, 20px radius)
- Glass-header effect: sticky top bar with backdrop blur
- Hover states: subtle background change
- Active indicator: signal-orange accent

**Reusable Insight:** Navigation should feel tactile. Pill shapes and glass effects create a modern, polished feel.

## Animation Philosophy

### Purposeful Animation
- Staggered card entrances for visual hierarchy
- Animated counters for KPI updates
- Aurora background drift for ambient depth
- Smooth transitions for state changes

### Performance Constraints
- Respects `prefers-reduced-motion`
- Uses CSS transforms (GPU-accelerated)
- Avoids layout-triggering properties
- Framer Motion for complex sequences

**Reusable Insight:** Animation should enhance, not distract. Every animation should have a purpose: guide attention, provide feedback, or create delight.

### Aurora Background
Three radial gradients with slow drift animation:
- Creates ambient depth without distraction
- Disabled for users who prefer reduced motion
- Pure CSS, no JavaScript required

**Reusable Insight:** Background effects should be subtle enough to ignore but present enough to notice. They set the mood, not the focus.

## Responsive Design

### Breakpoint Strategy
- Mobile: 1 column
- Tablet: 2 columns
- Desktop: 3 columns
- Max content width: 1200px

### Grid System
- CSS Grid for layouts
- Flexbox for component internals
- Gap-based spacing (no margins)

**Reusable Insight:** Design mobile-first, but test desktop-first. Most dashboard users are on desktop, but the layout must work on mobile.

## Component Library: shadcn/ui

### Why shadcn/ui
- Not a component library, but a copy-paste pattern
- Full control over component code
- Built on Radix UI primitives (accessible)
- Tailwind CSS for styling
- Easy to customize

**Reusable Insight:** shadcn/ui gives you the best of both worlds: accessible primitives and full customization. You own the code.

### Component Organization
```
components/
├── ui/           # shadcn primitives (button, card, dialog, etc.)
├── charts/       # Recharts wrappers
├── admin/        # Admin-specific components
├── app-shell.tsx # Main layout shell
└── lazy-chart.tsx # Lazy-loaded chart wrapper
```

**Reusable Insight:** Separate primitives from composites. Primitives (button, input) are reusable everywhere. Composites (data table, chart panel) are feature-specific.

## Accessibility Standards

### Keyboard Navigation
- All interactive elements are focusable
- Focus order matches visual order
- Visible focus indicators
- Escape key closes modals

### Screen Reader Support
- Semantic HTML elements
- ARIA labels where semantics are insufficient
- Live regions for dynamic content
- Alt text for images and icons

### Color Contrast
- All text meets WCAG AA contrast ratios
- Color is never the only indicator
- Icons accompany color-coded status

**Reusable Insight:** Accessibility is not optional. Test with keyboard only. Test with a screen reader. Test with high contrast mode.
