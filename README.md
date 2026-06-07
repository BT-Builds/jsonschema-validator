# JSON Schema Validator API

Validate any JSON data against JSON Schema draft-07 specifications. A simple HTTP endpoint for developers who need quick validation without setting up local libraries.

## Endpoints

### POST /validate
Validate JSON data against a schema.

**Request:**
```json
{
  "data": {"name": "John", "age": 30},
  "schema": {
    "type": "object",
    "required": ["name"],
    "properties": {
      "name": {"type": "string", "minLength": 2},
      "age": {"type": "integer", "minimum": 0}
    }
  }
}
```

**Response:**
```json
{
  "valid": true,
  "errors": [],
  "suggestions": ["Data is valid against schema"]
}
```

### POST /validate/file
Same as /validate but returns summary format for file-based workflows.

### GET /schema/types
Returns supported JSON Schema keywords and types.

### GET /health
Health check endpoint (no auth required).

## Quick Start

```bash
curl -X POST https://jsonschema-validator.vercel.app/validate \
  -H "Content-Type: application/json" \
  -H "x-api-key: your-key" \
  -d '{"data": {"email": "test@example.com"}, "schema": {"type": "object", "required": ["email"], "properties": {"email": {"type": "string", "pattern": "^[^@]+@[^@]+\\.[^@]+$"}}}'
```

## Supported Schema Keywords

- **string**: minLength, maxLength, pattern, enum
- **number/integer**: minimum, maximum
- **array**: minItems, maxItems, items
- **object**: properties, required, additionalProperties

## Postman
[![Run in Postman](https://run.pstmn.io/button.svg)](https://raw.githubusercontent.com/BT-Builds/jsonschema-validator/main/postman_collection.json)
