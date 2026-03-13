-- Init script for PostgreSQL (Run via docker-compose on fresh mount)

CREATE TABLE IF NOT EXISTS agents (
    id UUID PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    version VARCHAR(50),
    config JSONB,           -- Agent properties and configs
    status VARCHAR(20),     -- created/running/paused/completed/failed
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY,
    agent_id UUID REFERENCES agents(id),
    goal TEXT,
    thread_id VARCHAR(255),
    status VARCHAR(20),
    dag JSONB,              -- Task DAG structure
    current_step INT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS task_steps (
    id UUID PRIMARY KEY,
    task_id UUID REFERENCES tasks(id),
    step_index INT,
    action_type VARCHAR(20),  -- tool_call / delegate / respond
    plan JSONB,               -- LLM reasoning plan
    result JSONB,             -- Execution result
    latency_ms INT,
    model_used VARCHAR(100),
    token_usage JSONB,        -- {prompt_tokens, completion_tokens}
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tool_logs (
    id UUID PRIMARY KEY,
    task_step_id UUID REFERENCES task_steps(id),
    tool_name VARCHAR(255),
    input_params JSONB,
    output_result JSONB,
    sandbox_type VARCHAR(20),
    permissions_used TEXT[],
    latency_ms INT,
    success BOOLEAN,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
CREATE INDEX IF NOT EXISTS idx_agents_created_at ON agents(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_agent_id ON tasks(agent_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_task_steps_task_step ON task_steps(task_id, step_index);
CREATE INDEX IF NOT EXISTS idx_tool_logs_task_step_id ON tool_logs(task_step_id);
CREATE INDEX IF NOT EXISTS idx_tool_logs_tool_name ON tool_logs(tool_name);
CREATE INDEX IF NOT EXISTS idx_tool_logs_success ON tool_logs(success);
