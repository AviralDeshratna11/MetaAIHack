"""Verify and extract a generated learning bundle without trusting archive paths."""
import argparse
import hashlib
import json
import zipfile
from pathlib import Path


def verify(archive,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as zipped:
        if sum(i.file_size for i in zipped.infolist())>2_000_000_000: raise ValueError('Bundle exceeds 2 GB extraction budget')
        for name in zipped.namelist():
            if not (output/name).resolve().is_relative_to(output.resolve()): raise ValueError('Archive path escapes output')
        zipped.extractall(output)
    manifest=json.loads((output/'learning_manifest.json').read_text())
    for name,expected in manifest['files'].items():
        path=(output/name).resolve()
        if not path.is_relative_to(output.resolve()) or not path.is_file(): raise ValueError('Missing or unsafe manifest path')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected: raise ValueError('Artifact hash mismatch: '+name)
    return {'verified_files':len(manifest['files']),'quality':manifest['quality'],
            'accepted_training_subset':manifest['accepted_training_subset']}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('archive');parser.add_argument('--output',required=True)
    args=parser.parse_args();print(json.dumps(verify(args.archive,args.output)))
