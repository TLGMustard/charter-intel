"""
pipeline/utils/schema_validator.py
JSON schema validation for pipeline stage outputs.
Wraps jsonschema with pipeline-friendly return types.
"""
from __future__ import annotations
import json
import os
from typing import Optional

import jsonschema

from pipeline import ValidationResult

_schema_cache: dict[str, dict] = {}


def validate_against_schema(data: dict, schema_path: str) -> ValidationResult:
    """Validate data against a JSON schema file. Returns ValidationResult."""
    schema = _load_schema(schema_path)
    if schema is None:
        return ValidationResult(
            valid=False,
            errors=[f"Schema not found: {schema_path}"]
        )
    try:
        jsonschema.validate(instance=data, schema=schema)
        return ValidationResult(valid=True)
    except jsonschema.ValidationError as e:
        return ValidationResult(valid=False, errors=[str(e.message)])
    except jsonschema.SchemaError as e:
        return ValidationResult(valid=False, errors=[f"Schema error: {e.message}"])


def _load_schema(schema_path: str) -> Optional[dict]:
    if schema_path in _schema_cache:
        return _schema_cache[schema_path]
    if not os.path.exists(schema_path):
        return None
    with open(schema_path) as f:
        schema = json.load(f)
    _schema_cache[schema_path] = schema
    return schema
