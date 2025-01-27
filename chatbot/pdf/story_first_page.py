

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

    if current_state == "Nagaland":
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
                                <img src="https://static-media.gritworks.ai/fe-images/PNG/Shikshalokam/shikshalokam_logo_pdf.png" 
                                    class="story-logo2-fmt1" alt="pdf_bg1">
                                </img>
                                <img src="https://static-media.gritworks.ai/fe-images/PNG/GritWorks/grit-crop-logo.png" 
                                    class="story-logo3-fmt1" alt="pdf_bg1">
                                </img>
                            </div>
                        </div>
                    </div>
                </div>
                
        """
    else:
        is_special_state = current_state == "Haryana"

        html = f"""
            <div class="{'story-company-div1' if is_special_state else 'story-company-div'} page-break">
                <div class="{'story-logo-div' if is_special_state else 'story-logo-div'}">
                    <div class="{'story-normal-state-div' if is_special_state else 'story-normal-state-div'}">
                        <img src="https://static-media.gritworks.ai/fe-images/PNG/Shikshalokam/shikshalokam_logo_pdf.png" 
                             class="{'story-shikshalokam-logo' if is_special_state else 'story-shikshalokam-logo-normal'}" 
                             alt="company_logo" />
                        <img src="https://static-media.gritworks.ai/fe-images/PNG/GritWorks/grit-crop-logo.png"
                          class={'story-logo3-fmt1' if is_special_state else 'story-logo3-fmt1-normal'}
                           alt="pdf_bg1" />
                        {('<img src="https://static-media.gritworks.ai/fe-images/PNG/Shikshalokam/Govt_of_Haryana-Logo.png" '
                          'class="story-govt-logo" alt="Govt_of_Haryana-Logo" />') 
                        if is_special_state else ''}
                        {('<img src="https://static-media.gritworks.ai/fe-images/PNG/Shikshalokam/SCERT_Haryana-Logo.png" '
                          'class="story-haryana-logo" alt="SCERT_Haryana-Logo.png" />') 
                        if is_special_state else ''}
                    </div>
                </div>
                <div>
                    <img src="https://static-media.gritworks.ai/fe-images/PNG/Shikshalokam/pdf_bg0.png" 
                        class="story-bg0" alt="pdf_bg0">
                    </img>
                    <img src="https://static-media.gritworks.ai/fe-images/PNG/Shikshalokam/pdf_bg1.png" 
                        class="story-bg1" alt="pdf_bg1">
                    </img>
                    <img src="https://static-media.gritworks.ai/fe-images/PNG/Shikshalokam/pdf_bg2.png" 
                        class="story-bg2" alt="pdf_bg2">
                    </img>
                </div>
                <div class="story-details-div">
                    <p class="story-title">{title}</p>
                    <p class="story-author">{author}</p>
                </div>
            </div>
        """
    return html
