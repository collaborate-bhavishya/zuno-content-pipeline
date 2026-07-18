-- Theme catalog: the durable registry behind the admin CSV upload and the
-- overnight batch. theme_code is stable forever once assigned (content files
-- reference it). Run once in the Supabase SQL Editor.

create table if not exists themes (
    theme       text primary key,          -- normalized name, e.g. 'jungle'
    theme_code  text not null unique,      -- stable code, e.g. 'T07'
    ages        text not null default '3-7',   -- '3-7' | '4,5' | ...
    active      boolean not null default true, -- false = keep but skip in batch
    notes       text,
    created_at  timestamptz not null default now()
);

-- Default-deny RLS: only the backend (secret key) reads/writes.
alter table themes enable row level security;

-- Seed the original catalog (codes must match already-generated content).
insert into themes (theme, theme_code) values
    ('animals', 'T01'), ('bus', 'T02'), ('colors', 'T03'), ('family', 'T04'),
    ('food', 'T05'), ('fruits', 'T06'), ('jungle', 'T07'), ('ocean', 'T08'),
    ('space', 'T09'), ('weather', 'T10')
on conflict (theme) do nothing;
