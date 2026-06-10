from rknmon.db_schema import SCHEMA_SQL


def test_schema_defines_probe_nodes_table():
    assert "CREATE TABLE IF NOT EXISTS probe_nodes" in SCHEMA_SQL


def test_schema_adds_probe_node_id_to_probes():
    assert "probe_node_id INTEGER REFERENCES probe_nodes(id) ON DELETE CASCADE" in SCHEMA_SQL


def test_schema_defines_target_states_table():
    assert "CREATE TABLE IF NOT EXISTS target_states" in SCHEMA_SQL
    assert "UNIQUE (target_id, probe_node_id)" in SCHEMA_SQL
