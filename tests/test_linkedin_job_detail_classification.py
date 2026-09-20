from agent.observe import _classify_page_type


class _Locator:
    def __init__(self, text: str = "", count: int = 0):
        self._text = text
        self._count = count

    @property
    def first(self):
        return self

    def count(self):
        return self._count

    def inner_text(self, timeout=None):
        return self._text


class _LinkedInJobPage:
    url = "https://www.linkedin.com/jobs/view/123456/"

    def locator(self, selector):
        if selector == "body":
            return _Locator("Data Engineer role details")
        # The header search input is intentionally not modelled here: a
        # LinkedIn job-view URL must win over header navigation heuristics.
        return _Locator()


def test_linkedin_job_view_is_a_job_detail_not_a_search_page():
    assert _classify_page_type(_LinkedInJobPage(), "unknown") == "job_details"
