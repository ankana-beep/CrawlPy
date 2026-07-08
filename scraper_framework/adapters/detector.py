from __future__ import annotations

from bs4 import BeautifulSoup

from adapters.accela.adapter import AccelaAdapter
from adapters.arcgis.adapter import ArcGISAdapter
from adapters.base.base_adapter import BaseAdapter
from adapters.civicplus.adapter import CivicPlusAdapter
from adapters.generic.adapter import GenericAdapter
from adapters.mygovernmentonline.adapter import MyGovernmentOnlineAdapter
from adapters.opengov.adapter import OpenGovAdapter
from adapters.tyler_energov.adapter import TylerEnerGovAdapter


def build_adapters() -> list[BaseAdapter]:
    return [
        AccelaAdapter(),
        MyGovernmentOnlineAdapter(),
        TylerEnerGovAdapter(),
        OpenGovAdapter(),
        ArcGISAdapter(),
        CivicPlusAdapter(),
    ]


class AdapterDetector:
    def __init__(self, adapters: list[BaseAdapter]) -> None:
        self.adapters = adapters
        self.fallback = GenericAdapter()

    def detect(self, url: str, html: str, soup: BeautifulSoup) -> BaseAdapter:
        for adapter in self.adapters:
            if adapter.can_handle(url, html, soup):
                return adapter
        return self.fallback
