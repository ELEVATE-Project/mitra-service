import json
from bs4 import BeautifulSoup


def json_to_html(formatted_content):

    try:
        content_data = json.loads(formatted_content)
        print("type: ", type(content_data))
    except json.JSONDecodeError:
        return ""

    html_content = ""
    for block in content_data:
        print("block type: ", type(block))
        if isinstance(block, dict) and "type" in block and "data" in block:
            if block["type"] == "paragraph":
                text = block["data"].get("text", "")

                text = text.replace("\n\n", "<br><br>").replace("\n", "<br>")

                html_content += f"<p>{text}</p>"
        else:
            print(f"Unexpected block format: {block}")

    return html_content


def count_words_and_lines(text):

    word_count = 0
    lines = text.splitlines()

    for line in lines:
        word_count += len(line.split())

    return word_count, len(lines)


def split_content_based_on_words(content, max_words_per_page=400):
    soup = BeautifulSoup(content, "html.parser")
    chunks = []
    current_chunk = ""
    word_counter = 0

    for element in soup.find_all(["p", "br"]):  # Limit to <p> and <br>
        if element.name == "p":
            text = element.get_text(strip=True)
            words = text.split()  # Split paragraph into words
            paragraph_word_count = len(words)

            if paragraph_word_count > max_words_per_page:
                # Split paragraph into smaller parts
                for i in range(0, paragraph_word_count, max_words_per_page):
                    part = " ".join(words[i:i + max_words_per_page]) + "<br>"
                    if word_counter + len(part.split()) > max_words_per_page:
                        chunks.append(current_chunk)
                        current_chunk = part
                        word_counter = len(part.split())
                    else:
                        current_chunk += part
                        word_counter += len(part.split())
            else:
                if word_counter + paragraph_word_count > max_words_per_page:
                    chunks.append(current_chunk)
                    current_chunk = text + "<br>"
                    word_counter = paragraph_word_count
                else:
                    current_chunk += text + "<br>"
                    word_counter += paragraph_word_count

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def get_thirdpage_html(profile, story):

    profile_addresses = profile.profile_address.all().first()

    address_components = [
        profile_addresses.district if profile_addresses and profile_addresses.district else "",
        profile_addresses.block if profile_addresses and profile_addresses.block else "",
        profile_addresses.state if profile_addresses and profile_addresses.state else ""
    ]

    address_string = ", ".join(filter(None, address_components))
    title = (
        f"Peer Learning Groups: {story.title or ''} {address_string} "
        f"{profile.first_name or ''}'s initiative"
    )

    sanitized_content = json_to_html(story.formatted_content)
    should_show_story_heading = True

    content_chunks = split_content_based_on_words(sanitized_content)

    html_pages = []
    for chunk in content_chunks:
        html_page = f"""
        <div class="story-company2-div page-break">
            <div class="story-in-thirdpage">
                {f'<p class="story-heading-third">{title}</p>' if should_show_story_heading else ''}
                {(f'<img src="https://static-media.gritworks.ai/fe-images/PNG/GritPersona/line_story.png" '
                  f'class="story-line-logo1-third" alt="line_story" />') if should_show_story_heading else ''}

                <div class="story-contentBox">
                    <div style="position: relative; width: 90%; height: auto;">
                        {chunk}
                    </div>
                    <img src="https://static-media.gritworks.ai/fe-images/PNG/GritPersona/line_story.png" 
                    class="story-line1-logo" alt="line_story" />
                </div>
            </div>
        </div>
        """
        html_pages.append(html_page)
        should_show_story_heading = False

    return "\n".join(html_pages)
