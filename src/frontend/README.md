# LEMON Web Frontend

React + TypeScript frontend for the LEMON workflow platform.

## Prerequisites

- Node.js 18+
- npm or yarn
- Backend API running (see main project README)

## Setup

```bash
# Install dependencies
npm install

# Start development server
npm run dev
```

The frontend runs at `http://localhost:5173` and proxies API requests to `http://localhost:5001`.

## Development

```bash
# Start dev server with hot reload
npm run dev

# Type check
npm run build

# Lint
npm run lint
```

## Production Build

```bash
npm run build
npm run preview  # Preview production build locally
```

## Configuration

The app uses Vite's proxy in development. For production, set the `VITE_API_URL` environment variable:

```bash
VITE_API_URL=https://api.example.com npm run build
```

## Project Structure

```
src/
├── api/          # API client, Socket.IO, REST endpoints
├── stores/       # Zustand state management
├── hooks/        # Custom React hooks
├── types/        # TypeScript type definitions
├── utils/        # Helper functions (canvas math, etc.)
├── components/   # React components
│   ├── Canvas.tsx       # SVG workflow canvas
│   ├── Chat.tsx         # Orchestrator chat interface
│   ├── Header.tsx       # App header with actions
│   ├── Palette.tsx      # Block palette sidebar
│   ├── RightSidebar.tsx # Library & inputs panel
│   ├── Modals.tsx       # Library & validation modals
│   └── WorkflowBrowser.tsx
├── App.tsx       # Main app component
└── main.tsx      # Entry point
```
