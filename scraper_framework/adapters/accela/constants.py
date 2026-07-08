ADAPTER_NAME = "accela"
SIGNATURES = ["citizenaccess", "accela", "record details"]
SEARCH_WINDOW_YEARS = 2
MAX_CONCURRENT_PAGES = 4
WORKER_PAGE_NAVIGATION_RETRIES = 2
BROWSER_NAVIGATION_TIMEOUT_MS = 60000
BROWSER_POSTBACK_TIMEOUT_MS = 30000
BROWSER_RESULTS_TIMEOUT_MS = 30000


URLS = {
  "PASCO_COUNTY": {
    "agency_name": "Pasco County",
    "state": "FL",
    "service_provider_code": "PASCO",
    "base_url": "https://aca-prod.accela.com/pasco",
    "modules": [
      "Building",
      "Planning",
      "Permits",
      "Enforcement"
    ],
    "target_scrape_urls": {
    #   "Building": "https://aca-prod.accela.com/pasco/Cap/CapHome.aspx?module=Building&serviceProviderCode=PASCO",
      "Building": "https://aca-prod.accela.com/CITRUS/Cap/CapHome.aspx?module=Building",
      "Planning": "https://aca-prod.accela.com/pasco/Cap/CapHome.aspx?module=Planning&serviceProviderCode=PASCO",
      "Permits": "https://aca-prod.accela.com/pasco/Cap/CapHome.aspx?module=Permits&serviceProviderCode=PASCO",
      "Enforcement": "https://aca-prod.accela.com/pasco/Cap/CapHome.aspx?module=Enforcement&serviceProviderCode=PASCO"
    }
  },

  "CITY_OF_CHINO": {
    "agency_name": "City of Chino",
    "state": "CA",
    "service_provider_code": "CHINO",
    "base_url": "https://aca-prod.accela.com/CHINO",
    "modules": [
      "Building",
      "Planning",
      "Engineering"
    ],
    "target_scrape_urls": {
      "Building": "https://aca-prod.accela.com/CHINO/Cap/CapHome.aspx?module=Building&serviceProviderCode=CHINO",
      "Planning": "https://aca-prod.accela.com/CHINO/Cap/CapHome.aspx?module=Planning&serviceProviderCode=CHINO",
      "Engineering": "https://aca-prod.accela.com/CHINO/Cap/CapHome.aspx?module=Engineering&serviceProviderCode=CHINO"
    }
  }
}




SELECTOR_PRIORITIES = [
  "Commercial Multifamily",
  "Request CO/TCO/CC",
  "Residential New",
  "Sign Permit",
  "Residential",
]
