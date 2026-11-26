from chatbot.models import Profile


from django.db import IntegrityError, transaction


def get_or_create_token_profile(user_details, company, email, defaults):
    profile = Profile.objects.filter(userid=user_details.userId).first()
    if profile is not None:
        return profile, False, None

    if email:
        profile = Profile.objects.filter(email=email, company=company).first()
        if profile is not None:
            if profile.userid and profile.userid != user_details.userId:
                return None, False, (409, "This email is already linked to another user")
            if not profile.userid:
                profile.userid = user_details.userId
                profile.save(update_fields=["userid"])
            return profile, False, None

    try:
        with transaction.atomic():
            profile = Profile.objects.create(
                userid=user_details.userId,
                email=email,
                company=company,
                **defaults,
            )
        return profile, True, None
    except IntegrityError:
        # Another request created this user's profile first. Return it.
        profile = Profile.objects.filter(userid=user_details.userId).first()
        if profile is not None:
            return profile, False, None
        # Not a userid race, so it's the (email, company) constraint. Treat as a conflict.
        return None, False, (409, "Profile could not be created for this email")

def attach_user_to_session(session, user_details):
    """
    Saves the Elevate user ID and the user's profile (the 'result' object
    from user/read) on a session.

    - Guests (user_details is None): no-op.
    - Session bound to another user: no-op. The session is never rebound.
    - Session bound to this user with a stored profile: no-op. The first snapshot is kept.
    - Session bound to this user with no stored profile (earlier fetch failed):
      retries the fetch and saves it once it succeeds.
    - New session: saves user_id and the profile. user_id is saved even if the
      fetch fails, so the retry above can match it later.
    """
    if user_details is None:
        return

    if session.user_id and session.user_id != user_details.userId:
        return

    if session.user_id == user_details.userId and session.user_profile is not None:
        return

    profile = user_details.userProfile
    if profile is None:
        if not session.user_id:
            session.user_id = user_details.userId
            session.save(update_fields=["user_id"])
        return

    session.user_id = user_details.userId
    session.user_profile = profile
    session.save(update_fields=["user_id", "user_profile"])