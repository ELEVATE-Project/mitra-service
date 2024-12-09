

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

    sanitized_content = story.content or ""
    should_show_story_heading = True

    html = f"""
    <div class="story-company2-div page-break">
        <div class="story-in-thirdpage">
            {f'<p class="story-heading-third">{title}</p>' if should_show_story_heading else ''}
            {(f'<img src="https://static-media.gritworks.ai/fe-images/PNG/GritPersona/line_story.png" '
              f'class="story-line-logo1-third" alt="line_story" />') if should_show_story_heading else ''}

            <div class="story-contentBox">
                <div style="position: relative; width: 90%; height: auto;">
                    {sanitized_content}
                </div>
                <img src="https://static-media.gritworks.ai/fe-images/PNG/GritPersona/line_story.png" 
                class="story-line1-logo" alt="line_story" />
            </div>
        </div>
    </div>
    """
    return html
