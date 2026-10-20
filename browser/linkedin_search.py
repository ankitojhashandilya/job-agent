"""Read LinkedIn search cards across the classic and component-based layouts."""

CARD_SELECTOR = (
    "li.scaffold-layout__list-item, li.jobs-search-results__list-item, "
    ".job-card-container, [role='button'][componentkey^='job-card-component-ref-']"
)

# Only use identifiers and text that the rendered search page actually exposes.
# Current cards are buttons without job links; their component keys carry the
# posting ID and their first three paragraphs carry title/company/location.
EXTRACT_CARDS = r"""({selector, limit}) => {
    const seen = new Set();
    const results = [];
    for (const card of document.querySelectorAll(selector)) {
        const link = card.querySelector('a.job-card-list__title--link, a[href*="/jobs/view/"]');
        const component = (card.getAttribute('componentkey') || '')
            .match(/^job-card-component-ref-(\d+)$/);
        const linkedId = link?.href.match(/\/jobs\/view\/(\d+)/);
        const id = component?.[1] || linkedId?.[1];
        if (!id || !card.getClientRects().length) continue;
        const url = `https://www.linkedin.com/jobs/view/${id}/`;
        if (seen.has(url)) continue;
        const paragraphs = card.querySelectorAll('p');
        const titleNode = component
            ? paragraphs[0]?.querySelector('span[aria-hidden="true"]') || paragraphs[0]
            : link.querySelector('strong') || link;
        const title = (titleNode?.innerText || '').split('\n')[0]
            .replace(/^Selected,\s*/i, '')
            .replace(/\s*(\(Verified job\)|with verification)\s*$/i, '').trim();
        const company = component ? paragraphs[1] : card.querySelector(
            '.artdeco-entity-lockup__subtitle span, .job-card-container__primary-description,' +
            '.job-card-container__company-name');
        const location = component ? paragraphs[2] : card.querySelector(
            '.artdeco-entity-lockup__caption, .job-card-container__metadata-item');
        if (!title) continue;
        seen.add(url);
        results.push({title, company:(company?.innerText || '').trim(),
            location:(location?.innerText || '').trim(), url});
        if (results.length >= limit) break;
    }
    return results;
}"""

SEARCH_STATE = r"""selector => {
    const text = document.body?.innerText || '';
    if (/\/checkpoint\//.test(location.pathname) ||
        /verify you are human|security verification|complete this captcha/i.test(text))
        return 'verification_required';
    if (/\/(login|uas\/login|authwall)(\/|$)/.test(location.pathname) ||
        Array.from(document.querySelectorAll('input[type=password]'))
            .some(el => el.getClientRects().length)) return 'login_required';
    if (Array.from(document.querySelectorAll(selector))
        .some(el => el.getClientRects().length && el.innerText.trim())) return 'ready';
    if (/no matching jobs|no results found|no jobs found|couldn't find any jobs/i.test(text) ||
        /(?:^|\n)\s*0 results\b/i.test(text)) return 'no_results';
    return '';
}"""


class LinkedInSearchError(RuntimeError):
    """A blocked or unrecognised page is not a valid empty job search."""


def read_search_results(page, limit: int, *, timeout_ms: int = 45000) -> list[dict]:
    """Wait for actual cards or an explicit terminal state, never a fixed delay."""
    from playwright.sync_api import TimeoutError

    try:
        page.wait_for_function(SEARCH_STATE, arg=CARD_SELECTOR, timeout=timeout_ms)
    except TimeoutError:
        pass  # Re-check once, then emit a useful error instead of saving [].
    state = page.evaluate(SEARCH_STATE, CARD_SELECTOR)
    if state == "login_required":
        raise LinkedInSearchError(
            "LinkedIn sign-in is required in the job-agent browser profile. "
            "Run login_linkedin.py, complete sign-in, then retry discovery."
        )
    if state == "verification_required":
        raise LinkedInSearchError(
            "LinkedIn requires manual security verification in the job-agent browser profile."
        )
    if state == "no_results":
        return []
    results = page.evaluate(EXTRACT_CARDS, {"selector": CARD_SELECTOR, "limit": limit})
    if results:
        return results
    raise LinkedInSearchError(
        "LinkedIn search did not expose readable job cards or an explicit no-results state. "
        "The page may still be loading or its layout has changed. "
        "Previous job results have not been replaced by this failed discovery."
    )
