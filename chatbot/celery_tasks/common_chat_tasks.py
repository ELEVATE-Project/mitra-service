from celery import shared_task
from channels.layers import get_channel_layer
from chatbot.models import CompanyChat, Profile, CompanyBot
from chatbot.models.geo_models import ProfileAddress


channel_layer = get_channel_layer()


@shared_task
def save_in_company_db(session_id, profile_id, initiated_by, message, chunks, status, translated_message=None):
    if initiated_by == 'AI':
        receiver = Profile.objects.get(id=profile_id)
        sender = Profile.objects.get(id=1)
    else:
        sender = Profile.objects.get(id=profile_id)
        receiver = Profile.objects.get(id=1)
    company_chat = CompanyChat(
        message=message,
        translated_message=translated_message,
        chunks=chunks,
        sender=sender,
        receiver=receiver,
        session=session_id,
        status=status,
    )
    company_chat.save()


@shared_task
def get_company_bot(profile, route):
    company = profile.company
    print(company.slug)
    company_bot = CompanyBot.objects.filter(company=company).order_by('created_at')
    print(company_bot)
    if company.slug == 'shikshalokam':
        if route == 'testimonial':
            return company_bot[2]
        profile_address = ProfileAddress.objects.get(profile=profile)
        state = profile_address.state
        if state == 'Karnataka':
            return company_bot[1]
    return company_bot[0]
