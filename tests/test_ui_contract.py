from html.parser import HTMLParser
from pathlib import Path


INDEX = Path(__file__).parents[1] / "static" / "index.html"


class ReportTabsParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tabs = []
        self.panels = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set((attrs.get("class") or "").split())
        if tag == "button" and "segment-tab" in classes:
            self.tabs.append(attrs)
        if tag == "div" and "results-tab-panel" in classes:
            self.panels[attrs.get("id")] = attrs


def test_report_tabs_have_matching_panels_and_short_sections():
    parser = ReportTabsParser()
    parser.feed(INDEX.read_text(encoding="utf-8"))

    expected_sections = [
        "overview", "findings", "dns", "email", "security",
        "web", "subdomains", "network", "remediation",
    ]
    assert [tab.get("data-target") for tab in parser.tabs] == expected_sections
    assert len({tab.get("id") for tab in parser.tabs}) == len(parser.tabs)

    tab_ids = {tab.get("id") for tab in parser.tabs}
    for tab in parser.tabs:
        panel = parser.panels[tab["aria-controls"]]
        assert panel.get("data-segment") == tab.get("data-target")
        assert panel.get("aria-labelledby") == tab.get("id")
    for panel in parser.panels.values():
        assert panel.get("aria-labelledby") in tab_ids
