-- Voice/audio ledger: one row per unique dialogue line, mirroring image_assets.
-- The pipeline's audio planner registers new dialogues as pending (status=0);
-- an external TTS process renders them and flips status=1 via mark_audio_generated.
-- Dedupe key: exact dialogue text (stripped of leading/trailing whitespace).
-- audio_code keeps the fabricator's naming scheme from the FIRST question that
-- used the line (e.g. ag05t01p01q01_inst.mp3); later questions reuse that code.

create table if not exists audio_assets (
    id             bigint generated always as identity primary key,
    audio_code     text not null,
    dialogue_text  text not null unique,
    audio_url      text,
    status         smallint not null default 0,   -- 0 = pending, 1 = generated
    milestone_code text,
    theme_code     text,
    playable_code  text,
    created_at     timestamptz not null default now()
);

-- Default-deny RLS: only the backend (secret key) can read/write.
alter table audio_assets enable row level security;
