"""Exact allowlist reads. This tool boundary is not an OS sandbox."""
import hashlib
import os
import stat
from pathlib import Path, PurePosixPath


class AdmissionError(ValueError):pass


def no_links(path):
    p=Path(path).absolute()
    for part in (p,*p.parents):
        if part.exists() or part.is_symlink():
            st=part.lstat()
            if stat.S_ISLNK(st.st_mode) or getattr(st,'st_file_attributes',0)&0x400:
                raise AdmissionError('link/reparse point not admitted: '+str(part))
    return p


class Admission:
    def __init__(self,root,entries,path_maps=()):
        self.root=no_links(Path(root).resolve());self.entries={};self.paths={};self.audit=[];self.path_maps=list(path_maps)
        for e in entries:
            p=Path(e['path'])
            if not p.is_absolute():p=self.root/p
            p=no_links(p)
            try:p.relative_to(self.root)
            except ValueError:raise AdmissionError('allowlisted path outside workspace root')
            if e['id'] in self.entries:raise AdmissionError('duplicate artifact id')
            self.entries[e['id']]={**e,'absolute_path':p};self.paths[os.path.normcase(str(p))]=e['id']

    def read(self,aid):
        if aid not in self.entries:
            self.audit.append({'artifact_id':aid,'operation':'read','status':'denied'});raise AdmissionError('artifact not admitted')
        e=self.entries[aid];p=no_links(e['absolute_path'])
        data=p.read_bytes();actual=hashlib.sha256(data).hexdigest()
        if actual!=e['sha256'].lower():
            self.audit.append({'artifact_id':aid,'operation':'read','status':'hash_mismatch','actual_sha256':actual});raise AdmissionError('input hash mismatch: '+aid)
        self.audit.append({'artifact_id':aid,'operation':'read','status':'verified','sha256':actual,'bytes':len(data),'scope':e.get('access_scope','design')})
        return data

    def resolve(self,from_id,requested):
        if from_id not in self.entries:return None
        candidate=None
        for m in self.path_maps:
            prefix=m['requested_prefix'].rstrip('/')+'/'
            if requested.startswith(prefix):candidate=self.root/m['local_prefix']/requested[len(prefix):];break
        if candidate is None:
            if requested.startswith('/') or Path(requested).is_absolute():return None
            candidate=self.entries[from_id]['absolute_path'].parent/requested
        # resolve lexical '..' before allowlist lookup; never read an unlisted target.
        candidate=Path(os.path.abspath(candidate))
        try:candidate.relative_to(self.root);no_links(candidate)
        except (ValueError,AdmissionError):return None
        return self.paths.get(os.path.normcase(str(candidate)))
