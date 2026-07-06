"""Parser for JSON API responses."""

from typing import Any, Dict

from .base_parser import BaseParser


class JSONParser(BaseParser):
    def parse(self, content: Any, **kwargs) -> Dict[str, Any]:
        if isinstance(content, str):
            import json
            content = json.loads(content)
        return {"data": content}
