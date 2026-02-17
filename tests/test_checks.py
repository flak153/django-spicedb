"""Tests for django_spicedb.checks module (Django system checks)."""

import pytest
from django.core.checks import Error
from django.db import models
from django.test import override_settings

from django_spicedb.checks import check_rebac_configuration
from django_spicedb.core import (
    _REBAC_MODEL_REGISTRY,
    clear_rebac_model_registry,
    register_type,
)
from django_spicedb.models import RebacModel


@pytest.fixture(autouse=True)
def isolated_registry():
    """Save, clear, and restore the RebacModel registry around each test.

    Each checks test needs an empty registry so inline models are the only
    entries. We restore the registry afterwards so later test files still
    have the example project models registered.
    """
    saved = dict(_REBAC_MODEL_REGISTRY)
    _REBAC_MODEL_REGISTRY.clear()
    yield
    _REBAC_MODEL_REGISTRY.clear()
    _REBAC_MODEL_REGISTRY.update(saved)


class TestCheckE001_InvalidFieldReferences:
    """Test E001 error: invalid field references in relations."""

    def test_string_relation_with_nonexistent_field_triggers_e001(self):
        """Model with string relation pointing to nonexistent field triggers E001."""
        class E001StringModel(RebacModel):
            name = models.CharField(max_length=100)

            class RebacMeta:
                relations = {
                    "owner": "nonexistent_field",
                }

            class Meta:
                app_label = "tests"

        errors = check_rebac_configuration(app_configs=None)
        e001_errors = [e for e in errors if e.id == "django_spicedb.E001"]

        assert len(e001_errors) >= 1
        assert any("nonexistent_field" in str(e.msg) for e in e001_errors)
        assert any("owner" in str(e.msg) for e in e001_errors)

    def test_dict_relation_with_invalid_field_triggers_e001(self):
        """Model with dict relation spec with invalid field triggers E001."""
        class E001DictModel(RebacModel):
            name = models.CharField(max_length=100)

            class RebacMeta:
                relations = {
                    "owner": {"field": "bad_field", "subject": "user"},
                }

            class Meta:
                app_label = "tests"

        errors = check_rebac_configuration(app_configs=None)
        e001_errors = [e for e in errors if e.id == "django_spicedb.E001"]

        assert len(e001_errors) >= 1
        assert any("bad_field" in str(e.msg) for e in e001_errors)

    def test_valid_string_field_reference_passes_check(self):
        """Model with valid string field reference passes E001 check."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        register_type(User, type_name="user")

        class E001ValidStringModel(RebacModel):
            name = models.CharField(max_length=100)
            owner = models.ForeignKey(User, on_delete=models.CASCADE)

            class RebacMeta:
                relations = {
                    "owner": "owner",
                }

            class Meta:
                app_label = "tests"

        errors = check_rebac_configuration(app_configs=None)
        e001_errors = [e for e in errors if e.id == "django_spicedb.E001"]

        # Should have no E001 errors for this valid config
        assert len(e001_errors) == 0

    def test_valid_dict_field_reference_passes_check(self):
        """Model with valid dict field reference passes E001 check."""
        from django.contrib.auth import get_user_model

        User = get_user_model()
        register_type(User, type_name="user")

        class E001ValidDictModel(RebacModel):
            name = models.CharField(max_length=100)
            owner = models.ForeignKey(User, on_delete=models.CASCADE)

            class RebacMeta:
                relations = {
                    "owner": {"field": "owner"},
                }

            class Meta:
                app_label = "tests"

        errors = check_rebac_configuration(app_configs=None)
        e001_errors = [e for e in errors if e.id == "django_spicedb.E001"]

        assert len(e001_errors) == 0

    def test_multiple_invalid_fields_report_multiple_e001_errors(self):
        """Multiple invalid field references report multiple E001 errors."""
        class E001MultiModel(RebacModel):
            name = models.CharField(max_length=100)

            class RebacMeta:
                relations = {
                    "owner": "bad_owner",
                    "parent": "bad_parent",
                }

            class Meta:
                app_label = "tests"

        errors = check_rebac_configuration(app_configs=None)
        e001_errors = [e for e in errors if e.id == "django_spicedb.E001"]

        assert len(e001_errors) >= 2
        error_msgs = [str(e.msg) for e in e001_errors]
        assert any("bad_owner" in msg for msg in error_msgs)
        assert any("bad_parent" in msg for msg in error_msgs)

    def test_relation_without_field_key_in_dict_passes_check(self):
        """Dict relation without 'field' key (manual relation) passes check."""
        class E001ManualModel(RebacModel):
            name = models.CharField(max_length=100)

            class RebacMeta:
                relations = {
                    "viewer": {"subject": "user"},
                }

            class Meta:
                app_label = "tests"

        errors = check_rebac_configuration(app_configs=None)
        e001_errors = [e for e in errors if e.id == "django_spicedb.E001"]

        # Manual relations (without field) should not trigger E001
        assert len(e001_errors) == 0


class TestCheckE002_ThroughTableConfig:
    """Test E002 error: through-table configuration validation."""

    def test_through_missing_model_key_triggers_e002(self):
        """Through config missing 'model' key triggers E002."""
        class E002MissingModelModel(RebacModel):
            name = models.CharField(max_length=100)

            class RebacMeta:
                relations = {
                    "member": {"subject": "user"},
                }
                through = {
                    # Missing 'model' key
                    "object_fk": "object",
                    "subject_fk": "subject",
                }

            class Meta:
                app_label = "tests"

        errors = check_rebac_configuration(app_configs=None)
        e002_errors = [e for e in errors if e.id == "django_spicedb.E002"]

        assert len(e002_errors) >= 1
        assert any("model" in str(e.msg) for e in e002_errors)

    def test_through_missing_object_fk_triggers_e002(self):
        """Through config missing 'object_fk' triggers E002."""
        class E002MissingObjFkModel(RebacModel):
            name = models.CharField(max_length=100)

            class RebacMeta:
                relations = {
                    "member": {"subject": "user"},
                }
                through = {
                    "model": "example_project.documents.models.GroupMembership",
                    # Missing 'object_fk' key
                    "subject_fk": "user",
                }

            class Meta:
                app_label = "tests"

        errors = check_rebac_configuration(app_configs=None)
        e002_errors = [e for e in errors if e.id == "django_spicedb.E002"]

        assert len(e002_errors) >= 1
        assert any("object_fk" in str(e.msg) for e in e002_errors)

    def test_through_missing_subject_fk_triggers_e002(self):
        """Through config missing 'subject_fk' triggers E002."""
        class E002MissingSubjFkModel(RebacModel):
            name = models.CharField(max_length=100)

            class RebacMeta:
                relations = {
                    "member": {"subject": "user"},
                }
                through = {
                    "model": "example_project.documents.models.GroupMembership",
                    "object_fk": "group",
                    # Missing 'subject_fk' key
                }

            class Meta:
                app_label = "tests"

        errors = check_rebac_configuration(app_configs=None)
        e002_errors = [e for e in errors if e.id == "django_spicedb.E002"]

        assert len(e002_errors) >= 1
        assert any("subject_fk" in str(e.msg) for e in e002_errors)

    def test_complete_through_config_passes_check(self):
        """Complete through config with all required keys passes E002 check."""
        class E002CompleteModel(RebacModel):
            name = models.CharField(max_length=100)

            class RebacMeta:
                relations = {
                    "member": {"subject": "user"},
                    "manager": {"subject": "user"},
                }
                through = {
                    "model": "example_project.documents.models.GroupMembership",
                    "object_fk": "group",
                    "subject_fk": "user",
                    "role_field": "role",
                    "roles": {
                        "member": "member",
                        "manager": "manager",
                    },
                }

            class Meta:
                app_label = "tests"

        errors = check_rebac_configuration(app_configs=None)
        e002_errors = [e for e in errors if e.id == "django_spicedb.E002"]

        assert len(e002_errors) == 0

    def test_through_with_multiple_missing_keys_reports_multiple_e002(self):
        """Through config with multiple missing keys reports multiple E002 errors."""
        class E002MultiMissingModel(RebacModel):
            name = models.CharField(max_length=100)

            class RebacMeta:
                relations = {
                    "member": {"subject": "user"},
                }
                through = {
                    # Missing 'model', 'object_fk', 'subject_fk'
                    "role_field": "role",
                }

            class Meta:
                app_label = "tests"

        errors = check_rebac_configuration(app_configs=None)
        e002_errors = [e for e in errors if e.id == "django_spicedb.E002"]

        assert len(e002_errors) >= 3
        error_msgs = [str(e.msg) for e in e002_errors]
        assert any("model" in msg for msg in error_msgs)
        assert any("object_fk" in msg for msg in error_msgs)
        assert any("subject_fk" in msg for msg in error_msgs)

    def test_through_with_empty_string_values_triggers_e002(self):
        """Through config with empty string values (falsy) triggers E002."""
        class E002EmptyValModel(RebacModel):
            name = models.CharField(max_length=100)

            class RebacMeta:
                relations = {
                    "member": {"subject": "user"},
                }
                through = {
                    "model": "",  # Empty string is falsy
                    "object_fk": "group",
                    "subject_fk": "user",
                }

            class Meta:
                app_label = "tests"

        errors = check_rebac_configuration(app_configs=None)
        e002_errors = [e for e in errors if e.id == "django_spicedb.E002"]

        assert len(e002_errors) >= 1
        assert any("model" in str(e.msg) for e in e002_errors)


class TestCheckNoRegistry:
    """Test that checks handle empty or missing registry gracefully."""

    def test_check_returns_no_errors_when_registry_empty(self):
        """Checks return no errors when registry is empty."""
        errors = check_rebac_configuration(app_configs=None)

        # Should be a list, possibly empty
        assert isinstance(errors, list)
        # No errors expected when registry is empty
        assert len(errors) == 0

    def test_check_handles_model_without_rebac_meta(self):
        """Checks skip models without RebacMeta."""
        class RegularModel(models.Model):
            name = models.CharField(max_length=100)

            class Meta:
                app_label = "tests"

        # Model is created but not registered with RebacMeta
        errors = check_rebac_configuration(app_configs=None)

        # Should not raise an exception, just return the errors list
        assert isinstance(errors, list)

    def test_error_objects_have_correct_attributes(self):
        """Error objects have correct attributes (obj, id, msg)."""
        class E001AttrModel(RebacModel):
            name = models.CharField(max_length=100)

            class RebacMeta:
                relations = {
                    "owner": "nonexistent",
                }

            class Meta:
                app_label = "tests"

        errors = check_rebac_configuration(app_configs=None)
        e001_errors = [e for e in errors if e.id == "django_spicedb.E001"]

        assert len(e001_errors) >= 1
        for error in e001_errors:
            assert isinstance(error, Error)
            assert error.id == "django_spicedb.E001"
            assert error.msg is not None
            assert error.obj is not None


class TestCheckIntegrationWithExistingModels:
    """Test checks against the example project models."""

    def test_example_project_document_model_passes_checks(self):
        """Example Document model passes all system checks."""
        from example_project.documents.models import Document

        errors = check_rebac_configuration(app_configs=None)

        # Filter to only document-related errors
        doc_errors = [e for e in errors if hasattr(e, 'obj') and e.obj is Document]
        # Document model is well-configured, should not have E001/E002
        assert not any(e.id == "django_spicedb.E001" for e in doc_errors)
        assert not any(e.id == "django_spicedb.E002" for e in doc_errors)

    def test_example_project_folder_model_passes_checks(self):
        """Example Folder model passes all system checks."""
        from example_project.documents.models import Folder

        errors = check_rebac_configuration(app_configs=None)

        folder_errors = [e for e in errors if hasattr(e, 'obj') and e.obj is Folder]
        assert not any(e.id == "django_spicedb.E001" for e in folder_errors)
        assert not any(e.id == "django_spicedb.E002" for e in folder_errors)

    def test_example_project_group_model_passes_checks(self):
        """Example Group model with through config passes checks."""
        from example_project.documents.models import Group

        errors = check_rebac_configuration(app_configs=None)

        group_errors = [e for e in errors if hasattr(e, 'obj') and e.obj is Group]
        assert not any(e.id == "django_spicedb.E001" for e in group_errors)
        assert not any(e.id == "django_spicedb.E002" for e in group_errors)
