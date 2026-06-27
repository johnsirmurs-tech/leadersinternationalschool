from django import template

register = template.Library()

@register.filter
def dict_key(d, key):
    if isinstance(d, dict):
        return d.get(key) or d.get(str(key))
    return None
