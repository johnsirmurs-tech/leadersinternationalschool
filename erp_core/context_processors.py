def user_roles(request):
    """
    Context processor to make user roles always available in templates.
    """
    if request.user.is_authenticated:
        return {
            'user_roles': request.user.roles.all(),
            'user_role_codes': [role.code for role in request.user.roles.all()]
        }
    return {
        'user_roles': [],
        'user_role_codes': []
    }
