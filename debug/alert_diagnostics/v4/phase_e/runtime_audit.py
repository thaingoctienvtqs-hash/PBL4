"""Instrumented offline audit. Denies DB/network writes and writes outside Phase E."""
import builtins
import contextlib
import io
import json
import os
import socket
import sqlite3
import sys
from pathlib import Path
from unittest import mock
from .replay import BASE,new_output_directory,write_json

def main():
    root=BASE.resolve()
    attempted=[]
    writes=[]
    original_open=builtins.open
    original_io_open=io.open
    original_mkdir=os.mkdir

    def blocked(operation):
        def call(*args,**kwargs):
            attempted.append(operation)
            raise RuntimeError("Offline audit blocked "+operation)
        return call

    def check_path(path,mode):
        if isinstance(path,int):return
        target=Path(path).resolve()
        if target!=root and root not in target.parents:
            attempted.append("write_outside_phase_e")
            raise PermissionError("Write must stay inside Phase E")
        if target.exists() and any(char in mode for char in "wa+"):
            attempted.append("overwrite_existing_artifact")
            raise FileExistsError("Existing artifacts cannot be overwritten")
        writes.append({"path":str(target.relative_to(root)),"mode":mode})

    def guarded_open(original):
        def call(file,mode="r",*args,**kwargs):
            if any(char in mode for char in "wax+"):check_path(file,mode)
            return original(file,mode,*args,**kwargs)
        return call

    def mkdir(path,*args,**kwargs):
        check_path(path,"mkdir")
        return original_mkdir(path,*args,**kwargs)

    output=io.StringIO()
    with contextlib.ExitStack() as stack:
        for name in ("sqlite3.connect","sqlite3.dbapi2.connect","socket.create_connection","socket.socket.connect",
                     "os.remove","os.unlink","os.rename","os.replace"):
            stack.enter_context(mock.patch(name,side_effect=blocked(name)))
        stack.enter_context(mock.patch("builtins.open",side_effect=guarded_open(original_open)))
        stack.enter_context(mock.patch("io.open",side_effect=guarded_open(original_io_open)))
        stack.enter_context(mock.patch("os.mkdir",side_effect=mkdir))
        from . import run_tests
        with contextlib.redirect_stdout(output):
            code=run_tests.main()
    text=output.getvalue()
    print(text,end="")
    directory=new_output_directory(BASE/"runtime_audits")
    report={"runner_exit":code,"blocked_operation_attempts":attempted,"write_accesses":writes,
            "all_observed_writes_inside_phase_e":not attempted,
            "sqlite3_import_note":"Frozen v3 comparison imports EventStore; module import does not open a database.",
            "forbidden_AI_modules_loaded":[k for k in ("torch","detectron2","cv2","fastapi","pyodbc") if k in sys.modules],
            "captured_runner_output":text}
    write_json(directory/"runtime_guard_verification.json",report)
    print("Runtime guard report:",directory)
    print("Blocked operation attempts:",len(attempted))
    return code if not attempted else 2

if __name__=="__main__":sys.exit(main())
