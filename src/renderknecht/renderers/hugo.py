import copy
import re

import yaml
from yaml import SafeLoader

from util import yaml as util_yaml

CSLReferences = list | None
References = dict


def transform_references(references: CSLReferences) -> References:
    if not references:
        return {}
    return {reference["id"]: reference for reference in references if "id" in reference}


def add_hugo_header(yaml_metadata: dict) -> dict:
    result = copy.copy(yaml_metadata)
    result["header_src"] = "header.jpg"
    return result


def inline_references(markdown: str, references: References) -> str:
    pattern_brackets = r"\[.*?\]"
    pattern_keys = r"@\w+"

    def replace_keys(match: re.Match) -> str:
        key = match.group(0)[1:]
        if key in references and "URL" in references[key]:
            return f"[reference]({references[key]['URL']})"
        return match.group(0)

    def replace_brackets(match: re.Match) -> str:
        content = match.group(0)
        new_content = re.sub(pattern_keys, replace_keys, content)
        if new_content != content:
            return f"({new_content[1:-1]})"
        return new_content

    return re.sub(pattern_brackets, replace_brackets, markdown)


def add_more_section(yaml_metadata: dict) -> str:
    more = yaml_metadata.get("more", "")
    if more:
        return f"{more}\n<!--more-->\n\n"
    return ""


def transform_markdown_tables(markdown: str) -> str:
    def replace_table_with_caption(match: re.Match) -> str:
        table_content = match.group(2)
        caption = match.group(4).strip()
        new_table_format = f'{{{{< table title="{caption}" >}}}}\n' f"{table_content}\n" f"{{{{< /table >}}}}"
        return new_table_format

    # Regex to match the markdown table with the caption
    table_with_caption_pattern = re.compile(
        r"((\|.+?\|\n(\|\:?.*?\|\n)+).*?\nTable:\s*(.*?))(?=\n|$)",
        re.DOTALL | re.MULTILINE,
    )

    # Replace the matched pattern using the defined function
    transformed_markdown = table_with_caption_pattern.sub(replace_table_with_caption, markdown)
    return transformed_markdown


def prepare_markdown(hedgedoc_markdown: str) -> str:
    doc_pattern = r"^---\s*(.*?)---\s*(.*)"
    match = re.match(doc_pattern, hedgedoc_markdown, re.DOTALL)
    if not match:
        return hedgedoc_markdown

    yaml_str: str = match.group(1)
    md_str: str = match.group(2)
    yaml_metadata = (
        yaml.load(
            f"---\n{yaml_str}",
            Loader=SafeLoader,
        )
        or {}
    )

    references: References = transform_references(yaml_metadata.pop("references", None))

    yaml_metadata = add_hugo_header(yaml_metadata)

    return (
        f"---\n{yaml.dump(yaml_metadata, Dumper=util_yaml.Dumper)}---\n\n"
        f"{add_more_section(yaml_metadata)}"
        f"{transform_markdown_tables(inline_references(md_str, references))}"
    )
