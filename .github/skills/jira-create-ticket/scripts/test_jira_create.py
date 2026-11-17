import argparse
import unittest
from unittest.mock import patch

import jira_create


class SetParentTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {"allowed_projects": ["AIST"], "epic_link_field": ""}
        self.issues = {
            "AIST-1": ("Feature", None),
            "AIST-2": ("Story", None),
            "AIST-3": ("Story", None),
            "AIST-4": ("Story", "AIST-9"),
        }
        self.updates = []

    def fake_api(self, _cfg, method, path, body=None, **_kwargs):
        if method == "GET":
            key = path.split("/issue/", 1)[1].split("?", 1)[0]
            issue_type, parent = self.issues[key]
            fields = {
                "project": {"key": "AIST"},
                "issuetype": {"name": issue_type},
                "parent": {"key": parent} if parent else None,
            }
            return {"key": key, "fields": fields}
        self.updates.append((path, body))
        return {}

    def test_links_stories_to_feature(self):
        args = argparse.Namespace(parent="AIST-1", issues=["AIST-2", "AIST-3"])
        with patch.object(jira_create, "api", side_effect=self.fake_api):
            self.assertEqual(jira_create.cmd_set_parent(self.cfg, args), 0)
        self.assertEqual(
            self.updates,
            [
                ("/rest/api/2/issue/AIST-2", {"fields": {"parent": {"key": "AIST-1"}}}),
                ("/rest/api/2/issue/AIST-3", {"fields": {"parent": {"key": "AIST-1"}}}),
            ],
        )

    def test_refuses_to_replace_different_parent_before_updates(self):
        args = argparse.Namespace(parent="AIST-1", issues=["AIST-2", "AIST-4"])
        with patch.object(jira_create, "api", side_effect=self.fake_api):
            with self.assertRaises(SystemExit) as exc:
                jira_create.cmd_set_parent(self.cfg, args)
        self.assertEqual(exc.exception.code, 3)
        self.assertEqual(self.updates, [])

    def test_refuses_non_feature_parent_before_updates(self):
        args = argparse.Namespace(parent="AIST-2", issues=["AIST-3"])
        with patch.object(jira_create, "api", side_effect=self.fake_api):
            with self.assertRaises(SystemExit) as exc:
                jira_create.cmd_set_parent(self.cfg, args)
        self.assertEqual(exc.exception.code, 3)
        self.assertEqual(self.updates, [])


if __name__ == "__main__":
    unittest.main()
