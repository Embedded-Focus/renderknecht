# ruff: noqa: ANN401

from typing import Any

import yaml
from yaml import ScalarNode

YAMLMetadata = dict | None


class Dumper(yaml.Dumper):
    """Alternative Dumper that respects correct indentation of sequence nodes.

    See: https://github.com/yaml/pyyaml/issues/234#issuecomment-765894586
    """

    def increase_indent(self, flow: bool = False, *args: Any, **kwargs: Any) -> Any:
        del args  # unused
        del kwargs  # unused
        return super().increase_indent(flow=flow, indentless=False)


def configure() -> None:
    def str_presenter(dumper: yaml.Dumper, data: Any) -> ScalarNode:
        # see: https://stackoverflow.com/a/33300001
        if len(data.splitlines()) > 1:
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
        return dumper.represent_scalar("tag:yaml.org,2002:str", data)

    yaml.add_representer(str, str_presenter)
