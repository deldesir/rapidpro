from django import template

register = template.Library()


@register.simple_tag
def channel_callback(channel, action: str) -> str:
    """
    Gets the URL on which courier handles the given action for the given channel
    """
    return channel.courier_url(action)
