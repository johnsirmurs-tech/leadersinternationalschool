from django import template

register = template.Library()

@register.filter
def dict_key(d, key):
    if isinstance(d, dict):
        return d.get(key) or d.get(str(key))
    return None

@register.filter
def multiply(value, arg):
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0
