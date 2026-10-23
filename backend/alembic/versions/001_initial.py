"""Initial schema with pgvector HNSW index.

Revision ID: 001_initial
Revises:
Create Date: 2026-10-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE app_meta (
            id integer PRIMARY KEY CHECK (id = 1),
            embedding_model text NOT NULL DEFAULT '',
            embedding_dimensions integer NOT NULL DEFAULT 1536,
            index_revision integer NOT NULL DEFAULT 0,
            prompt_version text NOT NULL DEFAULT '',
            seed_version text NOT NULL DEFAULT '',
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("INSERT INTO app_meta (id) VALUES (1)")
    op.execute(
        """
        CREATE TABLE documents (
            id uuid PRIMARY KEY,
            tenant_id text NOT NULL,
            user_id text NOT NULL,
            title text NOT NULL,
            manufacturer text NOT NULL,
            machine_model text NOT NULL,
            equipment_type text NOT NULL,
            plant text NOT NULL,
            document_revision text NOT NULL,
            effective_date date NULL,
            filename text NOT NULL,
            mime_type text NOT NULL,
            storage_key text NOT NULL,
            size_bytes integer NOT NULL,
            status text NOT NULL,
            is_demo boolean NOT NULL DEFAULT false,
            current_version_id uuid NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE document_versions (
            id uuid PRIMARY KEY,
            document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            revision text NOT NULL,
            effective_date date NULL,
            storage_key text NOT NULL,
            checksum text NOT NULL,
            is_current boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        ALTER TABLE documents
        ADD CONSTRAINT fk_documents_current_version
        FOREIGN KEY (current_version_id) REFERENCES document_versions(id) ON DELETE SET NULL
        """
    )
    op.execute(
        """
        CREATE TABLE document_chunks (
            id uuid PRIMARY KEY,
            tenant_id text NOT NULL,
            document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            version_id uuid NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
            chunk_index integer NOT NULL,
            content text NOT NULL,
            token_count integer NOT NULL CHECK (token_count > 0),
            page_start integer NOT NULL,
            page_end integer NOT NULL,
            section_id text NOT NULL,
            section_title text NOT NULL,
            section_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
            manufacturer text NOT NULL,
            machine_model text NOT NULL,
            revision text NOT NULL,
            effective_date date NULL,
            embedding vector(1536) NOT NULL,
            embedding_model text NOT NULL,
            search_vector tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
            has_table boolean NOT NULL DEFAULT false,
            injection_suspected boolean NOT NULL DEFAULT false,
            metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE ingestion_jobs (
            id uuid PRIMARY KEY,
            tenant_id text NOT NULL,
            user_id text NOT NULL,
            document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            status text NOT NULL,
            stage text NOT NULL,
            progress integer NOT NULL DEFAULT 0,
            error text NULL,
            locked_at timestamptz NULL,
            started_at timestamptz NULL,
            finished_at timestamptz NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE chat_sessions (
            id uuid PRIMARY KEY,
            tenant_id text NOT NULL,
            user_id text NOT NULL,
            title text NOT NULL,
            manufacturer text NULL,
            machine_model text NULL,
            retain_until timestamptz NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE chat_messages (
            id uuid PRIMARY KEY,
            session_id uuid NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
            tenant_id text NOT NULL,
            user_id text NOT NULL,
            role text NOT NULL CHECK (role IN ('user', 'assistant')),
            content text NOT NULL,
            route text NULL,
            blocks jsonb NOT NULL DEFAULT '{}'::jsonb,
            citations jsonb NOT NULL DEFAULT '[]'::jsonb,
            confidence_score double precision NULL,
            confidence_label text NULL,
            confidence_detail jsonb NOT NULL DEFAULT '{}'::jsonb,
            warnings jsonb NOT NULL DEFAULT '[]'::jsonb,
            blocked boolean NOT NULL DEFAULT false,
            block_reason text NULL,
            prompt_version text NULL,
            experiment jsonb NOT NULL DEFAULT '{}'::jsonb,
            usage jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE retrieval_runs (
            id uuid PRIMARY KEY,
            message_id uuid NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
            session_id uuid NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
            tenant_id text NOT NULL,
            query text NOT NULL,
            rewritten_query text NOT NULL,
            route text NOT NULL,
            fusion jsonb NOT NULL DEFAULT '{}'::jsonb,
            score_components jsonb NOT NULL DEFAULT '{}'::jsonb,
            latency_ms double precision NOT NULL DEFAULT 0,
            vector_space text NOT NULL DEFAULT '',
            embedding_model text NOT NULL DEFAULT '',
            index_revision integer NOT NULL DEFAULT 0,
            attempt integer NOT NULL DEFAULT 1,
            trace jsonb NOT NULL DEFAULT '[]'::jsonb,
            guardrail jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE retrieved_evidence (
            id uuid PRIMARY KEY,
            retrieval_run_id uuid NOT NULL REFERENCES retrieval_runs(id) ON DELETE CASCADE,
            chunk_id uuid NULL REFERENCES document_chunks(id) ON DELETE SET NULL,
            document_id uuid NULL REFERENCES documents(id) ON DELETE SET NULL,
            source_type text NOT NULL,
            rank integer NOT NULL,
            rrf_score double precision NULL,
            vector_rank integer NULL,
            bm25_rank integer NULL,
            vector_similarity double precision NULL,
            bm25_score double precision NULL,
            rerank_score double precision NULL,
            score_components jsonb NOT NULL DEFAULT '{}'::jsonb,
            page_start integer NULL,
            page_end integer NULL,
            section_id text NULL,
            section_title text NULL,
            section_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
            document_title text NULL,
            revision text NULL,
            snippet text NOT NULL,
            manufacturer text NULL,
            machine_model text NULL,
            excluded boolean NOT NULL DEFAULT false,
            exclude_reason text NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE mcp_tool_calls (
            id uuid PRIMARY KEY,
            message_id uuid NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
            session_id uuid NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
            tenant_id text NOT NULL,
            tool_name text NOT NULL,
            arguments jsonb NOT NULL DEFAULT '{}'::jsonb,
            result jsonb NULL,
            status text NOT NULL,
            is_mock boolean NOT NULL DEFAULT true,
            error text NULL,
            latency_ms double precision NOT NULL DEFAULT 0,
            manufacturer text NULL,
            audit jsonb NOT NULL DEFAULT '{}'::jsonb,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE evaluation_runs (
            id uuid PRIMARY KEY,
            tenant_id text NOT NULL,
            status text NOT NULL,
            experiment jsonb NOT NULL DEFAULT '{}'::jsonb,
            metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
            started_at timestamptz NOT NULL DEFAULT now(),
            finished_at timestamptz NULL,
            error text NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE evaluation_results (
            id uuid PRIMARY KEY,
            run_id uuid NOT NULL REFERENCES evaluation_runs(id) ON DELETE CASCADE,
            case_id text NOT NULL,
            category text NOT NULL,
            question text NOT NULL,
            expected jsonb NOT NULL DEFAULT '{}'::jsonb,
            actual jsonb NOT NULL DEFAULT '{}'::jsonb,
            scores jsonb NOT NULL DEFAULT '{}'::jsonb,
            latency_ms double precision NOT NULL DEFAULT 0,
            prompt_tokens integer NOT NULL DEFAULT 0,
            completion_tokens integer NOT NULL DEFAULT 0,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE feedback (
            id uuid PRIMARY KEY,
            message_id uuid NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
            tenant_id text NOT NULL,
            user_id text NOT NULL,
            rating text NOT NULL CHECK (rating IN ('up', 'down')),
            comment text NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX documents_tenant_created_idx ON documents (tenant_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX documents_tenant_model_idx ON documents (tenant_id, manufacturer, machine_model)"
    )
    op.execute(
        "CREATE INDEX document_chunks_scope_idx ON document_chunks (tenant_id, manufacturer, machine_model)"
    )
    op.execute("CREATE INDEX document_chunks_document_idx ON document_chunks (document_id)")
    op.execute("CREATE INDEX document_chunks_section_idx ON document_chunks (section_id)")
    op.execute("CREATE INDEX document_chunks_search_idx ON document_chunks USING gin (search_vector)")
    op.execute("CREATE INDEX document_chunks_metadata_idx ON document_chunks USING gin (metadata)")
    op.execute(
        """
        CREATE INDEX document_chunks_embedding_hnsw
        ON document_chunks USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
        """
    )
    op.execute(
        "CREATE INDEX ingestion_jobs_status_idx ON ingestion_jobs (status, created_at)"
    )
    op.execute(
        "CREATE INDEX chat_sessions_scope_idx ON chat_sessions (tenant_id, user_id, updated_at DESC)"
    )
    op.execute("CREATE INDEX chat_messages_session_idx ON chat_messages (session_id, created_at)")
    op.execute("CREATE INDEX retrieval_runs_message_idx ON retrieval_runs (message_id)")
    op.execute("CREATE INDEX retrieved_evidence_run_idx ON retrieved_evidence (retrieval_run_id, rank)")
    op.execute("CREATE INDEX mcp_tool_calls_message_idx ON mcp_tool_calls (message_id, created_at)")
    op.execute("CREATE INDEX evaluation_results_run_idx ON evaluation_results (run_id)")
    op.execute("CREATE INDEX feedback_message_idx ON feedback (message_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS feedback")
    op.execute("DROP TABLE IF EXISTS evaluation_results")
    op.execute("DROP TABLE IF EXISTS evaluation_runs")
    op.execute("DROP TABLE IF EXISTS mcp_tool_calls")
    op.execute("DROP TABLE IF EXISTS retrieved_evidence")
    op.execute("DROP TABLE IF EXISTS retrieval_runs")
    op.execute("DROP TABLE IF EXISTS chat_messages")
    op.execute("DROP TABLE IF EXISTS chat_sessions")
    op.execute("DROP TABLE IF EXISTS ingestion_jobs")
    op.execute("DROP TABLE IF EXISTS document_chunks")
    op.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS fk_documents_current_version")
    op.execute("DROP TABLE IF EXISTS document_versions")
    op.execute("DROP TABLE IF EXISTS documents")
    op.execute("DROP TABLE IF EXISTS app_meta")
