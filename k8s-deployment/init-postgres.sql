CREATE SCHEMA IF NOT EXISTS eventuate;
CREATE SCHEMA IF NOT EXISTS public;
GRANT ALL ON SCHEMA eventuate TO eventuate;
GRANT ALL ON SCHEMA public TO eventuate;

CREATE TABLE IF NOT EXISTS eventuate.flyway_schema_history (
    installed_rank integer NOT NULL,
    version character varying(50),
    description character varying(200) NOT NULL,
    type character varying(20) NOT NULL,
    script character varying(1000) NOT NULL,
    checksum integer,
    installed_by character varying(100) NOT NULL,
    installed_on timestamp without time zone DEFAULT now() NOT NULL,
    execution_time integer NOT NULL,
    success boolean NOT NULL,
    CONSTRAINT flyway_schema_history_pk PRIMARY KEY (installed_rank)
);

INSERT INTO eventuate.flyway_schema_history (installed_rank, version, description, type, script, checksum, installed_by, installed_on, execution_time, success)
VALUES
(1, '1', 'eventuate postgres', 'SQL', 'V1__eventuate_postgres.sql', -1097379770, 'eventuate', now(), 12, true),
(2, '2', 'tram database postgres', 'SQL', 'V2__tram_database_postgres.sql', 1234772164, 'eventuate', now(), 4, true),
(3, '3', 'eventuate postgres wal', 'SQL', 'V3__eventuate_postgres_wal.sql', -168390987, 'eventuate', now(), 8, true),
(4, '1005', 'MyMigration', 'JDBC', 'io.eventuate.tram.spring.flyway.V1005__MyMigration', NULL, 'eventuate', now(), 10, true)
ON CONFLICT (installed_rank) DO UPDATE SET
    version = EXCLUDED.version,
    description = EXCLUDED.description,
    type = EXCLUDED.type,
    script = EXCLUDED.script,
    checksum = EXCLUDED.checksum,
    installed_by = EXCLUDED.installed_by,
    installed_on = EXCLUDED.installed_on,
    execution_time = EXCLUDED.execution_time,
    success = EXCLUDED.success;
