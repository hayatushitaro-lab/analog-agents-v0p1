"""Bounded Windows Word export with same-engine PNG fallback. Never alters input.

PDF and PNG attempts each own a fresh directory. No automatic install or repeated
retry. Only the worker and its verified new Word process may be stopped.
"""
import argparse
import hashlib
import json
import math
import shutil
import subprocess
from pathlib import Path

def pixel_size(width_points,height_points,dpi=150,max_pixels=12000000):
    if not all(math.isfinite(v) and v>0 for v in (width_points,height_points,dpi,max_pixels)):
        raise ValueError('positive finite page dimensions required')
    w=math.ceil(width_points*dpi/72);h=math.ceil(height_points*dpi/72)
    if w*h>max_pixels:raise ValueError('page exceeds pixel budget')
    return w,h

def hashfile(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def attempt(shell,source,out,mode,timeout):
    worker=Path(__file__).with_name('word_render_worker.ps1')
    args=[shell,'-NoProfile','-NonInteractive','-File',str(worker),'-Draft',str(source),'-OutputDirectory',str(out),'-Mode',mode]
    try:
        r=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
        return dict(mode=mode,status='completed' if r.returncode==0 else 'failed',exit_code=r.returncode,
                    diagnostic=r.stderr[-2000:] if r.returncode else '')
    except subprocess.TimeoutExpired:
        # The worker registered its own new COM process with creation ticks.
        # Cleanup rechecks identity, never guesses from a name or recent start.
        owner=out/'owned-word.json'
        if owner.is_file():
            cleanup=[shell,'-NoProfile','-NonInteractive','-File',str(worker),'-OwnerFile',str(owner),'-Mode','cleanup']
            try:subprocess.run(cleanup,capture_output=True,timeout=10)
            except subprocess.TimeoutExpired:pass
        return dict(mode=mode,status='timeout',reason='bounded worker timeout; no global process cleanup')

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('draft',type=Path);ap.add_argument('--out',required=True,type=Path)
    ap.add_argument('--timeout',type=int,default=60);ap.add_argument('--shell');a=ap.parse_args()
    if not 10<=a.timeout<=300:ap.error('timeout must be 10..300 seconds per attempt')
    source=a.draft.resolve(strict=True);a.out.mkdir(parents=True,exist_ok=False)
    shell=a.shell or shutil.which('pwsh') or shutil.which('powershell')
    result=dict(source_sha256=hashfile(source),status='not_rendered',attempts=[])
    if not shell:result['reason']='No Windows PowerShell/Word backend; use documents renderer and retain fields.'
    else:
        for mode in ('pdf','preview'):
            directory=a.out/mode
            r=attempt(shell,source,directory,mode,a.timeout);result['attempts'].append(r)
            if r['status']=='completed':
                doc=directory/'report.docx'
                result.update(status='rendered_requires_visual_review',mode=mode,docx=str(doc.resolve()),docx_sha256=hashfile(doc))
                break
    with (a.out/'render_status.json').open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['status']=='rendered_requires_visual_review' else 1
if __name__=='__main__':raise SystemExit(main())
