import json
import hashlib
import time
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import Any, Optional

app = FastAPI(title="JSON Schema Validator API", version="1.0.0")
# === BT Builds Standard Middleware (auto-injected) ===
from fastapi.middleware.cors import CORSMiddleware as _BTCors
app.add_middleware(_BTCors, allow_origins=["*"], allow_methods=["*"],
    allow_headers=["*"], expose_headers=["X-RateLimit-Limit","X-RateLimit-Remaining","X-RateLimit-Reset"])

@app.middleware("http")
async def _bt_add_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Powered-By"] = "btbuilds"
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


# Simple in-memory rate limiting (per API key)
RATE_LIMITS = {}
RATE_LIMIT_WINDOW = 60  # seconds
RATE_LIMIT_MAX = 100  # requests per window

def get_api_key(x_api_key: str = None):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="API key required")
    # Simple rate limiting check
    now = time.time()
    if x_api_key not in RATE_LIMITS:
        RATE_LIMITS[x_api_key] = []
    # Clean old requests
    RATE_LIMITS[x_api_key] = [t for t in RATE_LIMITS[x_api_key] if now - t < RATE_LIMIT_WINDOW]
    if len(RATE_LIMITS[x_api_key]) >= RATE_LIMIT_MAX:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    RATE_LIMITS[x_api_key].append(now)
    return x_api_key

class ValidationRequest(BaseModel):
    data: Any
    schema: dict

class ValidationResponse(BaseModel):
    valid: bool
    errors: list = []
    suggestions: list = []


def validate_schema(data: Any, schema: dict) -> tuple[bool, list, list]:
    """Pure Python JSON Schema draft-07 validation"""
    errors = []
    suggestions = []
    
    # Check required fields
    if "required" in schema:
        if not isinstance(data, dict):
            errors.append({"path": "", "message": "Expected object for required fields check"})
        else:
            for field in schema["required"]:
                if field not in data:
                    errors.append({"path": f".{field}", "message": f"Missing required field: {field}"})
    
    # Check type
    if "type" in schema:
        schema_type = schema["type"]
        type_map = {
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "array": list,
            "object": dict,
            "null": type(None)
        }
        if schema_type in type_map:
            expected_type = type_map[schema_type]
            if schema_type == "number" and not isinstance(data, (int, float)):
                errors.append({"path": "", "message": f"Expected {schema_type}, got {type(data).__name__}"})
            elif schema_type != "number" and not isinstance(data, expected_type):
                errors.append({"path": "", "message": f"Expected {schema_type}, got {type(data).__name__}"})
    
    # Check string constraints
    if isinstance(data, str):
        if "minLength" in schema and len(data) < schema["minLength"]:
            errors.append({"path": "", "message": f"String too short (min {schema['minLength']})"})
        if "maxLength" in schema and len(data) > schema["maxLength"]:
            errors.append({"path": "", "message": f"String too long (max {schema['maxLength']})"})
        if "pattern" in schema:
            import re
            if not re.match(schema["pattern"], data):
                errors.append({"path": "", "message": f"String does not match pattern: {schema['pattern']}"})
        if "enum" in schema and data not in schema["enum"]:
            errors.append({"path": "", "message": f"Value not in enum: {schema['enum']}"})
    
    # Check number constraints
    if isinstance(data, (int, float)):
        if "minimum" in schema and data < schema["minimum"]:
            errors.append({"path": "", "message": f"Value below minimum ({schema['minimum']})"})
        if "maximum" in schema and data > schema["maximum"]:
            errors.append({"path": "", "message": f"Value above maximum ({schema['maximum']})"})
    
    # Check array constraints
    if isinstance(data, list):
        if "minItems" in schema and len(data) < schema["minItems"]:
            errors.append({"path": "", "message": f"Array too short (min {schema['minItems']})"})
        if "maxItems" in schema and len(data) > schema["maxItems"]:
            errors.append({"path": "", "message": f"Array too long (max {schema['maxItems']})"})
        if "items" in schema:
            for i, item in enumerate(data):
                item_valid, item_errors, _ = validate_schema(item, schema["items"])
                for err in item_errors:
                    err["path"] = f"[{i}]{err['path']}"
                    errors.append(err)
    
    # Check object properties
    if isinstance(data, dict) and "properties" in schema:
        for prop, prop_schema in schema["properties"].items():
            if prop in data:
                prop_valid, prop_errors, _ = validate_schema(data[prop], prop_schema)
                for err in prop_errors:
                    err["path"] = f".{prop}{err['path']}"
                    errors.append(err)
        
        # Check additionalProperties
        if "additionalProperties" in schema and schema["additionalProperties"] is False:
            allowed = set(schema.get("properties", {}).keys())
            extra = set(data.keys()) - allowed
            if extra:
                errors.append({"path": "", "message": f"Additional properties not allowed: {list(extra)}"})
    
    # Generate suggestions
    if not errors:
        suggestions.append("Data is valid against schema")
    else:
        suggestions.append("Fix validation errors to conform to schema")
    
    return len(errors) == 0, errors, suggestions


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/validate", response_model=ValidationResponse)
def validate(request: ValidationRequest, api_key: str = Depends(get_api_key)):
    """Validate a single item against a JSON schema"""
    if not isinstance(request.data, (dict, list, str, int, float, bool, type(None))):
        raise HTTPException(status_code=400, detail="Invalid JSON data")
    valid, errors, suggestions = validate_schema(request.data, request.schema)
    return ValidationResponse(valid=valid, errors=errors, suggestions=suggestions)


@app.post("/validate/file")
async def validate_file(request: ValidationRequest, api_key: str = Depends(get_api_key)):
    """Same as /validate but optimized for file-based workflows"""
    valid, errors, suggestions = validate_schema(request.data, request.schema)
    return {
        "valid": valid,
        "error_count": len(errors),
        "errors": errors[:10],
        "passed": valid
    }


@app.post("/bulk/validate")
def bulk_validate(request: dict, api_key: str = Depends(get_api_key)):
    """Validate multiple items against a JSON schema (up to 1000 items)"""
    items = request.get("items", [])
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="items must be an array")
    if len(items) > 1000:
        raise HTTPException(status_code=400, detail="Maximum 1000 items per request")
    
    schema = request.get("schema")
    if not schema or not isinstance(schema, dict):
        raise HTTPException(status_code=400, detail="schema is required")
    
    results = []
    successful = 0
    
    for item in items:
        if not isinstance(item, (dict, list, str, int, float, bool, type(None))):
            results.append({
                "input": str(item)[:100],
                "output": None,
                "error": "Invalid JSON data"
            })
        else:
            valid, errors, suggestions = validate_schema(item, schema)
            if valid:
                successful += 1
            results.append({
                "input": item,
                "output": {"valid": valid, "errors": errors, "suggestions": suggestions},
                "error": None
            })
    
    return {
        "results": results,
        "total": len(items),
        "successful": successful
    }


@app.post("/bulk/validate/file")
def bulk_validate_file(request: dict, api_key: str = Depends(get_api_key)):
    """Bulk validate optimized for file-based workflows"""
    items = request.get("items", [])
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="items must be an array")
    if len(items) > 1000:
        raise HTTPException(status_code=400, detail="Maximum 1000 items per request")
    
    schema = request.get("schema")
    if not schema or not isinstance(schema, dict):
        raise HTTPException(status_code=400, detail="schema is required")
    
    results = []
    successful = 0
    
    for item in items:
        if not isinstance(item, (dict, list, str, int, float, bool, type(None))):
            results.append({
                "input": str(item)[:100],
                "output": None,
                "error": "Invalid JSON data"
            })
        else:
            valid, errors, _ = validate_schema(item, schema)
            if valid:
                successful += 1
            results.append({
                "input": item,
                "output": {
                    "valid": valid,
                    "error_count": len(errors),
                    "errors": errors[:10],
                    "passed": valid
                },
                "error": None
            })
    
    return {
        "results": results,
        "total": len(items),
        "successful": successful
    }


@app.get("/schema/types")
def get_schema_types():  # No auth - just docs
    """Return common JSON Schema type patterns"""
    return {
        "types": ["string", "number", "integer", "boolean", "array", "object", "null"],
        "string_keywords": ["minLength", "maxLength", "pattern", "format", "enum"],
        "number_keywords": ["minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf"],
        "array_keywords": ["minItems", "maxItems", "items", "uniqueItems"],
        "object_keywords": ["properties", "required", "additionalProperties", "minProperties", "maxProperties"]
    }

try:
    from mangum import Mangum
    handler = Mangum(app, lifespan="off")
except ImportError:
    pass