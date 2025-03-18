
def get_first_page_html(profile, story, project):
    profile_addresses = profile.profile_address.all().first()
    current_state = profile_addresses.state if profile_addresses else ""
    company_logo = profile.company.get_public_url()
    print("logo: ", company_logo)
    address_components = [
        profile_addresses.district if profile_addresses and profile_addresses.district else "",
        profile_addresses.block if profile_addresses and profile_addresses.block else "",
        profile_addresses.state if profile_addresses and profile_addresses.state else ""
    ]

    address_string = ", ".join(filter(None, address_components))

    print("current_state: ", current_state)
    title = project.expected_title or project.actual_title or "mi_story"
    print("using title: ", title)
    author = profile.first_name or ""

    html = f"""
    <div class="story-company-div-fmt1 page-break">
        <div class="story-logo-div2">
            <div style="width: 100%; margin-top: 40px;">
                <div style="display: flex; justify-content: center;">
                    <img src="{company_logo}" 
                        style="width: 300px; height: auto; object-fit: contain;"
                        alt="Bottom Logo">
                </div>
            </div>

            <h2 style="font-size: 2.8rem; margin: 20px 0; color: #333; font-weight: bold; text-align: center;">{title}</h2>
            <div class="nagaland-image-div"> 
                <img src="https://static-media.gritworks.ai/fe-images/PNG/Shikshalokam/pdf_page1_logo_fmt1.png" 
                    class="story-bg1-fmt1" alt="pdf_bg1">
                </img>
                </div>
            <div style="margin-top: 15px; text-align: center;">
                <p style="font-size: 1.2rem; margin: 5px 0; color: #555;">{author}</p>
                <p style="font-size: 1rem; color: #666; margin: 5px 0;">{address_string}</p>
            </div>
        </div>
    </div>
    """
    return html
