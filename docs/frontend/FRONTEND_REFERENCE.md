# DragonCP Frontend Reference

> **Purpose**: Reference document for AI tools to understand the frontend project structure, tech stack, and available components.

---

## Tech Stack

| Category | Technology | Version |
|----------|------------|---------|
| Framework | React | 19.x |
| Build Tool | Vite | 7.x |
| Language | TypeScript | 5.9.x |
| Styling | Tailwind CSS | 4.x |
| Component Library | Base UI (NOT Radix) | 1.x |
| Component System | shadcn/ui (base-nova style) | Latest |
| Routing | TanStack Router | 1.x |
| State Management | Zustand | 5.x |
| Server State | TanStack Query | 5.x |
| HTTP Client | Axios | 1.x |
| WebSocket | Socket.io Client | 4.x |
| Icons | Tabler Icons React | 3.x |
| Notifications | Sonner | 2.x |
| Theme | next-themes | 0.4.x |

---

## Important: Base UI vs Radix

**This project uses Base UI, NOT Radix UI.**

### Key Differences

| Feature | Radix Pattern | Base UI Pattern |
|---------|---------------|-----------------|
| Render delegation | `asChild` prop | `render` prop with callback |
| Primitive imports | `@radix-ui/react-*` | `@base-ui/react/*` |

### asChild Compatibility

The UI components have been modified to accept `asChild` prop for API compatibility, but internally convert to Base UI's `render` prop pattern. This applies to:

- `DialogTrigger`
- `AlertDialogTrigger`
- `DropdownMenuTrigger`

---

## Project Structure

```
frontend/
├── src/
│   ├── components/
│   │   ├── auth/           # Authentication components
│   │   ├── layout/         # Layout components (AppLayout)
│   │   ├── pages/          # Page-level components
│   │   └── ui/             # shadcn/Base UI components
│   ├── hooks/              # Custom React hooks
│   ├── lib/                # Utilities (api, utils, query-client)
│   ├── routes/             # TanStack Router file-based routes
│   ├── services/           # External services (socket)
│   ├── stores/             # Zustand stores
│   ├── index.css           # Global styles & CSS variables
│   └── main.tsx            # App entry point
├── components.json         # shadcn configuration
├── package.json
└── vite.config.ts
```

---

## Available UI Components

### From shadcn/ui (Base UI primitives)

| Component | Import Path | Base UI Primitive |
|-----------|-------------|-------------------|
| AlertDialog | `@/components/ui/alert-dialog` | `@base-ui/react/alert-dialog` |
| Badge | `@/components/ui/badge` | `@base-ui/react/use-render` |
| Button | `@/components/ui/button` | `@base-ui/react/button` |
| Card | `@/components/ui/card` | Native div elements |
| Combobox | `@/components/ui/combobox` | Base UI combobox |
| Dialog | `@/components/ui/dialog` | `@base-ui/react/dialog` |
| DropdownMenu | `@/components/ui/dropdown-menu` | `@base-ui/react/menu` |
| Field | `@/components/ui/field` | Base UI field |
| Input | `@/components/ui/input` | `@base-ui/react/input` |
| InputGroup | `@/components/ui/input-group` | Native elements |
| Label | `@/components/ui/label` | Base UI label |
| Progress | `@/components/ui/progress` | `@base-ui/react/progress` |
| ScrollArea | `@/components/ui/scroll-area` | `@base-ui/react/scroll-area` |
| Select | `@/components/ui/select` | `@base-ui/react/select` |
| Separator | `@/components/ui/separator` | `@base-ui/react/separator` |
| Skeleton | `@/components/ui/skeleton` | Native div elements |
| Switch | `@/components/ui/switch` | `@base-ui/react/switch` |
| Tabs | `@/components/ui/tabs` | `@base-ui/react/tabs` |
| Textarea | `@/components/ui/textarea` | Base UI textarea |
| Sonner (Toast) | `@/components/ui/sonner` | `sonner` library |

---

## Component Sub-exports

### Button
- `Button` - Main button component
- `buttonVariants` - CVA variants for styling

**Variants**: `default`, `outline`, `secondary`, `ghost`, `destructive`, `link`  
**Sizes**: `default`, `xs`, `sm`, `lg`, `icon`, `icon-xs`, `icon-sm`, `icon-lg`

### Card
- `Card`, `CardHeader`, `CardTitle`, `CardDescription`, `CardAction`, `CardContent`, `CardFooter`

### Dialog
- `Dialog`, `DialogTrigger`, `DialogContent`, `DialogHeader`, `DialogTitle`, `DialogDescription`, `DialogFooter`, `DialogClose`, `DialogOverlay`, `DialogPortal`

### AlertDialog
- `AlertDialog`, `AlertDialogTrigger`, `AlertDialogContent`, `AlertDialogHeader`, `AlertDialogTitle`, `AlertDialogDescription`, `AlertDialogFooter`, `AlertDialogAction`, `AlertDialogCancel`, `AlertDialogMedia`, `AlertDialogOverlay`, `AlertDialogPortal`

### DropdownMenu
- `DropdownMenu`, `DropdownMenuTrigger`, `DropdownMenuContent`, `DropdownMenuItem`, `DropdownMenuGroup`, `DropdownMenuLabel`, `DropdownMenuSeparator`, `DropdownMenuShortcut`, `DropdownMenuCheckboxItem`, `DropdownMenuRadioGroup`, `DropdownMenuRadioItem`, `DropdownMenuSub`, `DropdownMenuSubTrigger`, `DropdownMenuSubContent`, `DropdownMenuPortal`

### Select
- `Select`, `SelectTrigger`, `SelectValue`, `SelectContent`, `SelectItem`, `SelectGroup`, `SelectLabel`, `SelectSeparator`, `SelectScrollUpButton`, `SelectScrollDownButton`

### Tabs
- `Tabs`, `TabsList`, `TabsTrigger`, `TabsContent`
- `tabsListVariants` - CVA variants

### Badge
- `Badge` - Badge component
- `badgeVariants` - CVA variants

**Variants**: `default`, `secondary`, `destructive`, `outline`, `ghost`, `link`

---

## Custom Hooks

| Hook | Purpose |
|------|---------|
| `useAuth` | Authentication (login, logout, check) |
| `useBackups` | Backup CRUD operations |
| `useConfig` | App configuration |
| `useMedia` | Media browsing & operations |
| `useTransfers` | Transfer management |
| `useWebhooks` | Webhook management |

---

## Stores (Zustand)

| Store | Purpose |
|-------|---------|
| `auth` | Authentication state (user, isAuthenticated) |

---

## Routes Structure

```
routes/
├── __root.tsx              # Root layout
├── index.tsx               # Landing/redirect
├── login.tsx               # Login page
├── _authenticated.tsx      # Auth layout wrapper
└── _authenticated/
    ├── dashboard.tsx
    ├── transfers.tsx
    ├── webhooks.tsx
    ├── backups.tsx
    ├── settings.tsx
    └── media/
        ├── index.tsx
        └── $type.tsx       # Dynamic: movies, tvshows, anime
```

---

## shadcn Configuration

From `components.json`:

| Setting | Value |
|---------|-------|
| Style | `base-nova` |
| RSC | `false` |
| TSX | `true` |
| Base Color | `neutral` |
| CSS Variables | `true` |
| Icon Library | `tabler` |

### Path Aliases

| Alias | Path |
|-------|------|
| `@/components` | `src/components` |
| `@/components/ui` | `src/components/ui` |
| `@/lib` | `src/lib` |
| `@/hooks` | `src/hooks` |
| `@/lib/utils` | `src/lib/utils` |

---

## Utility Functions

| Function | Location | Purpose |
|----------|----------|---------|
| `cn()` | `@/lib/utils` | Merge Tailwind classes (clsx + tailwind-merge) |

---

## Design System

### Color Scheme
- Primary: Fuchsia/Magenta (`oklch` based)
- Base: Neutral grays
- Supports light and dark mode via CSS variables

### Font
- Nunito Sans Variable

### Border Radius
- Base: `0.625rem` (defined as `--radius`)
- Variants: `sm`, `md`, `lg`, `xl`, `2xl`, `3xl`, `4xl`

---

## Icon Usage

All icons come from `@tabler/icons-react`. Import pattern:

```tsx
import { IconName } from '@tabler/icons-react';
```

Common icons used:
- Navigation: `IconLayoutDashboard`, `IconMovie`, `IconDeviceTv`, `IconTransfer`, `IconWebhook`, `IconArchive`, `IconSettings`
- Actions: `IconRefresh`, `IconTrash`, `IconRestore`, `IconPlayerStop`, `IconLoader2`
- UI: `IconDotsVertical`, `IconX`, `IconMenu2`, `IconCheck`, `IconChevronRight`, `IconChevronUp`, `IconChevronDown`, `IconSelector`

---

## Toast Notifications

Use `sonner` for toast notifications:

```tsx
import { toast } from 'sonner';

toast.success('Message');
toast.error('Error message');
```

---

## API Integration

- Base API client in `@/lib/api.ts`
- Uses Axios
- TanStack Query for caching and state management
- Query client configured in `@/lib/query-client.ts`

---

## WebSocket

- Socket.io client in `@/services/socket.ts`
- Used for real-time updates (transfers, notifications)
