import re


def extract_error_blocks(log_path):
    error_blocks = []
    current_block = []
    in_error_block = False

    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                components = line.split(" - ")
                error_message = (
                    "ERROR" in components[3] if len(components) > 4 else False
                )
                if error_message or "Traceback" in line:
                    if current_block:
                        error_blocks.append("".join(current_block).rstrip("\n"))
                        current_block = []
                    in_error_block = True
                    current_block.append(line)
                elif in_error_block:
                    if (
                        line.startswith("\t")
                        or line.strip() == ""
                        or not re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", line)
                        or line.startswith("Traceback")
                    ):
                        current_block.append(line)
                    else:
                        error_blocks.append("".join(current_block).rstrip("\n"))
                        current_block = []
                        in_error_block = False

            if current_block:
                error_blocks.append("".join(current_block).rstrip("\n"))
    except Exception as e:
        print(f"Failed to extract error blocks from {log_path}: {e}")

    return error_blocks
