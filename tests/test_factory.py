import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from django_rebac.adapters import factory
from tests.conftest import RecordingAdapter


@pytest.fixture(autouse=True)
def reset_factory():
    factory.reset_adapter()
    yield
    factory.reset_adapter()


def test_get_adapter_requires_configuration():
    with override_settings(REBAC={}):
        factory.reset_adapter()
        with pytest.raises(ImproperlyConfigured):
            factory.get_adapter()


def test_get_adapter_returns_cached_instance():
    adapter = RecordingAdapter()
    factory.set_adapter(adapter)
    assert factory.get_adapter() is adapter
    factory.reset_adapter()


def test_get_adapter_uses_settings_configuration():
    config = {
        "types": {},
        "adapter": {
            "endpoint": "localhost:50051",
            "token": "test-token",
            "insecure": True,
        },
    }
    with override_settings(REBAC=config):
        adapter = factory.get_adapter()
        assert adapter is factory.get_adapter()
        factory.reset_adapter()
