# Vercel Inventory App

This folder contains a Vercel-ready version of the inventory app.

It is a static web app today:

- No Python server needed
- No SQLite database needed
- Deploys directly to Vercel
- Saves demo/working data in the browser with `localStorage`
- Keeps the same stock-in, stock-out, transfer, barcode lookup, and camera
  scanner workflow

Because it uses browser storage for now, the data is not shared between
different computers or phones yet. Supabase should be added later for shared
cloud storage.

## Run locally

From this folder:

```bash
npm run dev
```

Then open:

```text
http://127.0.0.1:8000
```

## Build locally

```bash
npm run build
```

The deployable static files are copied to:

```text
dist/
```

## Deploy to Vercel

1. Push this repository to GitHub.
2. Go to Vercel and create a new project.
3. Import the GitHub repository.
4. Set **Root Directory** to:

   ```text
   inventory_system/vercel_app
   ```

5. Use these settings:

   ```text
   Framework Preset: Other
   Build Command: npm run build
   Output Directory: dist
   ```

6. Deploy.

## Later: connect Supabase

When you are ready for shared cloud data:

1. Create a Supabase project.
2. Run:

   ```text
   inventory_system/supabase/schema.sql
   ```

   in the Supabase SQL editor.

3. Add Supabase URL and anon key to the Vercel project environment variables.
4. Replace the local browser store in:

   ```text
   public/data-store.js
   ```

   with calls to Supabase tables/views/functions:

   - `stock_in`
   - `stock_out`
   - `transfer_stock`
   - `current_stock`
   - `movement_history`

The UI is already written against an inventory-store interface, so the Supabase
work can stay mostly inside `data-store.js`.
