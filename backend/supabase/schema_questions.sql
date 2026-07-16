-- Question storage: run once in Supabase SQL Editor.
-- Companion to image_assets (see app/core/db.py).

create table if not exists runs (
    id                 text primary key,        -- run id, e.g. "20260716_143022"
    created_at         timestamptz not null default now(),
    theme              text not null,
    target_age         smallint not null,
    milestone_code     text not null,
    theme_code         text not null,
    status             text not null default 'completed',  -- completed | partial | failed
    blueprint_text     text,
    eval_grade         text,
    eval_score         numeric,
    eval_result        jsonb,
    metrics            jsonb,
    evaluator_history  jsonb,
    play_url           text,
    s3_uri             text,
    error              text
);
create index if not exists runs_milestone_theme_idx on runs (milestone_code, theme_code);

create table if not exists questions (
    id                           bigint generated always as identity primary key,
    run_id                       text not null references runs(id) on delete cascade,
    row_index                    smallint not null,

    playable_code                text not null,
    playable_name                text,
    layer                        text,
    template                     text,

    instruction_text             text,
    instruction_vo               text,
    instruction_vo_file          text,

    text_in_question             text,
    audio_in_question            text,
    audio_in_question_file       text,
    vo_for_question              text,
    vo_for_question_file         text,
    image_in_question_detail     text,
    image_in_question_name       text,

    correct_answer               text,
    correct_answer_vo_file       text,
    correct_answer_image         text,
    correct_answer_image_detail  text,

    other_options                text[],
    other_options_vo_file        text[],
    other_options_image          text[],
    other_options_image_detail   text[],

    stt_expectation              text,
    concept                      text,
    pattern                      text,
    notes                        text,

    created_at                   timestamptz not null default now(),
    unique (run_id, row_index)
);
create index if not exists questions_run_id_idx on questions (run_id);
create index if not exists questions_playable_code_idx on questions (playable_code);
