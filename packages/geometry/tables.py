"""Typed Parquet from canonical contracts, including all-null optional columns."""
import pyarrow as pa
import pyarrow.parquet as pq


def contract_schema(model):
    schema = model.model_json_schema()
    definitions = schema.get("$defs", {})
    def arrow(spec):
        if "$ref" in spec:
            return arrow(definitions[spec["$ref"].split("/")[-1]])
        if "anyOf" in spec:
            return arrow(next(s for s in spec["anyOf"] if s.get("type") != "null"))
        kind = spec.get("type")
        if kind == "string": return pa.string()
        if kind == "integer": return pa.int64()
        if kind == "number": return pa.float64()
        if kind == "boolean": return pa.bool_()
        if kind == "array": return pa.list_(arrow(spec["items"]))
        if kind == "object": return pa.struct([(name, arrow(s)) for name, s in spec["properties"].items()])
        raise ValueError(f"Unsupported Parquet schema type: {spec}")
    return pa.schema([(name, arrow(spec)) for name, spec in schema["properties"].items()])


def write_contracts(path, model, rows):
    validated = [model.model_validate(row).model_dump(mode="json") for row in rows]
    pq.write_table(pa.Table.from_pylist(validated, schema=contract_schema(model)), path, compression="zstd")
    return validated
