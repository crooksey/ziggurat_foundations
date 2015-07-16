# should hold global scoped session
DBSession = None


def groupfinder(userid, request):
    if userid and hasattr(request, 'user') and request.user:
        groups = ['group:%s' % g.group_name for g in request.user.groups]
        return groups
    return []