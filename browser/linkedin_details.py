"""Description extraction that waits for content rather than network idleness."""

READ_DESCRIPTION = r"""() => {
    for (const selector of ['#job-details', '.jobs-description-content__text',
        '.jobs-description__content', '.jobs-box__html-content']) {
        const node = document.querySelector(selector);
        if (node?.getClientRects().length && node.innerText.trim().length >= 200)
            return node.innerText.trim();
    }
    const text = document.body?.innerText || '';
    const start = /(?:about the job|job description)\s*\n/i.exec(text);
    if (!start) return '';
    const content = text.slice(start.index + start[0].length);
    const endings = ['about the company', 'meet the hiring team',
        'people you can reach out to', 'set alert for similar jobs',
        'similar jobs', 'see how you compare', 'show less', 'see less'];
    const end = new RegExp('\\n(?:' + endings.join('|') + ')\\b', 'i').exec(content);
    return (end ? content.slice(0, end.index) : content).trim();
}"""


def wait_for_description(page, timeout_ms: int = 20000) -> str:
    from playwright.sync_api import TimeoutError

    try:
        page.wait_for_function(f"() => ({READ_DESCRIPTION})().length >= 200", timeout=timeout_ms)
    except TimeoutError:
        pass
    return page.evaluate(READ_DESCRIPTION)
