-- Abu-Zahra Database Initialization Script
-- PostgreSQL Schema for Production

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "btree_gin";

-- Set timezone
SET timezone = 'UTC';

-- ============================================================================
-- ENUMS
-- ============================================================================

CREATE TYPE device_state AS ENUM (
    'online', 'offline', 'idle', 'busy', 'low_battery', 'charging'
);

CREATE TYPE command_state AS ENUM (
    'queued', 'delivered', 'executing', 'success', 'failed', 'timeout', 'cancelled', 'retrying'
);

CREATE TYPE priority_level AS ENUM ('critical', 'high', 'normal', 'low');

CREATE TYPE event_severity AS ENUM ('info', 'warning', 'error', 'critical');

-- ============================================================================
-- DEVICES TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS devices (
    id VARCHAR(64) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    model VARCHAR(100),
    manufacturer VARCHAR(100),
    android_version VARCHAR(20),
    sdk_version INTEGER DEFAULT 0,
    phone_number VARCHAR(20),
    country VARCHAR(10),
    carrier VARCHAR(100),
    state device_state DEFAULT 'offline',
    last_seen TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    linked_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    battery_level INTEGER DEFAULT 0,
    battery_charging BOOLEAN DEFAULT FALSE,
    storage_total BIGINT DEFAULT 0,
    storage_used BIGINT DEFAULT 0,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    permissions JSONB DEFAULT '{}',
    settings JSONB DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    encryption_key TEXT,
    auth_token TEXT,
    token_expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Device indexes
CREATE INDEX idx_devices_state ON devices(state);
CREATE INDEX idx_devices_last_seen ON devices(last_seen);
CREATE INDEX idx_devices_phone ON devices(phone_number);
CREATE INDEX idx_devices_country ON devices(country);
CREATE INDEX idx_devices_permissions ON devices USING GIN(permissions);

-- ============================================================================
-- COMMANDS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS commands (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    device_id VARCHAR(64) NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    command VARCHAR(100) NOT NULL,
    params JSONB DEFAULT '{}',
    state command_state DEFAULT 'queued',
    priority INTEGER DEFAULT 1,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    delivered_at TIMESTAMP WITH TIME ZONE,
    executed_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    result JSONB,
    error TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    timeout_seconds INTEGER DEFAULT 300,
    source VARCHAR(20) DEFAULT 'telegram',
    source_chat_id BIGINT,
    signature TEXT,
    nonce VARCHAR(128),
    client_ip VARCHAR(45)
);

-- Command indexes
CREATE INDEX idx_commands_device ON commands(device_id);
CREATE INDEX idx_commands_state ON commands(state);
CREATE INDEX idx_commands_created ON commands(created_at DESC);
CREATE INDEX idx_commands_priority ON commands(priority DESC, created_at ASC);
CREATE INDEX idx_commands_type ON commands(command);

-- ============================================================================
-- EVENTS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    device_id VARCHAR(64) REFERENCES devices(id) ON DELETE SET NULL,
    event_type VARCHAR(50) NOT NULL,
    data JSONB DEFAULT '{}',
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    severity event_severity DEFAULT 'info',
    client_ip VARCHAR(45),
    user_agent TEXT
);

-- Event indexes
CREATE INDEX idx_events_device ON events(device_id);
CREATE INDEX idx_events_type ON events(event_type);
CREATE INDEX idx_events_timestamp ON events(timestamp DESC);
CREATE INDEX idx_events_severity ON events(severity);
CREATE INDEX idx_events_data ON events USING GIN(data);

-- ============================================================================
-- SESSIONS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    device_id VARCHAR(64) REFERENCES devices(id) ON DELETE CASCADE,
    session_token VARCHAR(128) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE,
    last_activity TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    ip_address VARCHAR(45),
    user_agent TEXT,
    is_active BOOLEAN DEFAULT TRUE
);

-- Session indexes
CREATE INDEX idx_sessions_device ON sessions(device_id);
CREATE INDEX idx_sessions_token ON sessions(session_token);
CREATE INDEX idx_sessions_expires ON sessions(expires_at);

-- ============================================================================
-- AUDIT LOGS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    action VARCHAR(50) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    entity_id VARCHAR(64) NOT NULL,
    old_value JSONB,
    new_value JSONB,
    actor VARCHAR(100) NOT NULL,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    ip_address VARCHAR(45),
    metadata JSONB
);

-- Audit indexes
CREATE INDEX idx_audit_entity ON audit_logs(entity_type, entity_id);
CREATE INDEX idx_audit_timestamp ON audit_logs(timestamp DESC);
CREATE INDEX idx_audit_action ON audit_logs(action);

-- ============================================================================
-- FILES TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS files (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    device_id VARCHAR(64) NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    command_id UUID REFERENCES commands(id) ON DELETE SET NULL,
    path TEXT NOT NULL,
    filename VARCHAR(255) NOT NULL,
    size BIGINT DEFAULT 0,
    mime_type VARCHAR(100),
    hash VARCHAR(128),
    storage_path TEXT,
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE,
    metadata JSONB DEFAULT '{}'
);

-- File indexes
CREATE INDEX idx_files_device ON files(device_id);
CREATE INDEX idx_files_uploaded ON files(uploaded_at DESC);
CREATE INDEX idx_files_type ON files(mime_type);

-- ============================================================================
-- LOCATION HISTORY TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS location_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    device_id VARCHAR(64) NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    accuracy FLOAT,
    altitude FLOAT,
    speed FLOAT,
    bearing FLOAT,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    battery_level INTEGER,
    source VARCHAR(20) DEFAULT 'gps',
    address TEXT
);

-- Location indexes
CREATE INDEX idx_location_device ON location_history(device_id);
CREATE INDEX idx_location_timestamp ON location_history(timestamp DESC);
CREATE INDEX idx_location_coords ON location_history(latitude, longitude);
CREATE INDEX idx_location_device_time ON location_history(device_id, timestamp DESC);

-- ============================================================================
-- HEARTBEATS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS heartbeats (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    device_id VARCHAR(64) NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    battery_level INTEGER,
    battery_charging BOOLEAN,
    network_type VARCHAR(20),
    signal_strength INTEGER,
    memory_total BIGINT,
    memory_used BIGINT,
    cpu_usage FLOAT,
    storage_total BIGINT,
    storage_used BIGINT,
    temperature FLOAT
);

-- Heartbeat indexes
CREATE INDEX idx_heartbeats_device ON heartbeats(device_id);
CREATE INDEX idx_heartbeats_timestamp ON heartbeats(timestamp DESC);

-- ============================================================================
-- ALERTS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS alerts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    device_id VARCHAR(64) REFERENCES devices(id) ON DELETE CASCADE,
    alert_type VARCHAR(50) NOT NULL,
    severity event_severity DEFAULT 'warning',
    message TEXT,
    data JSONB DEFAULT '{}',
    triggered_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    acknowledged BOOLEAN DEFAULT FALSE,
    acknowledged_at TIMESTAMP WITH TIME ZONE,
    acknowledged_by VARCHAR(100)
);

-- Alert indexes
CREATE INDEX idx_alerts_device ON alerts(device_id);
CREATE INDEX idx_alerts_acknowledged ON alerts(acknowledged);
CREATE INDEX idx_alerts_triggered ON alerts(triggered_at DESC);

-- ============================================================================
-- WORKFLOWS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS workflows (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL,
    description TEXT,
    trigger_type VARCHAR(50) NOT NULL,
    trigger_config JSONB DEFAULT '{}',
    actions JSONB DEFAULT '[]',
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_triggered_at TIMESTAMP WITH TIME ZONE,
    trigger_count INTEGER DEFAULT 0
);

-- ============================================================================
-- FEATURE FLAGS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS feature_flags (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT,
    enabled BOOLEAN DEFAULT FALSE,
    conditions JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- SETTINGS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS settings (
    key VARCHAR(100) PRIMARY KEY,
    value JSONB NOT NULL,
    description TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================================================
-- BACKUP HISTORY TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS backup_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    device_id VARCHAR(64) REFERENCES devices(id) ON DELETE CASCADE,
    backup_type VARCHAR(20) NOT NULL,
    size BIGINT DEFAULT 0,
    file_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    storage_path TEXT,
    checksum VARCHAR(128)
);

-- ============================================================================
-- NONCES TABLE (for replay protection)
-- ============================================================================

CREATE TABLE IF NOT EXISTS nonces (
    nonce VARCHAR(128) PRIMARY KEY,
    device_id VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE INDEX idx_nonces_expires ON nonces(expires_at);

-- ============================================================================
-- FUNCTIONS AND TRIGGERS
-- ============================================================================

-- Update timestamp trigger function
CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply timestamp trigger to devices
CREATE TRIGGER devices_updated_at
    BEFORE UPDATE ON devices
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Apply timestamp trigger to workflows
CREATE TRIGGER workflows_updated_at
    BEFORE UPDATE ON workflows
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Apply timestamp trigger to feature_flags
CREATE TRIGGER feature_flags_updated_at
    BEFORE UPDATE ON feature_flags
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Cleanup expired sessions function
CREATE OR REPLACE FUNCTION cleanup_expired_sessions()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM sessions WHERE expires_at < NOW() OR (NOT is_active AND last_activity < NOW() - INTERVAL '24 hours');
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Cleanup expired nonces function
CREATE OR REPLACE FUNCTION cleanup_expired_nonces()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM nonces WHERE expires_at < NOW();
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Update device state on heartbeat function
CREATE OR REPLACE FUNCTION update_device_on_heartbeat()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE devices SET
        last_seen = NEW.timestamp,
        battery_level = NEW.battery_level,
        battery_charging = NEW.battery_charging,
        state = CASE
            WHEN NEW.battery_charging THEN 'charging'
            WHEN NEW.battery_level < 15 THEN 'low_battery'
            ELSE 'online'
        END,
        updated_at = NOW()
    WHERE id = NEW.device_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER heartbeat_update_device
    AFTER INSERT ON heartbeats
    FOR EACH ROW
    EXECUTE FUNCTION update_device_on_heartbeat();

-- ============================================================================
-- VIEWS
-- ============================================================================

-- Active devices view
CREATE OR REPLACE VIEW active_devices AS
SELECT 
    d.*,
    h.battery_level as current_battery,
    h.network_type,
    h.cpu_usage,
    h.timestamp as last_heartbeat
FROM devices d
LEFT JOIN LATERAL (
    SELECT * FROM heartbeats h2 
    WHERE h2.device_id = d.id 
    ORDER BY timestamp DESC 
    LIMIT 1
) h ON true
WHERE d.last_seen > NOW() - INTERVAL '5 minutes';

-- Command statistics view
CREATE OR REPLACE VIEW command_stats AS
SELECT 
    command,
    COUNT(*) as total_count,
    COUNT(*) FILTER (WHERE state = 'success') as success_count,
    COUNT(*) FILTER (WHERE state = 'failed') as failed_count,
    AVG(EXTRACT(EPOCH FROM (completed_at - created_at))) FILTER (WHERE state = 'success') as avg_duration_seconds,
    MAX(created_at) as last_executed
FROM commands
GROUP BY command;

-- Device activity summary
CREATE OR REPLACE VIEW device_activity AS
SELECT 
    d.id,
    d.name,
    d.state,
    COUNT(DISTINCT c.id) as total_commands,
    COUNT(DISTINCT c.id) FILTER (WHERE c.created_at > NOW() - INTERVAL '24 hours') as commands_24h,
    COUNT(DISTINCT e.id) FILTER (WHERE e.timestamp > NOW() - INTERVAL '24 hours') as events_24h,
    MAX(c.created_at) as last_command
FROM devices d
LEFT JOIN commands c ON d.id = c.device_id
LEFT JOIN events e ON d.id = e.device_id
GROUP BY d.id, d.name, d.state;

-- ============================================================================
-- INITIAL DATA
-- ============================================================================

-- Insert default settings
INSERT INTO settings (key, value, description) VALUES
    ('heartbeat_interval', '30', 'Heartbeat interval in seconds'),
    ('command_timeout', '300', 'Default command timeout in seconds'),
    ('max_retries', '3', 'Maximum command retry attempts'),
    ('offline_threshold', '300', 'Seconds before device is considered offline'),
    ('backup_retention_days', '30', 'Number of days to keep backups'),
    ('log_retention_days', '90', 'Number of days to keep logs'),
    ('rate_limit_per_minute', '60', 'Rate limit for API requests'),
    ('max_file_size_mb', '500', 'Maximum file upload size in MB')
ON CONFLICT (key) DO NOTHING;

-- Insert default feature flags
INSERT INTO feature_flags (name, description, enabled) VALUES
    ('websocket_realtime', 'Enable real-time WebSocket updates', true),
    ('location_tracking', 'Enable continuous location tracking', true),
    ('auto_backup', 'Enable automatic device backups', false),
    ('push_notifications', 'Enable push notifications', true),
    ('analytics', 'Enable usage analytics', true),
    ('beta_features', 'Enable beta features', false)
ON CONFLICT (name) DO NOTHING;

-- ============================================================================
-- GRANTS
-- ============================================================================

-- Grant permissions to application user
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO abuzahra;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO abuzahra;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO abuzahra;
