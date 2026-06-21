#!/usr/bin/env python3
'''
Code generator for the Tesla data layer.

Reads tesla_properties.json (the field registry) and emits a TeslaDataGen
QObject base class with one typed Q_PROPERTY (+ NOTIFY + getter + seeded
member) per field, plus three lookups used by the hand-written TeslaData
subclass: valueTypeForStream(), unitOf() and applyValue().

Generated files are committed to the source tree; re-run after editing the
registry (CMake target: regen_tesla_data). Usage:
    python generate_tesladata.py <registry.json> <out_gen.hh> <out_gen.cpp>
'''

import json
import sys

# protocol value_type tag -> (C++ type, QVariant accessor, member initialiser)
TYPE_MAP = {
    "double":   {"cpp": "double",       "variant": "toDouble", "init": " = 0.0",   "vt": 0},
    "string":   {"cpp": "QString",      "variant": "toString", "init": "",         "vt": 1},
    "bool":     {"cpp": "bool",         "variant": "toBool",   "init": " = false", "vt": 2},
    "location": {"cpp": "QVariantMap",  "variant": "toMap",    "init": "",         "vt": 3},
}

HEADER_BANNER = (
    "// GENERATED FILE - do not edit by hand.\n"
    "// Produced by core/tesla/generate_tesladata.py from tesla_properties.json.\n"
    "// Re-run via the `regen_tesla_data` CMake target after changing the registry.\n\n"
)


def qml_name(name: str) -> str:
    '''
    Converts a registry name to its QML/Q_PROPERTY name by lower-casing the
    first character only (e.g. BatteryLevel -> batteryLevel, ACChargingPower ->
    aCChargingPower). Deterministic; the rest of the name is left untouched.
    Arguments:
        name (str): PascalCase registry name.
    '''
    return name[0].lower() + name[1:]


def load_fields(registry_path: str):
    '''
    Loads and validates the registry, returning the list of field dicts.
    Arguments:
        registry_path (str): Path to tesla_properties.json.
    '''
    with open(registry_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    fields = data["properties"]
    seen_ids = set()
    seen_names = set()
    for field in fields:
        if field["type"] not in TYPE_MAP:
            raise ValueError(f"Unknown type {field['type']!r} for {field['name']}")
        if field["streamId"] in seen_ids:
            raise ValueError(f"Duplicate streamId {field['streamId']}")
        if field["name"] in seen_names:
            raise ValueError(f"Duplicate name {field['name']}")
        seen_ids.add(field["streamId"])
        seen_names.add(field["name"])
    return fields


def generate_header(fields) -> str:
    '''
    Builds the TeslaDataGen header text.
    Arguments:
        fields (list): Validated registry field dicts.
    '''
    props, getters, signals, members = [], [], [], []
    for field in fields:
        qn = qml_name(field["name"])
        cpp = TYPE_MAP[field["type"]]["cpp"]
        init = TYPE_MAP[field["type"]]["init"]
        props.append(
            f"    Q_PROPERTY({cpp} {qn} READ {qn} NOTIFY {qn}Changed)"
        )
        getters.append(f"    {cpp} {qn}() const {{ return m_{qn}; }}")
        signals.append(f"    void {qn}Changed();")
        members.append(f"    {cpp} m_{qn}{init};")

    return (
        HEADER_BANNER
        + "#ifndef FRONTEND_V2_TESLADATA_GEN_HH\n"
        + "#define FRONTEND_V2_TESLADATA_GEN_HH\n\n"
        + "#include <QObject>\n"
        + "#include <QString>\n"
        + "#include <QVariant>\n"
        + "#include <QVariantMap>\n\n"
        + "// Base class holding the generated Tesla telemetry properties. The\n"
        + "// hand-written TeslaData subclass decodes packets and calls applyValue().\n"
        + "class TeslaDataGen : public QObject {\n"
        + "    Q_OBJECT\n"
        + "\n".join(props) + "\n\n"
        + "public:\n"
        + "    explicit TeslaDataGen(QObject *parent = nullptr) : QObject(parent) {}\n\n"
        + "\n".join(getters) + "\n\n"
        + "    // Expected protocol value_type (0=double,1=string,2=bool,3=location)\n"
        + "    // for a stream id, or -1 if the id is not in the registry.\n"
        + "    static int valueTypeForStream(quint16 streamId);\n\n"
        + "    // Unit string for a property's QML name, or \"\" if unknown/unitless.\n"
        + "    Q_INVOKABLE QString unitOf(const QString &propertyName) const;\n\n"
        + "signals:\n"
        + "\n".join(signals) + "\n\n"
        + "protected:\n"
        + "    // Sets the field bound to streamId from value (interpreted per the\n"
        + "    // field's type) and emits its NOTIFY. Returns false if id is unknown.\n"
        + "    bool applyValue(quint16 streamId, const QVariant &value);\n\n"
        + "private:\n"
        + "\n".join(members) + "\n"
        + "};\n\n"
        + "#endif  // FRONTEND_V2_TESLADATA_GEN_HH\n"
    )


def generate_source(fields) -> str:
    '''
    Builds the TeslaDataGen source text.
    Arguments:
        fields (list): Validated registry field dicts.
    '''
    vt_cases, unit_entries, apply_cases = [], [], []
    for field in fields:
        qn = qml_name(field["name"])
        info = TYPE_MAP[field["type"]]
        vt_cases.append(f"        case {field['streamId']}: return {info['vt']};")
        if field["unit"]:
            unit_entries.append(
                f"        {{ QStringLiteral(\"{qn}\"), QStringLiteral(\"{field['unit']}\") }},"
            )
        apply_cases.append(
            f"        case {field['streamId']}: m_{qn} = value.{info['variant']}();"
            f" emit {qn}Changed(); return true;"
        )

    return (
        HEADER_BANNER
        + "#include \"tesladata_gen.hh\"\n\n"
        + "#include <QHash>\n\n"
        + "int TeslaDataGen::valueTypeForStream(quint16 streamId) {\n"
        + "    switch (streamId) {\n"
        + "\n".join(vt_cases) + "\n"
        + "        default: return -1;\n"
        + "    }\n"
        + "}\n\n"
        + "QString TeslaDataGen::unitOf(const QString &propertyName) const {\n"
        + "    static const QHash<QString, QString> units = {\n"
        + "\n".join(unit_entries) + "\n"
        + "    };\n"
        + "    return units.value(propertyName);\n"
        + "}\n\n"
        + "bool TeslaDataGen::applyValue(quint16 streamId, const QVariant &value) {\n"
        + "    switch (streamId) {\n"
        + "\n".join(apply_cases) + "\n"
        + "        default: return false;\n"
        + "    }\n"
        + "}\n"
    )


def main():
    '''Reads the registry and writes the generated header and source files.'''
    if len(sys.argv) != 4:
        print("usage: generate_tesladata.py <registry.json> <out.hh> <out.cpp>", file=sys.stderr)
        return 1
    registry_path, out_hh, out_cpp = sys.argv[1], sys.argv[2], sys.argv[3]
    fields = load_fields(registry_path)
    with open(out_hh, "w", encoding="utf-8", newline="\n") as f:
        f.write(generate_header(fields))
    with open(out_cpp, "w", encoding="utf-8", newline="\n") as f:
        f.write(generate_source(fields))
    print(f"Generated {len(fields)} Tesla properties -> {out_hh}, {out_cpp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
