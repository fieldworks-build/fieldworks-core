// ============================================================
// Fieldworks Graph Schema for LadybugDB
// Plant-agnostic — node/relationship tables only, no seed data.
// ============================================================
// Install: brew install ladybug  (or pip install ladybug-client)
// Run:     lbug -p ./fieldworks.db
// Load:    :source schema.cypher
//
// This schema defines structure only. To populate the static layer from a
// plant's topology.yaml, use fieldworks.topology.seeder.seed_topology().
// A worked example deployment (seed data + example queries) lives at
// examples/waterworks/schema_seed.cypher in this repo.
// ============================================================


// ── NODE TABLES ──────────────────────────────────────────────

// The facility — top level node, one per deployment
CREATE NODE TABLE Facility (
    id           STRING PRIMARY KEY,
    name         STRING,
    description  STRING,
    timezone     STRING,
    units_system STRING
);

// Process areas — map to Specialist agents
CREATE NODE TABLE ProcessArea (
    id               STRING PRIMARY KEY,
    name             STRING,
    description      STRING,
    specialist_prompt STRING    // Area-level context injected into specialist system prompt
);

// Equipment types — class definitions, defined once
CREATE NODE TABLE EquipmentType (
    id          STRING PRIMARY KEY,
    name        STRING,
    description STRING
);

// Equipment instances — deployed equipment, one per physical unit
CREATE NODE TABLE Equipment (
    id           STRING PRIMARY KEY,
    name         STRING,
    description  STRING,
    commissioned DATE,
    notes        STRING         // Operational history; persists across sessions
);

// Attributes — measurable properties, defined on a type
CREATE NODE TABLE Attribute (
    id                  STRING PRIMARY KEY,
    name                STRING,
    description         STRING,
    units               STRING,
    data_type           STRING,      // numeric | boolean | discrete — see AttributeDef
    normal_range_min    DOUBLE,       // numeric only
    normal_range_max    DOUBLE,       // numeric only
    normal_range_desc   STRING,       // numeric only
    normal_state        BOOLEAN,      // boolean only — expected steady-state value
    allowed_values      STRING[],     // discrete only
    normal_values       STRING[],     // discrete only — subset of allowed_values, not alarming
    writable            BOOLEAN,
    requires_confirmation BOOLEAN,   // True = operator approval required before write
    write_limit_min     DOUBLE,      // Hard lower bound enforced by control-mcp
    write_limit_max     DOUBLE       // Hard upper bound enforced by control-mcp
);

// Tag bindings — join between topology and the protocol surface
CREATE NODE TABLE TagBinding (
    id         STRING PRIMARY KEY,
    tag_id     STRING,
    confidence STRING,    // verified | inferred | suspect
    notes      STRING
);

// Fault modes — failure patterns, defined on a type
CREATE NODE TABLE FaultMode (
    id          STRING PRIMARY KEY,
    name        STRING,
    description STRING,
    severity    STRING    // advisory | warning | critical
);

// ── DYNAMIC / LEARNED LAYER ───────────────────────────────────

// A diagnostic session that produced a structured finding
CREATE NODE TABLE Incident (
    id         STRING PRIMARY KEY,
    session_id STRING,
    timestamp  TIMESTAMP,
    diagnosis  STRING,
    confidence DOUBLE,
    status     STRING,    // normal | anomaly_detected | fault_detected
    outcome    STRING     // monitoring | action_taken | recovered | unresolved
);

// Something a specialist learned that should persist across sessions
CREATE NODE TABLE Observation (
    id         STRING PRIMARY KEY,
    session_id STRING,
    timestamp  TIMESTAMP,
    text       STRING,
    confidence DOUBLE,
    specialist STRING
);

// An operator decision — mirrors action_events in SQLite, queryable by graph traversal
CREATE NODE TABLE OperatorDecision (
    id          STRING PRIMARY KEY,
    session_id  STRING,
    timestamp   TIMESTAMP,
    action_type STRING,
    value       STRING,
    decision    STRING,    // approved | denied
    operator_id STRING
);


// ── RELATIONSHIP TABLES ──────────────────────────────────────

// Structural relationships
CREATE REL TABLE CONTAINS_AREA      (FROM Facility TO ProcessArea);
CREATE REL TABLE CONTAINS_EQUIPMENT (FROM ProcessArea TO Equipment);
CREATE REL TABLE IS_TYPE            (FROM Equipment TO EquipmentType);
CREATE REL TABLE DEFINES_ATTRIBUTE  (FROM EquipmentType TO Attribute);
CREATE REL TABLE HAS_FAULT_MODE     (FROM EquipmentType TO FaultMode);
CREATE REL TABLE AFFECTS            (FROM FaultMode TO Attribute);  // Diagnostic indicators
CREATE REL TABLE BINDS_ATTRIBUTE    (FROM Equipment TO TagBinding, attribute_id STRING);
CREATE REL TABLE BINDING_OF         (FROM TagBinding TO Attribute);
CREATE REL TABLE FEEDS_INTO         (FROM ProcessArea TO ProcessArea, description STRING);

// Dynamic / learned relationships
CREATE REL TABLE INCIDENT_ON        (FROM Incident TO Equipment);
CREATE REL TABLE CONSISTENT_WITH    (FROM Incident TO FaultMode);
CREATE REL TABLE OBSERVATION_ON     (FROM Observation TO Equipment);
CREATE REL TABLE DECISION_ON        (FROM OperatorDecision TO Equipment);
CREATE REL TABLE PRECEDES           (FROM Incident TO Incident, hours_apart DOUBLE);
// PRECEDES: (A)-[:PRECEDES {hours_apart: X}]->(B) = A occurred X hours before B
// Query pattern: MATCH (cause)-[:PRECEDES]->(effect) to find causality chains
