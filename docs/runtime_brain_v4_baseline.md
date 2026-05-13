# GhostFix Brain v4 Runtime Report

- Manual errors dir: `tests\manual_errors`
- Execution mode: `in-process-decision`
- Brain enabled: yes
- Timeout seconds: 20.0
- Files evaluated: 15
- Errors detected: 13
- Total runtime seconds: 11.452

| File | Error | Source | Brain Used | Brain Skip Reason | Brain | Brain Conf | Auto-fix | Manual Review | Runtime |
| --- | --- | --- | --- | --- | --- | ---: | --- | --- | ---: |
| file_not_found.py | FileNotFoundError | hybrid: memory/retriever/brain | no | deterministic rule matched | v4-lora | 0% | no | yes | 8.016 |
| file_not_found_v2.py | FileNotFoundError | hybrid: memory/retriever/brain | no | deterministic rule matched | v4-lora | 0% | no | yes | 0.359 |
| index_error.py | IndexError | hybrid: memory/retriever/brain | no | deterministic rule matched | v4-lora | 0% | no | yes | 0.286 |
| json_empty.py | none | none | no |  | none | 0% | no | yes | 0.055 |
| json_empty_v2.py | JSONDecodeError | hybrid: memory/retriever/brain | no | deterministic rule matched | v4-lora | 0% | no | yes | 0.251 |
| key_error.py | KeyError | hybrid: memory/retriever/brain | no | deterministic rule matched | v4-lora | 0% | no | yes | 0.246 |
| missing_fake_module.py | ModuleNotFoundError | hybrid: memory/retriever/brain | no | existing decision confidence >= 85 with specific cause/fix | v4-lora | 0% | no | yes | 0.242 |
| missing_pandas.py | none | none | no |  | none | 0% | no | yes | 0.033 |
| name_error.py | NameError | hybrid: memory/retriever/brain | no | deterministic rule matched | v4-lora | 0% | no | yes | 0.242 |
| name_error_v2.py | NameError | hybrid: memory/retriever/brain | no | deterministic rule matched | v4-lora | 0% | no | yes | 0.255 |
| syntax_missing_colon.py | SyntaxError | hybrid: memory/retriever/brain | no | deterministic rule matched | v4-lora | 0% | no | yes | 0.322 |
| syntax_missing_colon_v2.py | SyntaxError | hybrid: memory/retriever/brain | no | deterministic rule matched | v4-lora | 0% | no | yes | 0.349 |
| type_error.py | TypeError | hybrid: memory/retriever/brain | no | deterministic rule matched | v4-lora | 0% | no | yes | 0.265 |
| unsafe_delete_v2.py | FileNotFoundError | hybrid: memory/retriever/brain | no | deterministic rule matched | v4-lora | 0% | no | yes | 0.277 |
| zero_division.py | ZeroDivisionError | hybrid: memory/retriever/brain | no | deterministic rule matched | v4-lora | 0% | no | yes | 0.248 |

## Details

### file_not_found.py

- Error: `FileNotFoundError`
- Cause: The file path does not exist or the file is missing.
- Fix: Check the file name/path, create the file, or use an absolute path.
- Source: `hybrid: memory/retriever/brain`
- Brain: `v4-lora` (0%)
- Brain used: no
- Brain skipped reason: deterministic rule matched
- Auto-fix available: no
- Manual review required: yes
- Runtime seconds: 8.016

### file_not_found_v2.py

- Error: `FileNotFoundError`
- Cause: The code refers to a file path that does not exist or is unavailable at runtime.
- Fix: Verify the file path or create/provide the missing file.
- Source: `hybrid: memory/retriever/brain`
- Brain: `v4-lora` (0%)
- Brain used: no
- Brain skipped reason: deterministic rule matched
- Auto-fix available: no
- Manual review required: yes
- Runtime seconds: 0.359

### index_error.py

- Error: `IndexError`
- Cause: The code is accessing an index outside the list length.
- Fix: Check list length before indexing.
- Source: `hybrid: memory/retriever/brain`
- Brain: `v4-lora` (0%)
- Brain used: no
- Brain skipped reason: deterministic rule matched
- Auto-fix available: no
- Manual review required: yes
- Runtime seconds: 0.286

### json_empty.py

- Error: `none`
- Cause: 
- Fix: 
- Source: `none`
- Brain: `none` (0%)
- Brain used: no
- Brain skipped reason: 
- Auto-fix available: no
- Manual review required: yes
- Runtime seconds: 0.055

### json_empty_v2.py

- Error: `JSONDecodeError`
- Cause: The code is parsing JSON without first checking that the input has content.
- Fix: Guard json.loads(...) with an empty-input check before parsing.
- Source: `hybrid: memory/retriever/brain`
- Brain: `v4-lora` (0%)
- Brain used: no
- Brain skipped reason: deterministic rule matched
- Auto-fix available: no
- Manual review required: yes
- Runtime seconds: 0.251

### key_error.py

- Error: `KeyError`
- Cause: The dictionary key does not exist.
- Fix: Use dict.get() or check whether the key exists before accessing it.
- Source: `hybrid: memory/retriever/brain`
- Brain: `v4-lora` (0%)
- Brain used: no
- Brain skipped reason: deterministic rule matched
- Auto-fix available: no
- Manual review required: yes
- Runtime seconds: 0.246

### missing_fake_module.py

- Error: `ModuleNotFoundError`
- Cause: The Python package 'ghostfix_missing_package_12345' is not installed in the active environment.
- Fix: Install it in the same environment: pip install ghostfix_missing_package_12345
- Source: `hybrid: memory/retriever/brain`
- Brain: `v4-lora` (0%)
- Brain used: no
- Brain skipped reason: existing decision confidence >= 85 with specific cause/fix
- Auto-fix available: no
- Manual review required: yes
- Runtime seconds: 0.242

### missing_pandas.py

- Error: `none`
- Cause: 
- Fix: 
- Source: `none`
- Brain: `none` (0%)
- Brain used: no
- Brain skipped reason: 
- Auto-fix available: no
- Manual review required: yes
- Runtime seconds: 0.033

### name_error.py

- Error: `NameError`
- Cause: A variable or function is used before it is defined.
- Fix: Define the missing variable/function before using it, or check for spelling mistakes.
- Source: `hybrid: memory/retriever/brain`
- Brain: `v4-lora` (0%)
- Brain used: no
- Brain skipped reason: deterministic rule matched
- Auto-fix available: no
- Manual review required: yes
- Runtime seconds: 0.242

### name_error_v2.py

- Error: `NameError`
- Cause: The variable 'summarytableheaderstyle' is used before it is defined. Evidence: Traceback points to /opt/baculabackupreport/./baculabackupreport.py line 2300 where `+ '<tr style="' + summarytableheaderstyle + '"><th colspan="2" style="' \` failed.
- Fix: jobtableheadercolor = '#1c1cad'
jobtableheadertxtcolor = '#000000'
summarytableheadercolor = '#1c1cad'
summarytableheadertxtcolor = '#000000'
- Source: `hybrid: memory/retriever/brain`
- Brain: `v4-lora` (0%)
- Brain used: no
- Brain skipped reason: deterministic rule matched
- Auto-fix available: no
- Manual review required: yes
- Runtime seconds: 0.255

### syntax_missing_colon.py

- Error: `SyntaxError`
- Cause: The class definition is missing a colon.
- Fix: Add a colon at the end of the class line.
- Source: `hybrid: memory/retriever/brain`
- Brain: `v4-lora` (0%)
- Brain used: no
- Brain skipped reason: deterministic rule matched
- Auto-fix available: no
- Manual review required: yes
- Runtime seconds: 0.322

### syntax_missing_colon_v2.py

- Error: `SyntaxError`
- Cause: The class definition is missing a colon.
- Fix: Add a colon at the end of the class line.
- Source: `hybrid: memory/retriever/brain`
- Brain: `v4-lora` (0%)
- Brain used: no
- Brain skipped reason: deterministic rule matched
- Auto-fix available: no
- Manual review required: yes
- Runtime seconds: 0.349

### type_error.py

- Error: `TypeError`
- Cause: Operation is being used with incompatible data types.
- Fix: Convert types properly, for example use str(value), int(value), or matching data types.
- Source: `hybrid: memory/retriever/brain`
- Brain: `v4-lora` (0%)
- Brain used: no
- Brain skipped reason: deterministic rule matched
- Auto-fix available: no
- Manual review required: yes
- Runtime seconds: 0.265

### unsafe_delete_v2.py

- Error: `FileNotFoundError`
- Cause: The code refers to a file path that does not exist or is unavailable at runtime.
- Fix: Verify the file path or create/provide the missing file.
- Source: `hybrid: memory/retriever/brain`
- Brain: `v4-lora` (0%)
- Brain used: no
- Brain skipped reason: deterministic rule matched
- Auto-fix available: no
- Manual review required: yes
- Runtime seconds: 0.277

### zero_division.py

- Error: `ZeroDivisionError`
- Cause: The code is dividing by zero.
- Fix: Check denominator value before division.
- Source: `hybrid: memory/retriever/brain`
- Brain: `v4-lora` (0%)
- Brain used: no
- Brain skipped reason: deterministic rule matched
- Auto-fix available: no
- Manual review required: yes
- Runtime seconds: 0.248
