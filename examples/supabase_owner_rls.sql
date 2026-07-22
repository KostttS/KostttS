-- Sanitized Supabase RLS example.
-- Public profiles may be read by anyone, while writes are owner-only.

alter table public.service_providers enable row level security;

drop policy if exists "Public can read service providers"
  on public.service_providers;

create policy "Public can read service providers"
  on public.service_providers
  for select
  using (true);

drop policy if exists "Authenticated users can create their own profile"
  on public.service_providers;

create policy "Authenticated users can create their own profile"
  on public.service_providers
  for insert
  to authenticated
  with check (auth.uid() = owner_id);

drop policy if exists "Owners can update their own profile"
  on public.service_providers;

create policy "Owners can update their own profile"
  on public.service_providers
  for update
  to authenticated
  using (auth.uid() = owner_id)
  with check (auth.uid() = owner_id);

-- Intentionally no DELETE policy:
-- rows cannot be deleted through the public or authenticated client API.
-- Administrative deletion should use a trusted server-side workflow.
