import sqlalchemy as sa
import hashlib
import random
import string
import six

from collections import namedtuple
from datetime import datetime, timedelta
from paginate_sqlalchemy import SqlalchemyOrmPage
from sqlalchemy.ext.declarative import declared_attr

try:
    from pyramid.security import Allow, Deny, ALL_PERMISSIONS
except ImportError as e:
    Allow = 'Allow'
    Deny = 'Deny'
    # borrowed directly from pyramid - to avoid dependency on pyramid itself
    # source https://github.com/Pylons/pyramid/blob/master/pyramid/security.py

    class AllPermissionsList(object):

        """ Stand in 'permission list' to represent all permissions """

        def __iter__(self):
            return ()

        def __contains__(self, other):
            return True

        def __eq__(self, other):
            return isinstance(other, self.__class__)

    ALL_PERMISSIONS = AllPermissionsList()

__version__ = '0.2'
DBSession = None


class ANY_PERMISSION_CLS(object):
    def __eq__(self, other):
        return '__any_permission__' == other

    def __ne__(self, other):
        return '__any_permission__' != other


ANY_PERMISSION = ANY_PERMISSION_CLS()

PermissionTuple = namedtuple('PermissionTuple',
                             ['user', 'perm_name', 'type', 'group', 'resource',
                              'owner', 'allowed'])


def resource_permissions_for_users(model, perm_names, resource_ids=None,
                                   user_ids=None, group_ids=None,
                                   resource_types=None,
                                   limit_group_permissions=False,
                                   skip_user_perms=False,
                                   skip_group_perms=False,
                                   db_session=None):
    """
    Returns permission tuples that match one of passed permission names
    perm_names - list of permissions that can be matched
    user_ids - restrict to specific users
    group_ids - restrict to specific groups
    resource_ids - restrict to specific resources
    limit_group_permissions - should be used if we do not want to have
    user objects returned for group permissions, this might cause performance
    issues for big groups
    """
    db_session = get_db_session(db_session, model)
    query = db_session.query(model._ziggurat_models.GroupResourcePermission.perm_name,
                             model._ziggurat_models.User,
                             model._ziggurat_models.Group,
                             sa.literal('group').label('type'),
                             model._ziggurat_models.Resource
    )
    if limit_group_permissions:
        query = query.outerjoin(model._ziggurat_models.User, model._ziggurat_models.User.id == None)
    else:
        query = query.filter(model._ziggurat_models.User.id == model._ziggurat_models.UserGroup.user_id)

    query = query.filter(
        model._ziggurat_models.Resource.resource_id == model._ziggurat_models.GroupResourcePermission.resource_id)
    query = query.filter(
        model._ziggurat_models.Group.id == model._ziggurat_models.GroupResourcePermission.group_id)
    if resource_ids:
        query = query.filter(
            model._ziggurat_models.GroupResourcePermission.resource_id.in_(resource_ids))
    if resource_types:
        query = query.filter(model._ziggurat_models.Resource.resource_type.in_(resource_types))
    query = query.filter(model._ziggurat_models.UserGroup.group_id ==
                         model._ziggurat_models.GroupResourcePermission.group_id)
    if (perm_names not in ([ANY_PERMISSION], ANY_PERMISSION) and perm_names):
        query = query.filter(
            model._ziggurat_models.GroupResourcePermission.perm_name.in_(perm_names))
    if group_ids:
        query = query.filter(
            model._ziggurat_models.GroupResourcePermission.group_id.in_(group_ids))
    if user_ids:
        query = query.filter(
            model._ziggurat_models.UserGroup.user_id.in_(user_ids))
    query2 = db_session.query(model._ziggurat_models.UserResourcePermission.perm_name,
                              model._ziggurat_models.User,
                              model._ziggurat_models.Group,
                              sa.literal('user').label('type'),
                              model._ziggurat_models.Resource)
    # group needs to be present to work for union, but never actually matched
    query2 = query2.outerjoin(model._ziggurat_models.Group, model._ziggurat_models.Group.id == None)
    query2 = query2.filter(model._ziggurat_models.User.id ==
                           model._ziggurat_models.UserResourcePermission.user_id)
    query2 = query2.filter(
        model._ziggurat_models.Resource.resource_id == model._ziggurat_models.UserResourcePermission.resource_id)
    if (perm_names not in ([ANY_PERMISSION], ANY_PERMISSION) and perm_names):
        query2 = query2.filter(
            model._ziggurat_models.UserResourcePermission.perm_name.in_(perm_names))
    if resource_ids:
        query2 = query2.filter(
            model._ziggurat_models.UserResourcePermission.resource_id.in_(resource_ids))
    if resource_types:
        query2 = query2.filter(model._ziggurat_models.Resource.resource_type.in_(resource_types))
    if user_ids:
        query2 = query2.filter(
            model._ziggurat_models.UserResourcePermission.user_id.in_(user_ids))

    if not skip_group_perms and not skip_user_perms:
        query = query.union(query2)
    elif skip_group_perms:
        query = query2

    users = [PermissionTuple(row.User, row.perm_name, row.type,
                             row.Group or None, row.Resource, False, True)
             for row in query]
    return users


def get_db_session(session=None, obj=None):
    """ utility function that attempts to return sqlalchemy session that could
    have been created/passed in one of few ways:

    * It first tries to read session attached to instance
      if object argument was passed

    * then it tries to return  session passed as argument

    * finally tries to read pylons-like threadlocal called DBSession

    * if this fails exception is thrown """
    # try to read the session from instance
    if obj:
        return sa.orm.session.object_session(obj)
    # try passed session
    elif session:
        return session
    # try global pylons-like session then
    elif DBSession:
        return DBSession
    raise Exception('No Session found')


def groupfinder(userid, request):
    if userid and hasattr(request, 'user') and request.user:
        groups = ['group:%s' % g.group_name for g in request.user.groups]
        return groups
    return []


class BaseModel(object):
    """ Basic class that all other classes inherit from that supplies some
    basic methods useful for interaction with packages like:
    deform, colander or wtforms """

    @classmethod
    def _get_keys(cls):
        """ returns column names for this model """
        return sa.orm.class_mapper(cls).c.keys()

    def get_dict(self, exclude_keys=None, include_keys=None):
        """ return dictionary of keys and values corresponding to this model's
        data
        if include_keys is null the function will return all keys

        ::arg include_keys (optional) is a list of columns from model that
        should be returned by this function
        ::arg exclude_keys (optional) is a list of columns from model that
        should not be returned by this function
        """
        d = {}
        exclude_keys_list = exclude_keys or []
        include_keys_list = include_keys or []
        for k in self._get_keys():
            if k not in exclude_keys_list and \
                    (k in include_keys_list or not include_keys):
                d[k] = getattr(self, k)
        return d

    def get_appstruct(self):
        """ return list of tuples keys and values corresponding to this model's
        data """
        l = []
        for k in self._get_keys():
            l.append((k, getattr(self, k),))
        return l

    def populate_obj(self, appstruct):
        """ updates instance properties with dictionary values *for keys that
        exist* for this model """
        for k in self._get_keys():
            if k in appstruct:
                setattr(self, k, appstruct[k])

    def get_db_session(self, session=None):
        """ Attempts to return session via get_db_session utility function
        :meth:`~ziggurat_foundations.models.get_db_session`"""
        return get_db_session(session, self)

    def persist(self, flush=False, db_session=None):
        """
        Adds object to session, if the object was freshly created this will
        persist the object in the storage on commit

        :param flush: boolean - if true then the session will be flushed
        instantly
        :param db_session:
        :return:
        """
        db_session = get_db_session(db_session)
        db_session.add(self)
        if flush:
            db_session.flush()

    def delete(self, db_session=None):
        """ Deletes the object via session, this will permanently delete the
        object from storage on commit """
        db_session = get_db_session(db_session, self)
        db_session.delete(self)

    @classmethod
    def base_query(cls, db_session=None):
        """
        Returns a base query object one can use to search on simple properties
        :param db_session:
        :return:
        """
        return get_db_session(db_session).query(cls)


class ModelManager(object):
    pass


class UserManager(ModelManager):
    @property
    def permissions(self):
        """ returns all non-resource permissions based on what groups user
            belongs and directly set ones for this user"""
        db_session = get_db_session(None, self)
        query = db_session.query(
            self._ziggurat_models.GroupPermission.group_id.label('owner_id'),
            self._ziggurat_models.GroupPermission.perm_name.label('perm_name'),
            sa.literal('group').label('type'))
        query = query.filter(self._ziggurat_models.GroupPermission.group_id ==
                             self._ziggurat_models.UserGroup.group_id)
        query = query.filter(self._ziggurat_models.User.id == self._ziggurat_models.UserGroup.user_id)
        query = query.filter(self._ziggurat_models.User.id == self.id)

        query2 = db_session.query(
            self._ziggurat_models.UserPermission.user_id.label('owner_id'),
            self._ziggurat_models.UserPermission.perm_name.label('perm_name'),
            sa.literal('user').label('type'))
        query2 = query2.filter(self._ziggurat_models.UserPermission.user_id == self.id)
        query = query.union(query2)
        groups_dict = dict([(g.id, g) for g in self.groups])
        return [PermissionTuple(self,
                                row.perm_name,
                                row.type,
                                groups_dict.get(
                                    row.owner_id) if row.type == 'group' else None,
                                None, False, True) for row in query]

    def resources_with_perms(self, perms, resource_ids=None,
                             resource_types=None,
                             db_session=None):
        """ returns all resources that user has perms for,
            note that at least one perm needs to be met,
            resource_ids restricts the search to specific resources"""
        # owned entities have ALL permissions so we return those resources too
        # even without explict perms set
        # TODO: implement admin superrule perm - maybe return all apps
        db_session = get_db_session(db_session, self)
        query = db_session.query(self._ziggurat_models.Resource).distinct()
        group_ids = [gr.id for gr in self.groups]
        # if user has some groups lets try to join based on their permissions
        if group_ids:
            join_conditions = (
                self._ziggurat_models.GroupResourcePermission.group_id.in_(group_ids),
                self._ziggurat_models.Resource.resource_id == self._ziggurat_models.GroupResourcePermission.resource_id,
                self._ziggurat_models.GroupResourcePermission.perm_name.in_(perms),)
            query = query.outerjoin(
                (self._ziggurat_models.GroupResourcePermission,
                 sa.and_(*join_conditions),)
            )
            # ensure outerjoin permissions are correct -
            # dont add empty rows from join
            # conditions are - join ON possible group permissions
            # OR owning group/user
            query = query.filter(sa.or_(
                self._ziggurat_models.Resource.owner_user_id == self.id,
                self._ziggurat_models.Resource.owner_group_id.in_(group_ids),
                self._ziggurat_models.GroupResourcePermission.perm_name != None, ))
        else:
            # filter just by username
            query = query.filter(self._ziggurat_models.Resource.owner_user_id ==
                                 self.id)
        # lets try by custom user permissions for resource
        query2 = db_session.query(self._ziggurat_models.Resource).distinct()
        query2 = query2.filter(self._ziggurat_models.UserResourcePermission.user_id ==
                               self.id)
        query2 = query2.filter(self._ziggurat_models.Resource.resource_id ==
                               self._ziggurat_models.UserResourcePermission.resource_id)
        query2 = query2.filter(
            self._ziggurat_models.UserResourcePermission.perm_name.in_(perms))
        if resource_ids:
            query = query.filter(self._ziggurat_models.Resource.resource_id.in_(resource_ids))
            query2 = query2.filter(self._ziggurat_models.Resource.resource_id.in_(resource_ids))

        if resource_types:
            query = query.filter(
                self._ziggurat_models.Resource.resource_type.in_(resource_types))
            query2 \
                = query2.filter(self._ziggurat_models.Resource.resource_type.in_(resource_types))
        query = query.union(query2)
        query = query.order_by(self._ziggurat_models.Resource.resource_name)
        return query

    def groups_with_resources(self):
        """ Returns a list of groups users belongs to with eager loaded
        resources owned by those groups """

        return self.groups_dynamic.options(
            sa.orm.eagerload(self._ziggurat_models.Group.resources))

    def resources_with_possible_perms(self, resource_ids=None,
                                      resource_types=None,
                                      db_session=None):
        """ returns list of permissions and resources for this user,
            resource_ids restricts the search to specific resources"""
        perms = resource_permissions_for_users(self, ANY_PERMISSION,
                                               resource_ids=resource_ids,
                                               user_ids=[self.id],
                                               db_session=db_session)
        for resource in self.resources:
            perms.append(PermissionTuple(self, ALL_PERMISSIONS, 'user', None,
                                         resource, True, True))
        for group in self.groups_with_resources():
            for resource in group.resources:
                perms.append(
                    PermissionTuple(self, ALL_PERMISSIONS, 'group', group,
                                    resource, True, True))

        return perms


    def gravatar_url(self, default='mm', **kwargs):
        """ returns user gravatar url """
        # construct the url
        hash = hashlib.md5(self.email.encode('utf8').lower()).hexdigest()
        if 'd' not in kwargs:
            kwargs['d'] = default
        params = '&'.join([six.moves.urllib.parse.urlencode({key: value})
                           for key, value in kwargs.items()])
        return "https://secure.gravatar.com/avatar/{}?{}" \
            .format(hash, params)

    def set_password(self, raw_password):
        """ sets new password """
        self.user_password = self.passwordmanager.encode(raw_password)
        self.regenerate_security_code()

    def check_password(self, raw_password):
        """ checks string with users password hash"""
        return self.passwordmanager.check(self.user_password, raw_password,
                                          setter=self.set_password)

    @classmethod
    def generate_random_pass(cls, chars=7):
        """ generates random string of fixed length"""
        return cls.generate_random_string(chars)

    def regenerate_security_code(self):
        """ generates new security code"""
        self.security_code = self.generate_random_string(64)

    @staticmethod
    def generate_random_string(chars=7):
        return u''.join(random.sample(string.ascii_letters * 2 + string.digits,
                                      chars))

    @classmethod
    def by_id(cls, user_id, db_session=None):
        """ fetch user by user name """
        db_session = get_db_session(db_session)
        query = db_session.query(cls)
        query = query.filter(cls.id == user_id)
        query = query.options(sa.orm.eagerload('groups'))
        return query.first()

    @classmethod
    def by_user_name(cls, user_name, db_session=None):
        """ fetch user by user name """
        db_session = get_db_session(db_session)
        query = db_session.query(cls)
        query = query.filter(sa.func.lower(cls.user_name) ==
                             (user_name or '').lower())
        query = query.options(sa.orm.eagerload('groups'))
        return query.first()

    @classmethod
    def by_user_name_and_security_code(cls, user_name, security_code,
                                       db_session=None):
        """ fetch user objects by user name and security code"""
        db_session = get_db_session(db_session)
        query = db_session.query(cls)
        query = query.filter(sa.func.lower(cls.user_name) ==
                             (user_name or '').lower())
        query = query.filter(cls.security_code == security_code)
        return query.first()

    @classmethod
    def by_user_names(cls, user_names, db_session=None):
        """ fetch user objects by user names """
        user_names = [(name or '').lower() for name in user_names]
        db_session = get_db_session(db_session)
        query = db_session.query(cls)
        query = query.filter(sa.func.lower(cls.user_name).in_(user_names))
        # q = q.options(sa.orm.eagerload(cls.groups))
        return query

    @classmethod
    def user_names_like(cls, user_name, db_session=None):
        """
        fetch users with similar names

        For now rely on LIKE in db - shouldnt be issue ever
        in future we can plug in fulltext search like solr or whoosh
        """
        db_session = get_db_session(db_session)
        query = db_session.query(cls)
        query = query.filter(sa.func.lower(cls.user_name).
                             like((user_name or '').lower()))
        query = query.order_by(cls.user_name)
        # q = q.options(sa.orm.eagerload('groups'))
        return query

    @classmethod
    def by_email(cls, email, db_session=None):
        """ fetch user object by email """
        db_session = get_db_session(db_session)
        query = db_session.query(cls).filter(
            sa.func.lower(cls.email) == (email or '').lower())
        query = query.options(sa.orm.eagerload('groups'))
        return query.first()

    @classmethod
    def by_email_and_username(cls, email, user_name, db_session=None):
        """ fetch user object by email and username """
        db_session = get_db_session(db_session)
        query = db_session.query(cls).filter(cls.email == email)
        query = query.filter(sa.func.lower(cls.user_name) ==
                             (user_name or '').lower())
        query = query.options(sa.orm.eagerload('groups'))
        return query.first()

    @classmethod
    def users_for_perms(cls, perm_names, db_session=None):
        """ return users hat have one of given permissions """
        db_session = get_db_session(db_session)
        query = db_session.query(cls)
        query = query.filter(cls._ziggurat_models.User.id == cls._ziggurat_models.UserGroup.user_id)
        query = query.filter(cls._ziggurat_models.UserGroup.group_id ==
                             cls._ziggurat_models.GroupPermission.group_id)
        query = query.filter(
            cls._ziggurat_models.GroupPermission.perm_name.in_(perm_names))

        query2 = db_session.query(cls)
        query2 = query2.filter(cls._ziggurat_models.User.id ==
                               cls._ziggurat_models.UserPermission.user_id)
        query2 = query2.filter(cls._ziggurat_models.UserPermission.perm_name.in_(perm_names))
        users = query.union(query2).order_by(cls.id)
        return users


class ExternalIdentityManager(ModelManager):
    @classmethod
    def by_external_id_and_provider(cls, external_id, provider_name,
                                    db_session=None):
        db_session = get_db_session(db_session)
        query = db_session.query(cls)
        query = query.filter(cls.external_id == external_id)
        query = query.filter(cls.provider_name == provider_name)
        return query.first()

    @classmethod
    def user_by_external_id_and_provider(cls, external_id, provider_name,
                                         db_session=None):
        db_session = get_db_session(db_session)
        query = db_session.query(cls._ziggurat_models.User)
        query = query.filter(cls.external_id == external_id)
        query = query.filter(cls._ziggurat_models.User.user_name == cls.local_user_name)
        query = query.filter(cls.provider_name == provider_name)
        return query.first()


class GroupManager(ModelManager):
    @classmethod
    def all(cls, db_session=None):
        """ return all groups"""
        query = get_db_session(db_session).query(cls)
        return query

    @classmethod
    def by_group_name(cls, group_name, db_session=None):
        """ fetch group by name"""
        db_session = get_db_session(db_session)
        query = db_session.query(cls).filter(cls.group_name == group_name)
        return query.first()

    @sa.orm.validates('permissions')
    def validate_permission(self, key, permission):
        """ validates if group can get assigned with permission"""
        assert permission.perm_name in self.__possible_permissions__
        return permission

    def get_user_paginator(self, page=1, item_count=None, items_per_page=50,
                           user_ids=None, GET_params=None):
        """ returns paginator over users belonging to the group"""
        if not GET_params:
            GET_params = {}
        GET_params.pop('page', None)
        query = self.users_dynamic
        if user_ids:
            query = query.filter(self._ziggurat_models.UserGroup.user_id.in_(user_ids))
        return SqlalchemyOrmPage(query, page=page, item_count=item_count,
                                 items_per_page=items_per_page,
                                 **GET_params)

    def resources_with_possible_perms(self, perm_names=None, resource_ids=None,
                                      resource_types=None,
                                      db_session=None):
        """ returns list of permissions and resources for this group,
            resource_ids restricts the search to specific resources"""
        db_session = get_db_session(db_session, self)
        perms = []

        query = db_session.query(self._ziggurat_models.GroupResourcePermission.perm_name,
                                 self._ziggurat_models.Group,
                                 self._ziggurat_models.Resource
        )
        query = query.filter(
            self._ziggurat_models.Resource.resource_id == self._ziggurat_models.GroupResourcePermission.resource_id)
        query = query.filter(
            self._ziggurat_models.Group.id == self._ziggurat_models.GroupResourcePermission.group_id)
        if resource_ids:
            query = query.filter(
                self._ziggurat_models.GroupResourcePermission.resource_id.in_(resource_ids))

        if resource_types:
            query = query.filter(
                self._ziggurat_models.Resource.resource_type.in_(resource_types))

        if (perm_names not in (
                [ANY_PERMISSION], ANY_PERMISSION) and perm_names):
            query = query.filter(
                self._ziggurat_models.GroupResourcePermission.perm_name.in_(perm_names))
        query = query.filter(self._ziggurat_models.GroupResourcePermission.group_id == self.id)

        perms = [PermissionTuple(None, row.perm_name, 'group',
                                 self, row.Resource, False, True)
                 for row in query]
        for resource in self.resources:
            perms.append(PermissionTuple(None, ALL_PERMISSIONS, 'group', self,
                                         resource, True, True))
        return perms


class GroupPermissionManager(ModelManager):
    @classmethod
    def by_group_and_perm(cls, group_id, perm_name, db_session=None):
        """" return by by_user_and_perm and permission name """
        db_session = get_db_session(db_session)
        query = db_session.query(cls).filter(cls.group_id == group_id)
        query = query.filter(cls.perm_name == perm_name)
        return query.first()


class UserPermissionManager(ModelManager):
    @classmethod
    def by_user_and_perm(cls, user_id, perm_name, db_session=None):
        """ return by user and permission name"""
        db_session = get_db_session(db_session)
        query = db_session.query(cls).filter(cls.user_id == user_id)
        query = query.filter(cls.perm_name == perm_name)
        return query.first()


class UserResourcePermissionManager(ModelManager):
    @classmethod
    def by_resource_user_and_perm(cls, user_id, perm_name, resource_id,
                                  db_session=None):
        """ return all instances by user name, perm name and resource id """
        db_session = get_db_session(db_session)
        query = db_session.query(cls).filter(cls.user_id == user_id)
        query = query.filter(cls.resource_id == resource_id)
        query = query.filter(cls.perm_name == perm_name)
        return query.first()


        # @classmethod
        # def allowed_permissions(cls, key):
        #        """ ensures we can only use permission that can be assigned
        #            to this resource type"""
        #        if key in cls.__possible_permissions__:
        #            return key
        #        raise KeyError


class ResourceManager(ModelManager):
    def perms_for_user(self, user, db_session=None):
        """ returns all permissions that given user has for this resource
            from groups and directly set ones too"""
        db_session = get_db_session(db_session, self)
        query = db_session.query(
            self._ziggurat_models.GroupResourcePermission.group_id.label('owner_id'),
            self._ziggurat_models.GroupResourcePermission.perm_name,
            sa.literal('group').label('type'))
        query = query.filter(self._ziggurat_models.GroupResourcePermission.group_id.in_(
            [gr.id for gr in user.groups]
        )
        )
        query = query.filter(self._ziggurat_models.GroupResourcePermission.resource_id ==
                             self.resource_id)

        query2 = db_session.query(
            self._ziggurat_models.UserResourcePermission.user_id.label('owner_id'),
            self._ziggurat_models.UserResourcePermission.perm_name,
            sa.literal('user').label('type'))
        query2 = query2.filter(self._ziggurat_models.UserResourcePermission.user_id ==
                               user.id)
        query2 = query2.filter(self._ziggurat_models.UserResourcePermission.resource_id ==
                               self.resource_id)
        query = query.union(query2)

        groups_dict = dict([(g.id, g) for g in user.groups])
        perms = [PermissionTuple(user,
                                 row.perm_name,
                                 row.type,
                                 groups_dict.get(row.owner_id) if
                                 row.type == 'group' else None,
                                 self, False, True) for row in query]

        # include all perms if user is the owner of this resource
        if self.owner_user_id == user.id:
            perms.append(PermissionTuple(user, ALL_PERMISSIONS, 'user',
                                         None, self, True, True))
        groups_dict = dict([(g.id, g) for g in user.groups])
        if self.owner_group_id in groups_dict:
            perms.append(PermissionTuple(user, ALL_PERMISSIONS, 'group',
                                         groups_dict.get(self.owner_group_id),
                                         self, True, True))

        return perms

    def direct_perms_for_user(self, user, db_session=None):
        """ returns permissions that given user has for this resource
            without ones inherited from groups that user belongs to"""
        db_session = get_db_session(db_session, self)
        query = db_session.query(self._ziggurat_models.UserResourcePermission.user_id,
                                 self._ziggurat_models.UserResourcePermission.perm_name)
        query = query.filter(self._ziggurat_models.UserResourcePermission.user_id ==
                             user.id)
        query = query.filter(self._ziggurat_models.UserResourcePermission.resource_id ==
                             self.resource_id)

        perms = [PermissionTuple(user,
                                 row.perm_name,
                                 'user',
                                 None,
                                 self, False, True) for row in query]

        # include all perms if user is the owner of this resource
        if self.owner_user_id == user.id:
            perms.append(PermissionTuple(user, ALL_PERMISSIONS, 'user',
                                         None, self, True))
        return perms

    def group_perms_for_user(self, user, db_session=None):
        """ returns permissions that given user has for this resource
            that are inherited from groups """
        db_session = get_db_session(db_session, self)
        perms = resource_permissions_for_users(self, ANY_PERMISSION,
                                               resource_ids=[self.resource_id],
                                               user_ids=[user.id],
                                               db_session=None)
        perms = [p for p in perms if p.type == 'group']
        # include all perms if user is the owner of this resource
        groups_dict = dict([(g.id, g) for g in user.groups])
        if self.owner_group_id in groups_dict:
            perms.append(PermissionTuple(user, ALL_PERMISSIONS, 'group',
                                         groups_dict.get(self.owner_group_id),
                                         self, True, True))
        return perms

    def users_for_perm(self, perm_name, user_ids=None, group_ids=None,
                       limit_group_permissions=False, skip_group_perms=False,
                       db_session=None):
        """ return PermissionTuples for users AND groups that have given
        permission for the resource, perm_name is __any_permission__ then
        users with any permission will be listed
        user_ids - limits the permissions to specific user ids,
        group_ids - limits the permissions to specific group ids,
        """
        db_session = get_db_session(db_session, self)
        users_perms = resource_permissions_for_users(self, [perm_name],
                                                     [self.resource_id],
                                                     user_ids=user_ids,
                                                     group_ids=group_ids,
                                                     limit_group_permissions=limit_group_permissions,
                                                     skip_group_perms=skip_group_perms,
                                                     db_session=db_session)
        if self.owner_user_id:
            users_perms.append(
                PermissionTuple(self.owner,
                                ALL_PERMISSIONS, 'user', None, self, True,
                                True))
        if self.owner_group_id and not skip_group_perms:
            for user in self.owner_group.users:
                users_perms.append(
                    PermissionTuple(user, ALL_PERMISSIONS, 'group',
                                    self.owner_group, self, True, True))

        return users_perms

    @classmethod
    def by_resource_id(cls, resource_id, db_session=None):
        """ fetch the resouce by id """
        db_session = get_db_session(db_session)
        query = db_session.query(cls).filter(cls.resource_id ==
                                             int(resource_id))
        return query.first()

    @classmethod
    def all(cls, db_session=None):
        """ fetch all permissions"""
        query = get_db_session(db_session).query(cls)
        return query

    @classmethod
    def perm_by_group_and_perm_name(cls, res_id, group_id, perm_name,
                                    db_session=None):
        """ fetch permissions by group and permission name"""
        db_session = get_db_session(db_session)
        query = db_session.query(cls._ziggurat_models.GroupResourcePermission)
        query = query.filter(
            cls._ziggurat_models.GroupResourcePermission.group_id == group_id)
        query = query.filter(
            cls._ziggurat_models.GroupResourcePermission.perm_id == perm_name)
        query = query.filter(cls._ziggurat_models.GroupResourcePermission.resource_id == res_id)
        return query.first()

    def groups_for_perm(self, perm_name, group_ids=None,
                        limit_group_permissions=False,
                        db_session=None):
        """ return PermissionTuples for groups that have given
        permission for the resource, perm_name is __any_permission__ then
        users with any permission will be listed
        user_ids - limits the permissions to specific user ids,
        group_ids - limits the permissions to specific group ids,
        """
        db_session = get_db_session(db_session, self)
        group_perms = resource_permissions_for_users(self, [perm_name],
                                                     [self.resource_id],
                                                     group_ids=group_ids,
                                                     limit_group_permissions=limit_group_permissions,
                                                     skip_user_perms=True,
                                                     db_session=db_session)
        if self.owner_group_id:
            for user in self.owner_group.users:
                group_perms.append(
                    PermissionTuple(user, ALL_PERMISSIONS, 'group',
                                    self.owner_group, self, True, True))

        return group_perms

    @sa.orm.validates('user_permissions', 'group_permissions')
    def validate_permission(self, key, permission):
        """ validate if resouce can have specific permission """
        assert permission.perm_name in self.__possible_permissions__
        return permission

    @classmethod
    def subtree_deeper(cls, object_id, limit_depth=1000000, flat=True,
                       db_session=None):
        """ This returns you subree of ordered objects relative
        to the start object id currently only postgresql
        """
        raw_q = """
            WITH RECURSIVE subtree AS (
                    SELECT res.*, 1 as depth, array[ordering] as sorting FROM
                    resources res WHERE res.resource_id = :id
                  UNION ALL
                    SELECT res_u.*, depth+1 as depth,
                    (st.sorting || ARRAY[res_u.ordering] ) as sort
                    FROM resources res_u, subtree st
                    WHERE res_u.parent_id = st.resource_id
            )
            SELECT * FROM subtree WHERE depth<=:depth ORDER BY sorting;
        """
        db_session = get_db_session(db_session)
        q = db_session.query(cls).from_statement(raw_q).params(id=object_id,
                                                               depth=limit_depth)
        return q

    @classmethod
    def path_upper(cls, object_id, limit_depth=1000000, flat=True,
                   db_session=None):
        """ This returns you path to root node starting from object_id
            currently only for postgresql
        """
        raw_q = """
            WITH RECURSIVE subtree AS (
                    SELECT res.*, 1 as depth FROM resources res
                    WHERE res.resource_id = :id
                  UNION ALL
                    SELECT res_u.*, depth+1 as depth
                    FROM resources res_u, subtree st
                    WHERE res_u.resource_id = st.parent_id
            )
            SELECT * FROM subtree WHERE depth<=:depth;
        """
        db_session = get_db_session(db_session)
        q = db_session.query(cls).from_statement(raw_q).params(id=object_id,
                                                               depth=limit_depth)
        return q


class UserMixin(UserManager, BaseModel):
    """ Base mixin for user object representation.
        It supplies all the basic functionality from password hash generation
        and matching to utility methods used for querying database for users
        and their permissions or resources they have access to. It is meant
        to be extended with other application specific properties"""

    __mapper_args__ = {}
    __table_args__ = {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8'
    }

    @declared_attr
    def __tablename__(self):
        return 'users'

    @declared_attr
    def id(self):
        """ Unique identifier of user object"""
        return sa.Column(sa.Integer, primary_key=True, autoincrement=True)

    @declared_attr
    def user_name(self):
        """ Unique user name user object"""
        return sa.Column(sa.Unicode(30), unique=True)

    @declared_attr
    def user_password(self):
        """ Password hash for user object """
        return sa.Column(sa.String(256))

    @declared_attr
    def email(self):
        """ Email for user object """
        return sa.Column(sa.Unicode(100), nullable=False, unique=True)

    @declared_attr
    def status(self):
        """ Status of user object """
        return sa.Column(sa.SmallInteger(), nullable=False, default=1)

    @declared_attr
    def security_code(self):
        """ Security code user object (can be used for password reset etc. """
        return sa.Column(sa.String(256), default='default')

    @declared_attr
    def last_login_date(self):
        """ Date of user's last login """
        return sa.Column(sa.TIMESTAMP(timezone=False),
                         default=lambda x: datetime.utcnow(),
                         server_default=sa.func.now())

    @declared_attr
    def registered_date(self):
        """ Date of user's registration """
        return sa.Column(sa.TIMESTAMP(timezone=False),
                         default=lambda x: datetime.utcnow(),
                         server_default=sa.func.now())

    @declared_attr
    def security_code_date(self):
        """ Date of user's security code update """
        return sa.Column(sa.TIMESTAMP(timezone=False),
                         default=datetime(2000, 1, 1),
                         server_default='2000-01-01 01:01')

    def __repr__(self):
        return '<User: %s>' % self.user_name

    @declared_attr
    def groups_dynamic(self):
        """ returns dynamic relationship for groups - allowing for
        filtering of data """
        return sa.orm.relationship('Group', secondary='users_groups',
                                   lazy='dynamic',
                                   passive_deletes=True,
                                   passive_updates=True)

    @declared_attr
    def user_permissions(self):
        """
        returns all direct non-resource permissions for this user,
        allows to assign new permissions to user::

            user.user_permissions.append(resource)
        """
        return sa.orm.relationship('UserPermission',
                                   cascade="all, delete-orphan",
                                   passive_deletes=True,
                                   passive_updates=True)

    @declared_attr
    def resource_permissions(self):
        """ returns all direct resource permissions for this user """
        return sa.orm.relationship('UserResourcePermission',
                                   cascade="all, delete-orphan",
                                   passive_deletes=True,
                                   passive_updates=True
        )

    @declared_attr
    def resources(cls):
        """ Returns all resources directly owned by user, can be used to assign
        ownership of new resources::

            user.resources.append(resource) """
        return sa.orm.relationship('Resource',
                                   cascade="all",
                                   passive_deletes=True,
                                   passive_updates=True,
                                   backref='owner',
                                   lazy='dynamic')

    @declared_attr
    def external_identities(self):
        """ dynamic relation for external identities for this user -
        allowing for filtering of data """
        return sa.orm.relationship('ExternalIdentity',
                                   lazy='dynamic',
                                   cascade="all, delete-orphan",
                                   passive_deletes=True,
                                   passive_updates=True,
                                   backref='owner')


class ExternalIdentityMixin(ExternalIdentityManager, BaseModel):
    @declared_attr
    def __tablename__(self):
        return 'external_identities'

    @declared_attr
    def external_id(self):
        return sa.Column(sa.Unicode(255), default=u'', primary_key=True)

    @declared_attr
    def external_user_name(self):
        return sa.Column(sa.Unicode(255), default=u'')

    @declared_attr
    def local_user_name(self):
        return sa.Column(sa.Unicode(50), sa.ForeignKey('users.user_name',
                                                       onupdate='CASCADE',
                                                       ondelete='CASCADE'),
                         primary_key=True)

    @declared_attr
    def provider_name(self):
        return sa.Column(sa.Unicode(50), default=u'', primary_key=True)

    @declared_attr
    def access_token(self):
        return sa.Column(sa.String(255), default=u'')

    @declared_attr
    def alt_token(self):
        return sa.Column(sa.String(255), default=u'')

    @declared_attr
    def token_secret(self):
        return sa.Column(sa.String(255), default=u'')


class GroupMixin(GroupManager, BaseModel):
    """ base mixin for group object"""

    __table_args__ = {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8'}

    @declared_attr
    def __tablename__(self):
        return 'groups'

    # lists app wide permissions we might want to assign to groups
    __possible_permissions__ = ()

    @declared_attr
    def id(self):
        return sa.Column(sa.Integer(), primary_key=True, )

    @declared_attr
    def group_name(self):
        return sa.Column(sa.Unicode(128), nullable=False)

    @declared_attr
    def description(self):
        return sa.Column(sa.Text())

    @declared_attr
    def member_count(self):
        return sa.Column(sa.Integer, nullable=False, default=0)

    @declared_attr
    def users(self):
        """ relationship for users belonging to this group"""
        return sa.orm.relationship('User',
                                   secondary='users_groups',
                                   order_by='User.user_name',
                                   passive_deletes=True,
                                   passive_updates=True,
                                   backref='groups')

    # dynamic property - useful
    @declared_attr
    def users_dynamic(self):
        """ dynamic relationship for users belonging to this group
            one can use filter """
        return sa.orm.relationship('User',
                                   secondary='users_groups',
                                   order_by='User.user_name',
                                   lazy="dynamic")

    @declared_attr
    def permissions(self):
        """ non-resource permissions assigned to this group"""
        return sa.orm.relationship('GroupPermission',
                                   backref='groups',
                                   cascade="all, delete-orphan",
                                   passive_deletes=True,
                                   passive_updates=True)

    @declared_attr
    def resource_permissions(self):
        """ permissions to specific resources this group has"""
        return sa.orm.relationship('GroupResourcePermission',
                                   backref='groups',
                                   cascade="all, delete-orphan",
                                   passive_deletes=True,
                                   passive_updates=True)

    @declared_attr
    def resources(cls):
        """ Returns all resources directly owned by group, can be used to assign
        ownership of new resources::

            user.resources.append(resource) """
        return sa.orm.relationship('Resource',
                                   cascade="all",
                                   passive_deletes=True,
                                   passive_updates=True,
                                   backref='owner_group')

    @declared_attr
    def resources_dynamic(cls):
        """ Returns all resources directly owned by group, can be used to assign
        ownership of new resources::

            user.resources.append(resource) """
        return sa.orm.relationship('Resource',
                                   cascade="all",
                                   passive_deletes=True,
                                   passive_updates=True,
                                   lazy='dynamic')

    def __repr__(self):
        return '<Group: %s, %s>' % (self.group_name, self.id)


class GroupPermissionMixin(GroupPermissionManager, BaseModel):
    """ group permission mixin """

    __table_args__ = {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8'}

    @declared_attr
    def __tablename__(self):
        return 'groups_permissions'

    @declared_attr
    def group_id(self):
        return sa.Column(sa.Integer(),
                         sa.ForeignKey('groups.id', onupdate='CASCADE',
                                       ondelete='CASCADE'), primary_key=True)

    @declared_attr
    def perm_name(self):
        return sa.Column(sa.Unicode(30), primary_key=True)

    def __repr__(self):
        return '<GroupPermission: %s>' % self.perm_name


class UserPermissionMixin(UserPermissionManager, BaseModel):
    __table_args__ = {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8'}

    @declared_attr
    def __tablename__(self):
        return 'users_permissions'

    @declared_attr
    def user_id(self):
        return sa.Column(sa.Integer,
                         sa.ForeignKey('users.id', onupdate='CASCADE',
                                       ondelete='CASCADE'), primary_key=True)

    @declared_attr
    def perm_name(self):
        return sa.Column(sa.Unicode(30), primary_key=True)

    def __repr__(self):
        return '<UserPermission: %s>' % self.perm_name


class UserGroupMixin(BaseModel):
    __table_args__ = {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8'}

    @declared_attr
    def __tablename__(self):
        return 'users_groups'

    @declared_attr
    def group_id(self):
        return sa.Column(sa.Integer,
                         sa.ForeignKey('groups.id', onupdate='CASCADE',
                                       ondelete='CASCADE'), primary_key=True)

    @declared_attr
    def user_id(self):
        return sa.Column(sa.Integer,
                         sa.ForeignKey('users.id', onupdate='CASCADE',
                                       ondelete='CASCADE'), primary_key=True)

    def __repr__(self):
        return '<UserGroup: g:%s, u:%s>' % (self.group_id, self.user_id,)


class GroupResourcePermissionMixin(BaseModel):
    __table_args__ = {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8'}

    @declared_attr
    def __tablename__(self):
        return 'groups_resources_permissions'

    @declared_attr
    def group_id(self):
        return sa.Column(sa.Integer, sa.ForeignKey('groups.id',
                                                   onupdate='CASCADE',
                                                   ondelete='CASCADE'),
                         primary_key=True)

    @declared_attr
    def resource_id(self):
        return sa.Column(sa.Integer(),
                         sa.ForeignKey('resources.resource_id',
                                       onupdate='CASCADE',
                                       ondelete='CASCADE'),
                         primary_key=True,
                         autoincrement=False)

    @declared_attr
    def perm_name(self):
        return sa.Column(sa.Unicode(50), primary_key=True)

    def __repr__(self):
        return '<GroupResourcePermission: g:%s, %s, r:%s>' % (self.group_id,
                                                              self.perm_name,
                                                              self.resource_id,)


class UserResourcePermissionMixin(UserResourcePermissionManager, BaseModel):
    __table_args__ = {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8'}

    @declared_attr
    def __tablename__(self):
        return 'users_resources_permissions'

    @declared_attr
    def user_id(self):
        return sa.Column(sa.Integer, sa.ForeignKey('users.id',
                                                   onupdate='CASCADE',
                                                   ondelete='CASCADE'),
                         primary_key=True)

    @declared_attr
    def resource_id(self):
        return sa.Column(sa.Integer(),
                         sa.ForeignKey('resources.resource_id',
                                       onupdate='CASCADE',
                                       ondelete='CASCADE'),
                         primary_key=True,
                         autoincrement=False)

    @declared_attr
    def perm_name(self):
        return sa.Column(sa.Unicode(50), primary_key=True)

    def __repr__(self):
        return '<userResourcePermission: %s, %s, %s>' % (self.user_id,
                                                         self.perm_name,
                                                         self.resource_id,)


class ResourceMixin(ResourceManager, BaseModel):
    __possible_permissions__ = ()

    @declared_attr
    def __tablename__(self):
        return 'resources'

    @declared_attr
    def resource_id(self):
        return sa.Column(sa.Integer(), primary_key=True, nullable=False,
                         autoincrement=True)

    @declared_attr
    def parent_id(self):
        return sa.Column(sa.Integer(),
                         sa.ForeignKey('resources.resource_id',
                                       onupdate='CASCADE', ondelete='SET NULL'))

    @declared_attr
    def ordering(self):
        return sa.Column(sa.Integer(), default=0, nullable=False)

    @declared_attr
    def resource_name(self):
        return sa.Column(sa.Unicode(100), nullable=False)

    @declared_attr
    def resource_type(self):
        return sa.Column(sa.Unicode(30), nullable=False)

    @declared_attr
    def owner_group_id(self):
        return sa.Column(sa.Integer,
                         sa.ForeignKey('groups.id', onupdate='CASCADE',
                                       ondelete='SET NULL'), index=True)

    @declared_attr
    def owner_user_id(self):
        return sa.Column(sa.Integer,
                         sa.ForeignKey('users.id', onupdate='CASCADE',
                                       ondelete='SET NULL'), index=True)

    @declared_attr
    def group_permissions(self):
        """ returns all group permissions for this resource"""
        return sa.orm.relationship('GroupResourcePermission',
                                   cascade="all, delete-orphan",
                                   passive_deletes=True,
                                   passive_updates=True)

    @declared_attr
    def user_permissions(self):
        """ returns all user permissions for this resource"""
        return sa.orm.relationship('UserResourcePermission',
                                   cascade="all, delete-orphan",
                                   passive_deletes=True,
                                   passive_updates=True)

    @declared_attr
    def groups(self):
        """ returns all groups that have permissions for this resource"""
        return sa.orm.relationship('Group',
                                   secondary='groups_resources_permissions',
                                   passive_deletes=True,
                                   passive_updates=True)

    @declared_attr
    def users(self):
        """ returns all users that have permissions for this resource"""
        return sa.orm.relationship('User',
                                   secondary='users_resources_permissions',
                                   passive_deletes=True,
                                   passive_updates=True)

    __mapper_args__ = {'polymorphic_on': resource_type}
    __table_args__ = {'mysql_engine': 'InnoDB', 'mysql_charset': 'utf8'}

    def __repr__(self):
        return '<Resource: %s, %s, id: %s>' % (self.resource_type,
                                               self.resource_name,
                                               self.resource_id,)

    @property
    def __acl__(self):
        raise Exception("The model should have implemented __acl__")
