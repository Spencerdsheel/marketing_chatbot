# Frontend Architecture

## Core Philosophy: Server-First

### React Server Components (RSC)
The frontend architecture is built around React Server Components as the default:
- Data fetching happens on the server
- Components render to HTML before reaching the client
- Client JavaScript is only loaded for interactive components
- Bundle size is minimized automatically

**Reusable Insight:** Use server components as the default. Only mark components as client components when they need interactivity (state, effects, event handlers).

### Next.js App Router
The App Router provides:
- File-based routing with nested layouts
- Server components by default
- Server actions for form submissions
- Streaming and suspense boundaries
- Built-in metadata and SEO

**Reusable Insight:** The App Router's file-based routing maps directly to URL structure. Use nested layouts for shared UI (navigation, sidebars).

## Component Architecture

### Component Hierarchy
```
app-shell.tsx (client component - layout shell)
├── Top navigation bar
├── User display + sign-out
└── Main content area (server components)
    ├── Page components (server)
    │   ├── Data fetching
    │   └── Layout composition
    └── UI components (client when interactive)
        ├── shadcn/ui primitives
        ├── Charts (lazy-loaded)
        └── Admin components
```

### Server vs Client Component Decision Tree
- **Server Component (default):** Data fetching, layout, static content
- **Client Component:** Forms, charts, animations, interactive UI
- **Lazy-loaded Client Component:** Heavy components (charts, tables)

**Reusable Insight:** The boundary between server and client components should be as close to the leaves of the component tree as possible. This minimizes client JavaScript.

### Lazy Loading Strategy
Heavy components (charts, large tables) are dynamically imported:
```typescript
const Chart = dynamic(() => import('./chart'), { ssr: false })
```

**Reusable Insight:** Lazy load anything that:
- Is not visible on initial render
- Requires a large library (charting, data grid)
- Is conditionally rendered
- Is below the fold

## State Management Philosophy

### No Client-Side State Library
The architecture deliberately avoids Redux, Zustand, or similar:
- **Server state:** Fetched in server components, passed as props
- **Form state:** React controlled components
- **Session state:** httpOnly cookies, decoded server-side
- **URL state:** Next.js routing and search params

**Reusable Insight:** With server components, most "state management" problems disappear. Data flows from server to client as props. Only keep client state for UI interactions.

### Server Actions for Mutations
Form submissions use Next.js server actions:
- No API endpoints needed for simple mutations
- Automatic CSRF protection
- Type-safe with TypeScript
- Can call backend API directly

**Reusable Insight:** Server actions eliminate the need for separate API routes for form submissions. Use them for create, update, and delete operations.

## Data Fetching Patterns

### Server Component Data Fetching
```typescript
async function Page() {
  const data = await fetchData()
  return <Component data={data} />
}
```

**Reusable Insight:** Async server components are the simplest data fetching pattern. No loading states, no error boundaries needed for the fetch itself.

### Provider Abstraction Layer
Frontend uses a provider interface with multiple implementations:
- **RestApiProvider:** Production - calls backend API
- **SampleDataProvider:** Development - static data
- **ShopmetricsProvider:** Alternative - direct API calls

Selected via environment variable, swapped without UI changes.

**Reusable Insight:** Define a TypeScript interface for your data layer. Implement it differently for dev, test, and prod. This enables offline development and easy testing.

### Error Boundaries and Loading States
- Suspense boundaries for loading states
- Error boundaries for graceful error handling
- Fallback UI matches the design system

**Reusable Insight:** Use Suspense for loading states, not manual loading flags. It composes better and works with streaming.

## Routing and Navigation

### File-Based Routing
- `app/dashboard/page.tsx` -> `/dashboard`
- `app/dashboard/projects/[id]/page.tsx` -> `/dashboard/projects/:id`
- `app/layout.tsx` -> Root layout (shared across all pages)
- `app/dashboard/layout.tsx` -> Dashboard layout (shared across dashboard pages)

**Reusable Insight:** Organize routes by feature, not by type. All files related to a feature live in the same directory.

### Middleware for Auth Routing
Next.js middleware handles:
- Authentication checks before page render
- Redirect unauthenticated users to login
- Role-based route protection
- Session cookie validation

**Reusable Insight:** Middleware runs before the request reaches any page. Use it for authentication, not individual pages.

## Type Safety

### TypeScript Strict Mode
- No `any` types
- Strict null checks
- Strict function types
- Path aliases (`@/*` -> `src/*`)

**Reusable Insight:** Strict TypeScript catches bugs at compile time. The initial friction pays off in reduced runtime errors.

### Zod for Runtime Validation
Zod schemas validate:
- Server action inputs
- API response shapes
- Form data before submission

**Reusable Insight:** TypeScript catches compile-time errors. Zod catches runtime errors from external data (APIs, forms, environment).

## Performance Optimization

### Rendering Strategy
- Server components for static/semi-static content
- Client components only for interactivity
- Lazy loading for heavy components
- Streaming for progressive rendering

### Bundle Optimization
- Tree shaking via ES modules
- Code splitting via dynamic imports
- Image optimization via Next.js Image component
- Font optimization via next/font

**Reusable Insight:** Measure before optimizing. Use Next.js bundle analyzer to identify large dependencies.

## Accessibility

### Built-In Accessibility
- Semantic HTML elements
- ARIA labels where needed
- Keyboard navigation support
- Focus management for dialogs and modals

### Reduced Motion
- Respects `prefers-reduced-motion`
- Disables background animations
- Reduces transition durations

**Reusable Insight:** Accessibility is not a feature, it's a requirement. Build it in from the start, not as an afterthought.
