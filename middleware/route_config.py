# Route lists for RouteGuardMiddleware.
# Paths are root-relative because chatbot.urls is mounted at the project root.

# Public: no token needed. A valid token is still parsed and request.user_details is set.
GUEST_URLS = (
    # Authentication and session
    "/api/login/",
    "/api/logout/",
    "/api/generate-session/",

    # Profile
    "/api/profile/",
    "/api/user_profile/",
    "/api/create-profile/",
    "/api/profileuser/",
    "/api/profileuser/<int:pk>/",

    # Company chat and bot
    "/api/companychat/",
    "/api/companychat/<int:pk>/",
    "/api/companybot/",
    "/api/companybot/<int:pk>/",
    "/api/bot_vernacular/",
    "/api/bot_vernacular/<int:pk>/",

    # Stories
    "/api/story/",
    "/api/story/<int:pk>/",
    "/api/get-story/",
    "/api/end-story/",
    "/api/end-story/v2/",
    "/api/storymedia/",
    "/api/storymedia/<int:pk>/",

    # Chat sessions and chat APIs
    "/api/chatsession/",
    "/api/chatsession/<int:pk>/",
    "/api/chatsession/<str:session>/",
    "/api/save-company-chat/",
    "/api/create-chatsession/",
    "/api/non-llm-chat/",
    "/api/questions/save/",

    # Flow APIs
    "/api/flow-image-config/",
    "/api/flow-languages/",
    "/api/flow-connection-info/",

    # Language and speech APIs
    "/api/text_to_speech/",
    "/api/asr/",
    "/api/text_translate/",
    "/api/text_transliterate/",

    # Project and recommendation APIs
    "/api/create-project/",
    "/api/generate-recommendation/",
    "/api/sync-user-project/",

    # Location APIs
    "/api/get-location/",
    "/api/get-ip-location/",

    # PDF and file APIs
    "/api/generate-pdf/",
    "/api/generate-pdf/v2/",
    "/api/get-presigned-url/",
    "/api/image-converter/",
    "/api/media/presigned-url/",
    "/api/media/presigned-download/",

    # Media APIs
    "/api/search/",
    "/api/v1/",
    "/api/v1/media/",
    "/api/v1/documents",
    "/api/v2/media/",
    "/ai/documents/search",

    # Media tracking
    "/api/track-view/",
    "/api/track-download/",
    "/api/track-solution-download/",

    # Admin media batch APIs
    "/admin/media/batch-upload/",
    "/admin/media/batch-extract/",
    "/admin/media/batch-save/",
    "/admin/media/batch-task-status/",
    "/admin/media/retry-extract/",
    "/admin/media/retry-save/",
    "/admin/media/vector-db-task-status/",

    # Generic batch upload APIs
    "/admin/<str:app_label>/<str:model_name>/batch-upload/",
    "/admin/<str:app_label>/<str:model_name>/batch-template/",
    "/admin/<str:app_label>/<str:model_name>/batch-import/",

    # Template details
    "/api/template-details/<int:template_id>/",
)


# Protected: a valid token is required, or the guard returns 401.
AUTH_ROUTES = (
    "/api/get-profile-details/",
)