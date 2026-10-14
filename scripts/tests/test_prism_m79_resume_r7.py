import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import prism_m79_resume_r7 as resume
from training.prism_portable.common import digest


class ResumeR7Test(unittest.TestCase):
    def test_budget_and_execution_binding_refuse_drift(self):
        with tempfile.TemporaryDirectory() as d, patch.object(resume,'ROOT',Path(d)):
            root=Path(d);(root/'migration-r7').mkdir();(root/'execution-revisions').mkdir();(root/'scripts').mkdir()
            for name in ('execution.json','execution-revisions/r6.json','round-budget.json'):
                (root/name).write_text('{}')
            (root/'scripts/prism_m79_dual_dispatch.py').write_text('bound independent adapter')
            revision=dict(adapter_sha256=digest(resume.__file__),execution_sha256=digest(root/'execution.json'),
                          r6_sha256=digest(root/'execution-revisions/r6.json'),original_budget={},
                          dual_dispatch_sha256=digest(root/'scripts/prism_m79_dual_dispatch.py'))
            (root/'migration-r7/revision.json').write_text(json.dumps(revision))
            resume.verify_binding()
            (root/'round-budget.json').write_text('{"deadline":999}')
            with self.assertRaises(ValueError):resume.verify_binding()
            (root/'round-budget.json').write_text('{}');(root/'execution.json').write_text('{"changed":true}')
            with self.assertRaises(ValueError):resume.verify_binding()

    def test_unapproved_accounting_cannot_reconcile(self):
        with tempfile.TemporaryDirectory() as d,patch.object(resume,'ROOT',Path(d)),patch.object(resume,'verify_binding',return_value={}),patch.object(resume,'qualify',return_value={}):
            root=Path(d);(root/'migration-r7').mkdir()
            (root/'migration-r7/budget-authorization.json').write_text(json.dumps(dict(decision='PENDING',unobserved_cpu_charge=10000)))
            with self.assertRaises(ValueError):resume.reconcile()
            self.assertFalse((root/'pipeline/resources.json').exists())


if __name__=='__main__':unittest.main()
