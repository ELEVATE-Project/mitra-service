def attach_user_to_session(session, user_details):
    """
    Saves the Elevate user ID and the user's profile (the 'result' object
    from user/read) on a session.

    No-op for guests (user_details is None), and for sessions that already
    have a user_id, so the first snapshot is kept.
    """
    if user_details is None or session.user_id:
        return

    session.user_id = user_details.userId
    session.user_profile = user_details.userProfile
    session.save(update_fields=["user_id", "user_profile"])