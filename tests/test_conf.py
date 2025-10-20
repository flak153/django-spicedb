from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

import django_rebac.conf as conf
from django_rebac.types import TypeGraph


class TypeGraphConfigTests(SimpleTestCase):
    def tearDown(self) -> None:
        conf.reset_type_graph_cache()

    @override_settings(REBAC={"types": {"user": {}, "doc": {}}})
    def test_get_type_graph_builds_from_settings(self) -> None:
        graph = conf.get_type_graph()

        self.assertIsInstance(graph, TypeGraph)
        self.assertIn("user", graph.types)
        self.assertIn("doc", graph.types)

    @override_settings(REBAC=None)
    def test_missing_rebac_settings_raises(self) -> None:
        with self.assertRaises(ImproperlyConfigured):
            conf.get_type_graph()

    @override_settings(REBAC={"types": {"user": {}}})
    def test_cache_reused_between_calls(self) -> None:
        first = conf.get_type_graph()
        second = conf.get_type_graph()

        self.assertIs(first, second)
