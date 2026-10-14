import pytest
from django.contrib.auth.models import Group, User


@pytest.fixture
def make_user(db):
    def _make(email="ana@andronautic.com", departments=(), **kwargs):
        user = User.objects.create_user(username=email, email=email, password="x", **kwargs)
        for name in departments:
            user.groups.add(Group.objects.get(name=name))
        return user

    return _make
