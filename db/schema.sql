-- T5 永続化スキーマ（Supabase / PostgreSQL）
--
-- 単一店舗デモなので、アプリ状態の各「バケット」
--   （dynamic_constraints / availability / manager_questions / base_headcounts など）を
--   key = バケット名 の1行に value(JSONB) で丸ごと保存する。
-- src/persistence.py の SupabaseStore がこの表を upsert / select する。
--
-- 使い方: Supabase の SQL Editor でこのファイルを一度だけ実行しておく。
--   その後 .env に SUPABASE_URL と SUPABASE_SERVICE_ROLE_KEY を入れると自動で Supabase 保存に切り替わる。
--
-- 認証/RLS は使わない（CLAUDE.md の方針: 単一店舗デモ・service_role キーで接続）。

create table if not exists app_state (
  key        text primary key,                 -- バケット名（"dynamic_constraints" 等）
  value      jsonb not null,                    -- そのバケットの中身（list / dict / スカラ）
  updated_at timestamptz not null default now() -- 監査用（任意）
);

-- 更新時に updated_at を自動更新（任意・運用の見やすさのため）
create or replace function set_app_state_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists trg_app_state_updated_at on app_state;
create trigger trg_app_state_updated_at
  before update on app_state
  for each row execute function set_app_state_updated_at();
