
def get_first_page_html(profile, story):
    profile_addresses = profile.profile_address.all().first()
    current_state = profile_addresses.state if profile_addresses else ""

    address_components = [
        profile_addresses.district if profile_addresses and profile_addresses.district else "",
        profile_addresses.block if profile_addresses and profile_addresses.block else "",
        profile_addresses.state if profile_addresses and profile_addresses.state else ""
    ]

    address_string = ", ".join(filter(None, address_components))

    print("current_state: ", current_state)
    title = story.title or ""
    author = profile.first_name or ""

    html = f"""
        <div class="story-company-div-fmt1 page-break">
            <div class="story-logo-div2">
                <div class=story-nagaland-logo-div>
                    <p class="story-title-fmt1">{title}</p>
                </div>
                <div class="nagaland-image-div"> 
                    <img src="https://static-media.gritworks.ai/fe-images/PNG/Shikshalokam/pdf_page1_logo_fmt1.png" 
                        class="story-bg1-fmt1" alt="pdf_bg1">
                    </img>
                    </div>
                <p class="story-author-fmt1">{author}</p>
                <p class="story-school-fmt1">{address_string}</p>

                <div class=story-firstpage-bottom-div>
                    <div class=story-firstpage-bottom-in-div>
                        <img src="https://static-media.gritworks.ai/fe-images/PNG/Shikshalokam/nagaland_govt_logo.png" 
                            class="story-logo-fmt1" alt="pdf_bg1">
                        </img>
                        <img src="https://static-media.gritworks.ai/fe-images/PNG/Shikshalokam/nagaland_samagra_logo.png" 
                            class="story-logo1-fmt1" alt="pdf_bg1">
                        </img>
                        <img src="https://static-media.gritworks.ai/fe-images/PNG/Shikshalokam/shikshagrahaLogo.png" 
                            class="story-logo2-fmt1" alt="pdf_bg1">
                        </img>
                    </div>
                </div>
            </div>
        </div>
    """
    return html
