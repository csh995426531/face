import argparse
from pathlib import Path

from app.db.mysql import db_connect


def split_sql_statements(sql_text: str) -> list[str]:
    statements = []
    current = []
    in_single = False
    in_double = False
    in_backtick = False
    in_line_comment = False
    in_block_comment = False
    text = sql_text.lstrip("\ufeff")
    length = len(text)
    index = 0

    while index < length:
        char = text[index]
        next_char = text[index + 1] if index + 1 < length else ""
        previous_char = text[index - 1] if index > 0 else ""

        if in_line_comment:
            if char == "\n":
                in_line_comment = False
            index += 1
            continue

        if in_block_comment:
            if char == "*" and next_char == "/":
                in_block_comment = False
                index += 2
                continue
            index += 1
            continue

        if not (in_single or in_double or in_backtick):
            if char == "#":
                in_line_comment = True
                index += 1
                continue
            if char == "-" and next_char == "-" and (previous_char == "" or previous_char.isspace()):
                third_char = text[index + 2] if index + 2 < length else ""
                if third_char == "" or third_char.isspace():
                    in_line_comment = True
                    index += 2
                    continue
            if char == "/" and next_char == "*":
                in_block_comment = True
                index += 2
                continue

        if char == "'" and not (in_double or in_backtick):
            current.append(char)
            if in_single and next_char == "'":
                current.append(next_char)
                index += 2
                continue
            if not in_single:
                in_single = True
            elif previous_char != "\\":
                in_single = False
            index += 1
            continue

        if char == '"' and not (in_single or in_backtick):
            current.append(char)
            if in_double and next_char == '"':
                current.append(next_char)
                index += 2
                continue
            if not in_double:
                in_double = True
            elif previous_char != "\\":
                in_double = False
            index += 1
            continue

        if char == "`" and not (in_single or in_double):
            in_backtick = not in_backtick
            current.append(char)
            index += 1
            continue

        if char == ";" and not (in_single or in_double or in_backtick):
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            index += 1
            continue

        current.append(char)
        index += 1

    statement = "".join(current).strip()
    if statement:
        statements.append(statement)
    return statements


def run_sql_file(sql_file: str | Path) -> int:
    path = Path(sql_file)
    if not path.is_file():
        raise FileNotFoundError(f"SQL file not found: {path}")

    statements = split_sql_statements(path.read_text(encoding="utf-8"))
    if not statements:
        raise ValueError(f"SQL file contains no executable statements: {path}")

    with db_connect() as conn:
        for index, statement in enumerate(statements, start=1):
            try:
                conn.execute(statement)
            except Exception as exc:
                raise RuntimeError(f"failed at statement {index} in {path}") from exc
    return len(statements)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Execute a selected SQL migration file.")
    parser.add_argument("sql_file", help="Path to the SQL file to execute")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    count = run_sql_file(args.sql_file)
    print(f"Executed {count} statements from {args.sql_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
