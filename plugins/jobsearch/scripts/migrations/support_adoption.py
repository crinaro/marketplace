"""Line replacement shared by the 0.76.0 source adoption and the 0.76.1 legacy placeholders migrations.

One module of `migrations/` (design-component-segmentation.md §5); moved out of `migrate.py` unedited by S2."""


def _adoption_replace_lines(text, replacements):
    """`text` (a JSONL file's text) with the non-blank line at each index of `replacements` ({n: new line}) replaced and
    every other byte untouched. The index counts non-blank lines, as `_uid_text_read` does."""
    parts, n = text.split("\n"), 0              # NOT splitlines(): a raw U+2028 inside a JSON string is not a line break
    for i, line in enumerate(parts):
        if line.strip():
            if n in replacements:
                parts[i] = replacements[n]
            n += 1
    return "\n".join(parts)
