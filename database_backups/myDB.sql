CREATE TYPE user_roles AS ENUM ('Admin', 'Operator', 'Viewer');
CREATE TYPE inspection_status AS ENUM ('Good', 'Defected');

CREATE TABLE Users (
    user_id  SERIAL PRIMARY KEY,
    username  VARCHAR(80) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    user_role  user_roles NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    is_active  BOOLEAN DEFAULT TRUE
);

CREATE TABLE Sessions (
    session_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INT NOT NULL REFERENCES Users(user_id) ON DELETE CASCADE,
	created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
	CHECK (expires_at > created_at)
);

CREATE INDEX idx_sessions_user_id ON Sessions(user_id);
CREATE INDEX idx_sessions_expires_at ON Sessions(expires_at);

CREATE TABLE Sensors (
    sensor_id VARCHAR(100) PRIMARY KEY,
    sensor_type VARCHAR(50) NOT NULL,
	min_threshold NUMERIC(10,2),
    max_threshold NUMERIC(10,2),
	unit VARCHAR(20),
	is_active BOOLEAN DEFAULT TRUE,
    CHECK (min_threshold IS NULL OR max_threshold IS NULL OR min_threshold < max_threshold)
);

CREATE TABLE Inspections (
    inspection_id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES Users(user_id) ON DELETE RESTRICT,
    sensor_id VARCHAR(100) REFERENCES Sensors(sensor_id) ON DELETE RESTRICT,
    status inspection_status NOT NULL,
    defect_type VARCHAR(255),
    cv_image_url TEXT,
    inspected_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_inspections_user_time ON Inspections(user_id, inspected_at DESC);
CREATE INDEX idx_inspections_sensor_time ON Inspections(sensor_id, inspected_at DESC);
CREATE INDEX idx_inspections_status_time ON Inspections(status, inspected_at DESC);
