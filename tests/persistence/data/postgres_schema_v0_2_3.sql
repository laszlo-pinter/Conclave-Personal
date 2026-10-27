-- PostgreSQL-Schema von Conclave v0.2.3 (initialize_schema aus Tag v0.2.3, pg_dump 16).
-- Fuer den Migrationstest in tests/persistence/test_postgres_context_reports.py.
CREATE TABLE public._migrations (
    id text NOT NULL,
    description text NOT NULL,
    applied_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE public.agents (
    id text NOT NULL,
    name text NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    api_key_enc text DEFAULT ''::text NOT NULL,
    role text DEFAULT ''::text NOT NULL,
    topic text DEFAULT ''::text NOT NULL,
    system_prompt text DEFAULT ''::text NOT NULL,
    preset text DEFAULT ''::text NOT NULL,
    api_url text DEFAULT ''::text NOT NULL,
    response_path text DEFAULT ''::text NOT NULL,
    message_format text DEFAULT 'standard'::text NOT NULL,
    created_at timestamp with time zone NOT NULL
);
CREATE TABLE public.audit_log (
    id text NOT NULL,
    "timestamp" timestamp with time zone NOT NULL,
    operation text NOT NULL,
    conversation_id text NOT NULL,
    participant_id text NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    success boolean NOT NULL,
    error_message text,
    user_id text,
    input_tokens integer,
    output_tokens integer
);
CREATE TABLE public.config (
    key text NOT NULL,
    value text NOT NULL
);
CREATE TABLE public.conversations (
    id text NOT NULL,
    status text NOT NULL,
    topic text DEFAULT ''::text NOT NULL,
    floor text,
    rules text DEFAULT ''::text NOT NULL,
    created_at timestamp with time zone NOT NULL
);
CREATE TABLE public.messages (
    id text NOT NULL,
    conversation_id text NOT NULL,
    author_type text NOT NULL,
    author_id text,
    content text NOT NULL,
    sequence integer NOT NULL,
    created_at timestamp with time zone NOT NULL
);
CREATE TABLE public.participants (
    id text NOT NULL,
    conversation_id text NOT NULL,
    participant_type text NOT NULL,
    name text NOT NULL,
    created_at timestamp with time zone NOT NULL
);
CREATE TABLE public.runs (
    id text NOT NULL,
    conversation_id text NOT NULL,
    kind text NOT NULL,
    participants text NOT NULL,
    started_at timestamp with time zone NOT NULL,
    finished_at timestamp with time zone,
    status text NOT NULL,
    error text
);
CREATE TABLE public.tool_events (
    id text NOT NULL,
    conversation_id text NOT NULL,
    message_id text,
    run_id text,
    participant_id text NOT NULL,
    tool text NOT NULL,
    status text NOT NULL,
    input_json text NOT NULL,
    output_json text NOT NULL,
    error text,
    created_at timestamp with time zone NOT NULL
);
CREATE TABLE public.usage_records (
    id text NOT NULL,
    run_id text NOT NULL,
    conversation_id text NOT NULL,
    participant_id text NOT NULL,
    provider text NOT NULL,
    model text NOT NULL,
    input_tokens integer,
    output_tokens integer,
    created_at timestamp with time zone NOT NULL
);
ALTER TABLE ONLY public._migrations
    ADD CONSTRAINT _migrations_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.agents
    ADD CONSTRAINT agents_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.config
    ADD CONSTRAINT config_pkey PRIMARY KEY (key);
ALTER TABLE ONLY public.conversations
    ADD CONSTRAINT conversations_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.participants
    ADD CONSTRAINT participants_pkey PRIMARY KEY (conversation_id, id);
ALTER TABLE ONLY public.runs
    ADD CONSTRAINT runs_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.tool_events
    ADD CONSTRAINT tool_events_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.usage_records
    ADD CONSTRAINT usage_records_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.messages
    ADD CONSTRAINT messages_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.conversations(id);
ALTER TABLE ONLY public.participants
    ADD CONSTRAINT participants_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.conversations(id);
ALTER TABLE ONLY public.runs
    ADD CONSTRAINT runs_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.conversations(id);
ALTER TABLE ONLY public.tool_events
    ADD CONSTRAINT tool_events_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.conversations(id);
ALTER TABLE ONLY public.tool_events
    ADD CONSTRAINT tool_events_message_id_fkey FOREIGN KEY (message_id) REFERENCES public.messages(id);
ALTER TABLE ONLY public.tool_events
    ADD CONSTRAINT tool_events_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.runs(id);
ALTER TABLE ONLY public.usage_records
    ADD CONSTRAINT usage_records_conversation_id_fkey FOREIGN KEY (conversation_id) REFERENCES public.conversations(id);
ALTER TABLE ONLY public.usage_records
    ADD CONSTRAINT usage_records_run_id_fkey FOREIGN KEY (run_id) REFERENCES public.runs(id);
INSERT INTO public._migrations VALUES ('005_personal_runs', 'Personal-Runs und UsageRecords', '2026-10-27 02:43:37.914061+00');
INSERT INTO public._migrations VALUES ('006_tool_events', 'Tool-Events fuer deterministische Backend-Aktionen', '2026-10-27 02:43:37.915178+00');
