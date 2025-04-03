# ------------------------------------------------------------------------------
# This file allows you to look up a specific e621 tag and it returns how many
# posts were made each year over the past several years featuring that tag.
# Default behaviour prints each year's post count to standard output as well as
# a CSV file named e621_tag_count.csv, and multiple tags are treated as separate
# queries. Tags already in the CSV file are skipped.
#
# Usage: e621_tag_counter.py [flags] [tags]
# Optional flags:
#     -c: Concatenate tags instead of treating each as a separate query.
#     -o: Print to standard output only, not file.
#     -p [X..Y]: Queries for tags on pages X to Y (inclusive) from e621's
#         list of tags sorted by total count.
#     -w: Overwrites tags already in the CSV file.
#
# Written in 2025 by Yoriyari.
# ------------------------------------------------------------------------------

import sys, csv, os, re
from urllib.parse import quote_plus as url_encode_plus
from playwright.sync_api import sync_playwright, Playwright, TimeoutError

CURRENT_YEAR = 2025
INITIAL_BOUND_SCORE = 512 # For batched counting with >750 pages of posts
INITIAL_INTERVAL_SCORE = 512 # For batched counting with >750 pages of posts
OUTPUT_FILE = "e621_tag_count.csv"

# ------------------------------------------------------------------------------

def tag_counter() -> None:
    output_to_file = "-o" not in sys.argv
    queries = get_queries()
    if queries:
        print(f"Scraping yearly post count for {len(queries)} tags...")
    else:
        print("Found zero tags to scrape posts for. Aborting.")
    with sync_playwright() as playwright:
        run_tag_count(playwright, queries, output_to_file)

def get_queries() -> list:
    arguments = [tag.lower() for tag in sys.argv[1:]]
    if "-o" in arguments:
        arguments.remove("-o")
    if "-p" in arguments:
        i = arguments.index("-p")
        page_range = arguments.pop(i+1)
        arguments.pop(i)
        arguments += get_tag_names_by_page_range(page_range)
    skip_known_tags = True
    if "-w" in arguments:
        arguments.remove("-w")
        skip_known_tags = False
    if "-c" in arguments:
        arguments.remove("-c")
        if arguments:
            return [" ".join(arguments)]
    if skip_known_tags:
        arguments = remove_known_tags(arguments)
    return arguments

def get_tag_names_by_page_range(page_range: str) -> list:
    match = re.match(r"^(\d+)(\.\.(\d+))?$", page_range)
    if not match:
        raise Exception("No page range defined after -p flag. Format: \"-p X\" or \"-p X..Y\"")
    start = int(match.group(1))
    if match.group(2):
        end = int(match.group(3))
    else:
        end = start
    with sync_playwright() as playwright:
        return run_tag_names_list(playwright, start, end)

def run_tag_names_list(playwright: Playwright, first_page: int, last_page: int) -> list:
    browser = playwright.firefox.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    initialize_page(page)
    print(f"Scraping tags from pages {first_page} to {last_page}...")
    names = parse_tag_names_from_page(page, first_page, last_page)
    context.close()
    browser.close()
    return names

def parse_tag_names_from_page(page, first_page, last_page) -> list:
    try:
        names = []
        for i in range(first_page, last_page+1):
            page.goto(f"https://e621.net/tags?commit=Search&page={i}&search%5Bhide_empty%5D=1&search%5Border%5D=count")
            links = page.get_by_role("link").all()
            for link in links:
                if not link.get_attribute("href").startswith("/posts?tags="):
                    continue
                names.append(link.inner_text())
        return names
    except TimeoutError:
        print("\nWebpage timed out -- Retrying...\n")
        return parse_tag_names_from_page(page, first_page, last_page)

def remove_known_tags(tags: list) -> list:
    if not os.path.isfile(OUTPUT_FILE):
        return tags
    with open(OUTPUT_FILE, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        tags = {tag.lower(): None for tag in tags}
        for row in reader:
            if row["Tag"].lower() in tags:
                tags.pop(row["Tag"].lower())
    return list(tags)

def run_tag_count(playwright: Playwright, queries: list, output_to_file: bool) -> None:
    browser = playwright.firefox.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    initialize_page(page)
    for tags in queries:
        print_post_total(page, tags, output_to_file)
    context.close()
    browser.close()

def initialize_page(page, url="https://e621.net/posts") -> None:
    page.goto(url)
    page.get_by_role("button", name="I agree and am over").click()

def print_post_total(page, tags, output_to_file) -> None:
    if output_to_file:
        new_row = {"Tag": tags}
    print(f'\n{tags}')
    for year in range(18, 0, -1): # (18, 0, -1)
        count = get_post_count_for_year(page, year, tags)
        if output_to_file:
            new_row[str(CURRENT_YEAR-year)] = count
        print(CURRENT_YEAR-year, count)
    if output_to_file:
        update_csv_file(new_row)

def update_csv_file(new_row):
    if not os.path.isfile(OUTPUT_FILE):
        open(OUTPUT_FILE, mode="w").close()
    with open(OUTPUT_FILE, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        data = []
        overwrote_row = False
        for row in reader:
            if row["Tag"].lower() == new_row["Tag"].lower():
                overwrote_row = True
                new_row["Tag"] = row["Tag"]
                data.append(new_row)
            else:
                data.append(row)
        if not overwrote_row:
            data.append(new_row)
    with open(OUTPUT_FILE, mode="w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(new_row.keys()))
        writer.writeheader()
        writer.writerows(data)

def get_post_count_for_year(page, year, tags) -> int:
    try:
        year_tags = url_encode_plus(f"{tags} status:any date:{year}_yesteryears_ago")
        return get_post_count(page, year_tags)
    except TimeoutError:
        print("\nWebpage timed out -- Retrying...\n")
        return get_post_count_for_year(page, year, tags)

def get_post_count(page, tags, is_batched=False) -> int:
    page.goto(f"https://e621.net/posts?tags={tags}")
    pagination = page.get_by_label("Pagination")
    data_total = int(pagination.get_attribute("data-total"))
    if data_total == 0:
        return 0
    if data_total > 1:
        if data_total >= 750:
            if is_batched:
                return None
            else:
                return get_batched_post_count(page, tags)
        page.locator(".page.last").click()
    page.wait_for_load_state("load")
    return 75 * (data_total-1) + get_post_count_on_current_page(page)

def get_batched_post_count(page, tags) -> int:
    bound = INITIAL_BOUND_SCORE
    interval = INITIAL_INTERVAL_SCORE
    count = 0
    while bound > 0:
        batched_tags = f"{tags} score:{max(1, bound-interval+1)}..{bound}"
        batch_count = get_post_count(page, batched_tags, is_batched=True)
        if batch_count == None:
            interval = interval // 2
            continue
        count += batch_count
        bound -= interval
    batched_tags = f"{tags} score:>{INITIAL_BOUND_SCORE}"
    count += get_post_count(page, batched_tags, is_batched=False)
    batched_tags = f"{tags} score:<=0"
    count += get_post_count(page, batched_tags, is_batched=False)
    return count

def get_post_count_on_current_page(page) -> int:
    anon_filter = page.locator(".blacklist-toggle-all")
    if anon_filter and anon_filter.is_visible():
        if anon_filter.first.inner_text() == "Disable All Filters":
            anon_filter.first.click()
    post_count = len(page.get_by_role("link", name="post #").all())
    hidden_notice = page.locator(".info.hidden-posts-notice")
    if hidden_notice and hidden_notice.is_visible():
        text_hidden = hidden_notice.first.inner_text()
        post_count += int(re.match(r"^(\d+)", text_hidden).group(1))
    return post_count

# ------------------------------------------------------------------------------

if __name__ == "__main__":
    tag_counter()
