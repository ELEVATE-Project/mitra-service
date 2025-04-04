from chatbot.utils.story_llama_utils import translate_field


def get_first_page_html(profile, project, voice_provider):
    profile_addresses=None
    if profile and profile.first_name:
        profile_addresses = profile.profile_address.all().first()
        company_logo = profile.company.get_public_url()
    else:
        company_logo = voice_provider.company_bot.company.get_public_url()
    print("logo: ", company_logo)
    current_state = profile_addresses.state if profile_addresses else ""
    address_components = [
        profile_addresses.district if profile_addresses and profile_addresses.district else "",
        profile_addresses.block if profile_addresses and profile_addresses.block else "",
        profile_addresses.state if profile_addresses and profile_addresses.state else ""
    ]

    address_string = ", ".join(filter(None, address_components))

    print("current_state: ", current_state)
    title = project.expected_title or project.actual_title or "mi_story"

    author = profile.first_name if profile else ""

    if project and project.project_language and project.project_language != 'en':
        if author:
            author = translate_field(
                voice_provider=voice_provider, message_body=author, target_language=project.project_language
            )
        if address_string:
            address_string = translate_field(
                voice_provider=voice_provider, message_body=address_string, target_language=project.project_language
            )

    if profile_addresses and profile_addresses.state and profile_addresses.state.lower() == 'nagaland':
        html = f"""
        <div class="story-company-div-fmt1 page-break">
            <div class="story-logo-div2">
              <div class="nagaland-logo-div">
                  <img src="https://static-media.gritworks.ai/fe-images/PNG/Shikshalokam/Samagra_Shiksha_new_bg_removed.png" 
                      style="width: 200px; height: auto; object-fit: contain;"
                      alt="Logo 1">
              
                  <img src="https://static-media.gritworks.ai/fe-images/PNG/Shikshalokam/Nagaland.png" 
                      style="width: 200px; height: auto; object-fit: contain;"
                      alt="Logo 2">
              
                  <img src="https://static-media.gritworks.ai/fe-images/PNG/Shikshalokam/SCERT nagaland.png" 
                      style="width: 200px; height: auto; object-fit: contain;"
                      alt="Logo 3">
              </div>

                <h2 style="font-size: 2.8rem; margin: 20px 0; color: #333; font-weight: bold; text-align: center;">
                    {title}
                </h2>
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
            <div  class="nagaland-company-logo-div">
                <img src="https://static-media.gritworks.ai/fe-images/PNG/Shikshalokam/shikshalokam_logo_pdf.png" 
                    style="width: 200px; height: auto; object-fit: contain;"
                alt="Logo 1">
                
                <img src="https://static-media.gritworks.ai/fe-images/PNG/Shikshalokam/shikshagrahaLogo_bg_removed.png" 
                    style="width: 200px; height: auto; object-fit: contain;"
                alt="Logo 2">
            </div>
        </div>
        """
    else:
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
    
                <h2 style="font-size: 2.8rem; margin: 20px 0; color: #333; font-weight: bold; text-align: center;">
                    {title}
                </h2>
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
