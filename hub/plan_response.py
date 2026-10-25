"""Decode model plans, repairing only an empty object key with no value."""
import json


def decode(raw):
    value = raw.strip()
    if value.startswith('```'):
        value = value.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    for repairs in range(9):
        try:
            return json.loads(value), repairs
        except json.JSONDecodeError as error:
            # JSON itself confirms this is an object key, not text inside a
            # report. Only remove a valueless empty member after a comma.
            end = error.pos
            while end and value[end - 1].isspace():
                end -= 1
            start = end - 2
            comma = start - 1
            while comma >= 0 and value[comma].isspace():
                comma -= 1
            if (repairs == 8 or error.msg != "Expecting ':' delimiter"
                    or value[start:end] != '""' or comma < 0 or value[comma] != ','
                    or error.pos >= len(value) or value[error.pos] not in ',}'):
                raise
            value = value[:comma] + value[end:]
