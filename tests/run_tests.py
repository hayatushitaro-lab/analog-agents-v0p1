"""Run tests and save a machine-readable result under the authorized run directory."""
import argparse
import json
import sys
import time
import unittest
from pathlib import Path


class RecordedResult(unittest.TextTestResult):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.cases=[]
    def addSuccess(self,test):
        super().addSuccess(test);self.cases.append({'test':test.id(),'status':'passed'})
    def addFailure(self,test,err):
        super().addFailure(test,err);self.cases.append({'test':test.id(),'status':'failed','detail':self._exc_info_to_string(err,test)})
    def addError(self,test,err):
        super().addError(test,err);self.cases.append({'test':test.id(),'status':'error','detail':self._exc_info_to_string(err,test)})
    def addSkip(self,test,reason):
        super().addSkip(test,reason);self.cases.append({'test':test.id(),'status':'skipped','reason':reason})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    started=time.perf_counter()
    suite=unittest.defaultTestLoader.discover(str(Path(__file__).parent),pattern='test_*.py')
    result=unittest.TextTestRunner(verbosity=2,resultclass=RecordedResult).run(suite)
    target=Path(a.output);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps({'tests_run':result.testsRun,'passed':len([x for x in result.cases if x['status']=='passed']),
                                 'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
                                 'successful':result.wasSuccessful(),'elapsed_seconds':round(time.perf_counter()-started,3),'cases':result.cases},ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    sys.exit(not result.wasSuccessful())
